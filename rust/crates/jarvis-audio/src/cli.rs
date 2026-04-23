//! CLI definition for the `jarvis-audio` binary.

use clap::{Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(
    name = "jarvis-audio",
    version,
    about = "OpenJarvis audio daemon: mic + VAD + speaker over WebSocket"
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Option<Command>,

    /// Interface to bind the WebSocket server to.
    #[arg(long, default_value = "127.0.0.1", global = true)]
    pub host: String,

    /// TCP port for the WebSocket server.
    #[arg(long, default_value_t = 8765, global = true)]
    pub port: u16,

    /// Canonical output sample rate, in Hz. PCM16 mono.
    #[arg(long, default_value_t = 16_000, global = true)]
    pub sample_rate: u32,

    /// Emitted audio frame length, in milliseconds. 20 ms @ 16 kHz = 320 samples.
    #[arg(long, default_value_t = 20, global = true)]
    pub frame_ms: u32,

    /// VAD sensitivity knob in [0.0, 1.0]. Higher = needs louder audio.
    #[arg(long, default_value_t = 0.5, global = true)]
    pub vad_threshold: f32,

    /// Input (microphone) device name. Uses the system default if omitted.
    #[arg(long, global = true)]
    pub input_device: Option<String>,

    /// Output (speaker) device name. Uses the system default if omitted.
    #[arg(long, global = true)]
    pub output_device: Option<String>,

    /// Disable microphone capture (server → client audio).
    #[arg(long, global = true)]
    pub no_capture: bool,

    /// Disable speaker playback (client → server audio).
    #[arg(long, global = true)]
    pub no_playback: bool,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Enumerate audio devices visible via `cpal` and exit.
    ListDevices,
}
