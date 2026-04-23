//! Speaker playback via `cpal`.
//!
//! Clients push PCM16 mono samples at the daemon's canonical rate. We queue
//! them in a ring buffer consumed by the cpal output callback, upsampling to
//! the device's native rate as needed. The queue is bounded; overflow drops
//! the oldest samples to keep the playback tail close to real time.

use std::collections::VecDeque;
use std::sync::mpsc as std_mpsc;
use std::sync::{Arc, Mutex};
use std::thread;

use anyhow::{anyhow, Context, Result};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{Device, SampleFormat, StreamConfig};
use tracing::{error, info, warn};

use crate::resample::Resampler;

/// Shared ring buffer holding resampled PCM16 samples at the device's native
/// rate. Indexed mono samples; stereo devices duplicate on drain.
type SampleQueue = Arc<Mutex<VecDeque<i16>>>;

/// Public handle: clients push source-rate mono samples; the playback thread
/// resamples and enqueues them for the cpal callback.
pub struct PlaybackHandle {
    queue: SampleQueue,
    resampler: Arc<Mutex<Resampler>>,
    max_queued: usize,
    channels: u16,
    _shutdown: std_mpsc::Sender<()>,
    thread: Option<thread::JoinHandle<()>>,
}

impl PlaybackHandle {
    /// Enqueue mono PCM16 samples at the daemon's canonical rate. Samples
    /// are resampled to the device's native rate and stored for playback.
    pub fn push(&self, samples: &[i16]) {
        if samples.is_empty() {
            return;
        }
        let mut resampled = Vec::with_capacity(samples.len());
        {
            let mut r = self.resampler.lock().unwrap();
            r.process(samples, &mut resampled);
        }
        let mut q = self.queue.lock().unwrap();
        // For stereo devices we interleave the mono stream into both channels.
        if self.channels >= 2 {
            for s in resampled {
                for _ in 0..self.channels {
                    q.push_back(s);
                }
            }
        } else {
            q.extend(resampled);
        }
        // Drop oldest samples if we've outpaced the speaker; keeps latency
        // bounded instead of letting the queue grow forever.
        let max = self.max_queued;
        while q.len() > max {
            q.pop_front();
        }
    }

    /// Drop all queued samples (handles the `stop_output` control message).
    pub fn clear(&self) {
        self.queue.lock().unwrap().clear();
    }
}

impl Drop for PlaybackHandle {
    fn drop(&mut self) {
        // `_shutdown` dropping closes the channel, waking the thread's recv.
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
    }
}

pub fn start_playback(device_name: Option<&str>, source_rate: u32) -> Result<PlaybackHandle> {
    let (ready_tx, ready_rx) = std_mpsc::channel::<Result<(u32, u16)>>();
    let (shutdown_tx, shutdown_rx) = std_mpsc::channel::<()>();
    let device_name_owned = device_name.map(str::to_owned);

    // The queue is created before the thread so the main thread and the cpal
    // callback share the same `Arc`. We size it generously later once we know
    // the device rate, but bound it to ~2 s in any case.
    let queue: SampleQueue = Arc::new(Mutex::new(VecDeque::new()));
    let queue_for_thread = Arc::clone(&queue);

    let thread = thread::Builder::new()
        .name("jarvis-audio-playback".into())
        .spawn(move || {
            match build_and_play(device_name_owned.as_deref(), queue_for_thread) {
                Ok((stream, device_rate, device_channels)) => {
                    let _ = ready_tx.send(Ok((device_rate, device_channels)));
                    let _ = shutdown_rx.recv();
                    drop(stream);
                }
                Err(e) => {
                    let _ = ready_tx.send(Err(e));
                }
            }
        })
        .context("failed to spawn playback thread")?;

    let (device_rate, channels) = match ready_rx.recv() {
        Ok(Ok(v)) => v,
        Ok(Err(e)) => {
            let _ = thread.join();
            return Err(e);
        }
        Err(_) => return Err(anyhow!("playback thread died before signalling readiness")),
    };

    Ok(PlaybackHandle {
        queue,
        resampler: Arc::new(Mutex::new(Resampler::new(source_rate, device_rate))),
        // 2 seconds of device-rate audio, across all channels.
        max_queued: (device_rate as usize * channels as usize) * 2,
        channels,
        _shutdown: shutdown_tx,
        thread: Some(thread),
    })
}

fn build_and_play(device_name: Option<&str>, queue: SampleQueue) -> Result<(cpal::Stream, u32, u16)> {
    let host = cpal::default_host();
    let device = pick_output_device(&host, device_name)?;
    let name = device.name().unwrap_or_else(|_| "<unknown>".to_string());
    let supported = device
        .default_output_config()
        .with_context(|| format!("no default output config for device {name:?}"))?;
    let sample_format = supported.sample_format();
    let device_rate = supported.sample_rate().0;
    let channels = supported.channels();
    let config: StreamConfig = supported.into();

    info!(
        device = %name,
        device_rate,
        channels,
        ?sample_format,
        "starting speaker playback"
    );

    let err_fn = |err| error!(?err, "cpal output stream error");

    let stream = match sample_format {
        SampleFormat::F32 => {
            let q = Arc::clone(&queue);
            device.build_output_stream(
                &config,
                move |out: &mut [f32], _| fill_f32(out, &q),
                err_fn,
                None,
            )
        }
        SampleFormat::I16 => {
            let q = Arc::clone(&queue);
            device.build_output_stream(
                &config,
                move |out: &mut [i16], _| fill_i16(out, &q),
                err_fn,
                None,
            )
        }
        SampleFormat::U16 => {
            let q = Arc::clone(&queue);
            device.build_output_stream(
                &config,
                move |out: &mut [u16], _| fill_u16(out, &q),
                err_fn,
                None,
            )
        }
        other => return Err(anyhow!("unsupported output sample format: {other:?}")),
    }
    .context("failed to build cpal output stream")?;

    stream.play().context("failed to start cpal output stream")?;
    Ok((stream, device_rate, channels))
}

fn pick_output_device(host: &cpal::Host, name: Option<&str>) -> Result<Device> {
    if let Some(n) = name {
        for d in host.output_devices().context("listing output devices")? {
            if d.name().map(|dn| dn == n).unwrap_or(false) {
                return Ok(d);
            }
        }
        return Err(anyhow!("output device {n:?} not found"));
    }
    host.default_output_device()
        .ok_or_else(|| anyhow!("no default output device"))
}

// ---- Output fillers ---------------------------------------------------------

fn fill_f32(out: &mut [f32], queue: &SampleQueue) {
    let mut q = queue.lock().unwrap();
    let mut underrun = false;
    for slot in out.iter_mut() {
        match q.pop_front() {
            Some(s) => *slot = s as f32 / i16::MAX as f32,
            None => {
                *slot = 0.0;
                underrun = true;
            }
        }
    }
    if underrun {
        // Not fatal; happens naturally when the caller hasn't streamed audio.
        warn!("playback buffer underrun");
    }
}

fn fill_i16(out: &mut [i16], queue: &SampleQueue) {
    let mut q = queue.lock().unwrap();
    for slot in out.iter_mut() {
        *slot = q.pop_front().unwrap_or(0);
    }
}

fn fill_u16(out: &mut [u16], queue: &SampleQueue) {
    let mut q = queue.lock().unwrap();
    for slot in out.iter_mut() {
        let s = q.pop_front().unwrap_or(0) as i32;
        *slot = (s + 0x8000) as u16;
    }
}
