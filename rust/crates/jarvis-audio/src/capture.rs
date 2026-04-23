//! Microphone capture via `cpal`.
//!
//! The cpal callback runs on an OS audio thread and is strictly non-blocking.
//! We push PCM16 mono samples at the daemon's canonical rate into a
//! `crossbeam-channel`, and a dedicated "framer" task drains that channel,
//! accumulates samples into fixed-size frames, feeds each frame through the
//! VAD, and forwards them to the async broadcast layer.

use std::sync::mpsc as std_mpsc;
use std::thread;

use anyhow::{anyhow, Context, Result};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{Device, SampleFormat, StreamConfig};
use crossbeam_channel::{bounded, Sender};
use tracing::{error, info, warn};

use crate::resample::Resampler;

/// A single 16 kHz mono PCM16 frame emitted by the framer.
#[derive(Debug, Clone)]
pub struct CapturedFrame {
    pub pcm: Vec<i16>,
    /// Wall-clock-agnostic sample-count-derived timestamp (ms since the
    /// first emitted frame on this capture stream). Monotonic and stable
    /// across system clock jumps.
    pub ts_ms: u64,
}

/// Owns the thread that hosts the cpal input stream. `cpal::Stream` is
/// `!Send` on several platforms (ALSA, CoreAudio), so we build and hold it
/// on a dedicated OS thread and signal shutdown through a oneshot channel.
pub struct CaptureHandle {
    shutdown: Option<std_mpsc::Sender<()>>,
    thread: Option<thread::JoinHandle<()>>,
}

impl Drop for CaptureHandle {
    fn drop(&mut self) {
        if let Some(tx) = self.shutdown.take() {
            let _ = tx.send(());
        }
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
    }
}

/// Start a cpal input stream on a dedicated OS thread. Raw device samples
/// are converted to mono PCM16 at `target_rate` and sent on `tx`.
pub fn start_capture(
    device_name: Option<&str>,
    target_rate: u32,
    tx: Sender<Vec<i16>>,
) -> Result<CaptureHandle> {
    let (ready_tx, ready_rx) = std_mpsc::channel::<Result<()>>();
    let (shutdown_tx, shutdown_rx) = std_mpsc::channel::<()>();
    let device_name_owned = device_name.map(str::to_owned);

    let thread = thread::Builder::new()
        .name("jarvis-audio-capture".into())
        .spawn(move || {
            match build_and_play(device_name_owned.as_deref(), target_rate, tx) {
                Ok(stream) => {
                    // Signal successful start; keep the stream alive until
                    // shutdown signal arrives. `stream` drops on thread exit.
                    let _ = ready_tx.send(Ok(()));
                    let _ = shutdown_rx.recv();
                    drop(stream);
                }
                Err(e) => {
                    let _ = ready_tx.send(Err(e));
                }
            }
        })
        .context("failed to spawn capture thread")?;

    match ready_rx.recv() {
        Ok(Ok(())) => Ok(CaptureHandle {
            shutdown: Some(shutdown_tx),
            thread: Some(thread),
        }),
        Ok(Err(e)) => {
            let _ = thread.join();
            Err(e)
        }
        Err(_) => Err(anyhow!("capture thread died before signalling readiness")),
    }
}

fn build_and_play(
    device_name: Option<&str>,
    target_rate: u32,
    tx: Sender<Vec<i16>>,
) -> Result<cpal::Stream> {
    let host = cpal::default_host();
    let device = pick_input_device(&host, device_name)?;
    let device_name = device.name().unwrap_or_else(|_| "<unknown>".to_string());
    let supported = device
        .default_input_config()
        .with_context(|| format!("no default input config for device {device_name:?}"))?;
    let sample_format = supported.sample_format();
    let src_rate = supported.sample_rate().0;
    let src_channels = supported.channels();
    let config: StreamConfig = supported.into();

    info!(
        device = %device_name,
        src_rate,
        src_channels,
        ?sample_format,
        target_rate,
        "starting microphone capture"
    );

    let mut resampler = Resampler::new(src_rate, target_rate);
    let channels = src_channels as usize;
    let err_fn = |err| error!(?err, "cpal input stream error");

    let stream = match sample_format {
        SampleFormat::F32 => device.build_input_stream(
            &config,
            move |data: &[f32], _| handle_f32_chunk(data, channels, &mut resampler, &tx),
            err_fn,
            None,
        ),
        SampleFormat::I16 => device.build_input_stream(
            &config,
            move |data: &[i16], _| handle_i16_chunk(data, channels, &mut resampler, &tx),
            err_fn,
            None,
        ),
        SampleFormat::U16 => device.build_input_stream(
            &config,
            move |data: &[u16], _| handle_u16_chunk(data, channels, &mut resampler, &tx),
            err_fn,
            None,
        ),
        other => return Err(anyhow!("unsupported input sample format: {other:?}")),
    }
    .context("failed to build cpal input stream")?;

    stream.play().context("failed to start cpal input stream")?;
    Ok(stream)
}

