//! `jarvis-audio` — OpenJarvis audio daemon entry point.
//!
//! Pipeline on startup:
//! 1. Parse CLI flags.
//! 2. Start cpal capture + playback (each on its own OS thread).
//! 3. Spawn the framer thread that slices raw samples into 20 ms frames
//!    and runs them through the VAD.
//! 4. Serve a WebSocket endpoint that fans frames + VAD events out to the
//!    Python backend and accepts playback audio in return.

use std::net::{IpAddr, SocketAddr};
use std::sync::Arc;

use anyhow::{Context, Result};
use clap::Parser;
use cpal::traits::{DeviceTrait, HostTrait};
use tokio::sync::broadcast;
use tracing::{info, warn};

mod capture;
mod cli;
mod playback;
mod protocol;
mod resample;
mod vad;
mod ws;

use crate::capture::CapturedFrame;
use crate::cli::{Cli, Command};
use crate::protocol::ServerMessage;
use crate::vad::{Vad, VadConfig};
use crate::ws::{CaptureEvent, ServerOptions};

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let cli = Cli::parse();

    if matches!(cli.command, Some(Command::ListDevices)) {
        return list_devices();
    }

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("failed to build tokio runtime")?;
    runtime.block_on(async move { run(cli).await })
}

async fn run(cli: Cli) -> Result<()> {
    let frame_samples = (cli.sample_rate as u64 * cli.frame_ms as u64 / 1_000) as usize;
    let (cap_tx, _) = broadcast::channel::<CaptureEvent>(256);

    // ---- Capture + framer ---------------------------------------------------
    let _capture_handle = if cli.no_capture {
        info!("capture disabled by --no-capture");
        None
    } else {
        let (raw_tx, raw_rx) = capture::make_capture_channel(cli.sample_rate);
        let handle = capture::start_capture(cli.input_device.as_deref(), cli.sample_rate, raw_tx)?;

        let vad_cfg = VadConfig {
            threshold: cli.vad_threshold,
            ..VadConfig::default()
        };
        let mut vad = Vad::new(vad_cfg);
        let cap_tx_frames = cap_tx.clone();

        capture::spawn_framer(raw_rx, frame_samples, cli.sample_rate, move |frame: CapturedFrame| {
            // VAD first so the `speech_start` event is delivered before any
            // silence-gated listener sees the first frame of the utterance.
            if let Some(event) = vad.push_frame(&frame.pcm) {
                let msg = ServerMessage::Vad { state: event, ts_ms: frame.ts_ms };
                let _ = cap_tx_frames.send(CaptureEvent::Vad(msg));
            }
            let _ = cap_tx_frames.send(CaptureEvent::Frame(Arc::new(frame.pcm)));
        });

        Some(handle)
    };

    // ---- Playback -----------------------------------------------------------
    let playback = if cli.no_playback {
        info!("playback disabled by --no-playback");
        None
    } else {
        match playback::start_playback(cli.output_device.as_deref(), cli.sample_rate) {
            Ok(pb) => Some(Arc::new(pb)),
            Err(e) => {
                warn!(?e, "playback unavailable; continuing without speaker");
                None
            }
        }
    };

    // ---- WebSocket server ---------------------------------------------------
    let host_ip: IpAddr = cli.host.parse().with_context(|| format!("invalid --host {}", cli.host))?;
    let addr = SocketAddr::new(host_ip, cli.port);
    ws::run_server(
        ServerOptions {
            addr,
            sample_rate: cli.sample_rate,
            frame_ms: cli.frame_ms,
            capture_enabled: !cli.no_capture,
            playback_enabled: !cli.no_playback && playback.is_some(),
        },
        cap_tx,
        playback,
    )
    .await
}

fn list_devices() -> Result<()> {
    let host = cpal::default_host();
    println!("host: {}", host.id().name());

    println!("\n== input devices ==");
    for d in host.input_devices()? {
        let name = d.name().unwrap_or_else(|_| "<error>".into());
        let def = match d.default_input_config() {
            Ok(c) => format!("{:?} {} Hz, {} ch", c.sample_format(), c.sample_rate().0, c.channels()),
            Err(e) => format!("(no default config: {e})"),
        };
        println!("  - {name}: {def}");
    }

    println!("\n== output devices ==");
    for d in host.output_devices()? {
        let name = d.name().unwrap_or_else(|_| "<error>".into());
        let def = match d.default_output_config() {
            Ok(c) => format!("{:?} {} Hz, {} ch", c.sample_format(), c.sample_rate().0, c.channels()),
            Err(e) => format!("(no default config: {e})"),
        };
        println!("  - {name}: {def}");
    }
    Ok(())
}
