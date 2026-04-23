//! WebSocket server that fronts the capture + playback pipelines.
//!
//! Each accepted connection:
//! - receives a `Ready` text frame describing the audio format,
//! - receives binary frames = server → client mic PCM16,
//! - receives text frames = server → client `VadEvent` / `Error`,
//! - may send binary frames = client → server playback PCM16,
//! - may send text frames = client → server `ClientMessage` control.
//!
//! The daemon supports a single concurrent client at a time (the OpenJarvis
//! backend). Additional connections are accepted but will race on the mic
//! broadcast channel; that's deliberate — the daemon is not meant to be a
//! multi-tenant audio server.

use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::{Context, Result};
use futures::{SinkExt, StreamExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::broadcast;
use tokio_tungstenite::tungstenite::Message;
use tracing::{debug, info, warn};

use crate::playback::PlaybackHandle;
use crate::protocol::{ClientMessage, ReadyMessage, ServerMessage};

/// Event type broadcast from the capture pipeline to every connected client.
#[derive(Debug, Clone)]
pub enum CaptureEvent {
    /// Raw PCM16 mono frame at the canonical sample rate.
    Frame(Arc<Vec<i16>>),
    /// Tagged VAD transition.
    Vad(ServerMessage),
}

pub struct ServerOptions {
    pub addr: SocketAddr,
    pub sample_rate: u32,
    pub frame_ms: u32,
    pub capture_enabled: bool,
    pub playback_enabled: bool,
}

pub async fn run_server(
    opts: ServerOptions,
    capture_rx: broadcast::Sender<CaptureEvent>,
    playback: Option<Arc<PlaybackHandle>>,
) -> Result<()> {
    let listener = TcpListener::bind(opts.addr)
        .await
        .with_context(|| format!("failed to bind {}", opts.addr))?;
    info!(addr = %opts.addr, "jarvis-audio listening");

    let opts = Arc::new(opts);

    loop {
        let (stream, peer) = match listener.accept().await {
            Ok(v) => v,
            Err(e) => {
                warn!(?e, "accept failed");
                continue;
            }
        };
        let opts = Arc::clone(&opts);
        let rx = capture_rx.subscribe();
        let playback = playback.clone();
        tokio::spawn(async move {
            if let Err(e) = handle_connection(stream, peer, opts, rx, playback).await {
                warn!(?peer, ?e, "client session ended with error");
            } else {
                debug!(?peer, "client session ended cleanly");
            }
        });
    }
}

async fn handle_connection(
    stream: TcpStream,
    peer: SocketAddr,
    opts: Arc<ServerOptions>,
    mut capture_rx: broadcast::Receiver<CaptureEvent>,
    playback: Option<Arc<PlaybackHandle>>,
) -> Result<()> {
    let ws = tokio_tungstenite::accept_async(stream)
        .await
        .context("websocket handshake failed")?;
    info!(?peer, "client connected");
    let (mut sink, mut source) = ws.split();

    // Initial handshake: announce capture format.
    let ready = ServerMessage::Ready(ReadyMessage {
        sample_rate: opts.sample_rate,
        channels: 1,
        format: "pcm_s16le".to_string(),
        frame_ms: opts.frame_ms,
        capture_enabled: opts.capture_enabled,
        playback_enabled: opts.playback_enabled,
    });
    sink.send(Message::Text(serde_json::to_string(&ready)?)).await?;

    let mut muted = false;

    loop {
        tokio::select! {
            biased;

            // Drain the capture broadcast channel toward the client.
            event = capture_rx.recv() => {
                match event {
                    Ok(CaptureEvent::Frame(pcm)) if !muted => {
                        let bytes = pcm16_to_bytes(&pcm);
                        sink.send(Message::Binary(bytes)).await?;
                    }
                    Ok(CaptureEvent::Vad(msg)) => {
                        sink.send(Message::Text(serde_json::to_string(&msg)?)).await?;
                    }
                    Ok(_) => {}
                    Err(broadcast::error::RecvError::Lagged(n)) => {
                        warn!(?peer, dropped = n, "client lagged; dropped capture events");
                    }
                    Err(broadcast::error::RecvError::Closed) => break,
                }
            }

            // Handle client-originated frames.
            msg = source.next() => {
                let Some(msg) = msg else { break };
                match msg? {
                    Message::Binary(data) => {
                        if let Some(pb) = &playback {
                            let samples = bytes_to_pcm16(&data);
                            pb.push(&samples);
                        }
                    }
                    Message::Text(txt) => {
                        match serde_json::from_str::<ClientMessage>(&txt) {
                            Ok(ClientMessage::MuteInput { value }) => {
                                muted = value;
                                debug!(?peer, muted, "mute state updated");
                            }
                            Ok(ClientMessage::StopOutput) => {
                                if let Some(pb) = &playback {
                                    pb.clear();
                                }
                            }
                            Ok(ClientMessage::Ping) => {
                                let pong = ServerMessage::Pong;
                                sink.send(Message::Text(serde_json::to_string(&pong)?)).await?;
                            }
                            Err(e) => {
                                let err = ServerMessage::Error { message: format!("bad control message: {e}") };
                                sink.send(Message::Text(serde_json::to_string(&err)?)).await?;
                            }
                        }
                    }
                    Message::Ping(p) => sink.send(Message::Pong(p)).await?,
                    Message::Close(_) => break,
                    Message::Pong(_) | Message::Frame(_) => {}
                }
            }
        }
    }
    Ok(())
}

fn pcm16_to_bytes(samples: &[i16]) -> Vec<u8> {
    let mut out = Vec::with_capacity(samples.len() * 2);
    for &s in samples {
        out.extend_from_slice(&s.to_le_bytes());
    }
    out
}

fn bytes_to_pcm16(data: &[u8]) -> Vec<i16> {
    let usable = data.len() - (data.len() % 2);
    let mut out = Vec::with_capacity(usable / 2);
    for chunk in data[..usable].chunks_exact(2) {
        out.push(i16::from_le_bytes([chunk[0], chunk[1]]));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pcm_byte_round_trip() {
        let samples: Vec<i16> = vec![0, 1, -1, i16::MAX, i16::MIN, 12345, -12345];
        let bytes = pcm16_to_bytes(&samples);
        assert_eq!(bytes.len(), samples.len() * 2);
        let back = bytes_to_pcm16(&bytes);
        assert_eq!(samples, back);
    }

    #[test]
    fn bytes_to_pcm_ignores_trailing_odd_byte() {
        // A malformed 5-byte payload: we should parse 2 samples and drop the trailing byte.
        let samples = bytes_to_pcm16(&[0x00, 0x01, 0x02, 0x03, 0xff]);
        assert_eq!(samples.len(), 2);
    }
}