/// Run the framer loop: drain `rx`, accumulate into `frame_samples`-length
/// PCM16 buffers, and call `on_frame` for each completed frame. This runs on
/// a dedicated OS thread since it bridges the sync cpal producer into the
/// async world without pulling tokio into the callback.
pub fn spawn_framer<F>(
    rx: crossbeam_channel::Receiver<Vec<i16>>,
    frame_samples: usize,
    sample_rate: u32,
    mut on_frame: F,
) -> thread::JoinHandle<()>
where
    F: FnMut(CapturedFrame) + Send + 'static,
{
    thread::Builder::new()
        .name("jarvis-audio-framer".into())
        .spawn(move || {
            let mut buf: Vec<i16> = Vec::with_capacity(frame_samples * 2);
            let mut emitted_samples: u64 = 0;
            while let Ok(chunk) = rx.recv() {
                buf.extend_from_slice(&chunk);
                while buf.len() >= frame_samples {
                    let frame: Vec<i16> = buf.drain(..frame_samples).collect();
                    let ts_ms = emitted_samples * 1_000 / sample_rate as u64;
                    emitted_samples += frame_samples as u64;
                    on_frame(CapturedFrame { pcm: frame, ts_ms });
                }
            }
        })
        .expect("failed to spawn framer thread")
}

fn pick_input_device(host: &cpal::Host, name: Option<&str>) -> Result<Device> {
    if let Some(n) = name {
        for d in host.input_devices().context("listing input devices")? {
            if d.name().map(|dn| dn == n).unwrap_or(false) {
                return Ok(d);
            }
        }
        return Err(anyhow!("input device {n:?} not found"));
    }
    host.default_input_device()
        .ok_or_else(|| anyhow!("no default input device"))
}

// ---- Sample-format adapters -------------------------------------------------

fn handle_f32_chunk(data: &[f32], channels: usize, resampler: &mut Resampler, tx: &Sender<Vec<i16>>) {
    let mono = downmix_f32(data, channels);
    let pcm: Vec<i16> = mono
        .into_iter()
        .map(|s| (s.clamp(-1.0, 1.0) * i16::MAX as f32) as i16)
        .collect();
    let mut out = Vec::with_capacity(pcm.len());
    resampler.process(&pcm, &mut out);
    forward(tx, out);
}

fn handle_i16_chunk(data: &[i16], channels: usize, resampler: &mut Resampler, tx: &Sender<Vec<i16>>) {
    let mono = downmix_i16(data, channels);
    let mut out = Vec::with_capacity(mono.len());
    resampler.process(&mono, &mut out);
    forward(tx, out);
}

fn handle_u16_chunk(data: &[u16], channels: usize, resampler: &mut Resampler, tx: &Sender<Vec<i16>>) {
    // u16 samples are unsigned PCM with silence at 0x8000.
    let signed: Vec<i16> = data.iter().map(|&u| (u as i32 - 0x8000) as i16).collect();
    let mono = downmix_i16(&signed, channels);
    let mut out = Vec::with_capacity(mono.len());
    resampler.process(&mono, &mut out);
    forward(tx, out);
}

fn downmix_f32(data: &[f32], channels: usize) -> Vec<f32> {
    if channels <= 1 {
        return data.to_vec();
    }
    data.chunks(channels)
        .map(|frame| frame.iter().sum::<f32>() / channels as f32)
        .collect()
}

fn downmix_i16(data: &[i16], channels: usize) -> Vec<i16> {
    if channels <= 1 {
        return data.to_vec();
    }
    data.chunks(channels)
        .map(|frame| {
            let sum: i32 = frame.iter().map(|&s| s as i32).sum();
            (sum / channels as i32) as i16
        })
        .collect()
}

fn forward(tx: &Sender<Vec<i16>>, pcm: Vec<i16>) {
    if pcm.is_empty() {
        return;
    }
    // Non-blocking send: if the framer is lagging, we drop rather than stall
    // the audio callback.
    if let Err(crossbeam_channel::TrySendError::Full(_)) = tx.try_send(pcm) {
        warn!("framer channel full; dropping capture chunk");
    }
}

/// Helper to allocate the producer/consumer pair for capture. A bounded
/// channel gives us back-pressure; we size it for ~1 second of audio so
/// short stalls don't drop frames.
pub fn make_capture_channel(sample_rate: u32) -> (Sender<Vec<i16>>, crossbeam_channel::Receiver<Vec<i16>>) {
    // Each chunk from cpal is typically a few tens of ms of samples; 64
    // entries is plenty even at high sample rates.
    bounded::<Vec<i16>>((sample_rate as usize / 1024).max(32))
}
