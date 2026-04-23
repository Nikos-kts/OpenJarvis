//! JSON control protocol spoken over WebSocket text frames.
//!
//! Binary frames carry raw PCM16 little-endian samples at the daemon's
//! canonical sample rate (default 16 kHz, mono). Text frames carry the
//! structured messages defined here.
//!
//! Direction:
//! - Server → Client: `Ready`, `Vad`, `Error` (plus binary mic frames).
//! - Client → Server: `Control` (plus binary playback frames).

use serde::{Deserialize, Serialize};

use crate::vad::VadEvent;

/// One-shot announcement the server sends immediately after accepting a
/// connection, so clients don't need to know the capture format a priori.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReadyMessage {
    pub sample_rate: u32,
    pub channels: u16,
    /// Always `"pcm_s16le"` today; present on the wire so the client can
    /// refuse an unexpected format without parsing audio.
    pub format: String,
    pub frame_ms: u32,
    pub capture_enabled: bool,
    pub playback_enabled: bool,
}

/// Tagged union of server-originated text messages.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    Ready(ReadyMessage),
    Vad { state: VadEvent, ts_ms: u64 },
    Error { message: String },
    Pong,
}

/// Tagged union of client-originated text messages. Binary frames (playback
/// audio) are handled outside this enum.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    /// Temporarily suppress capture frames without tearing down the stream.
    MuteInput { value: bool },
    /// Drop any pending playback samples queued for the speaker.
    StopOutput,
    /// Keepalive round-trip; the server responds with `Pong`.
    Ping,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ready_round_trip() {
        let m = ServerMessage::Ready(ReadyMessage {
            sample_rate: 16_000,
            channels: 1,
            format: "pcm_s16le".to_string(),
            frame_ms: 20,
            capture_enabled: true,
            playback_enabled: true,
        });
        let s = serde_json::to_string(&m).unwrap();
        let back: ServerMessage = serde_json::from_str(&s).unwrap();
        assert_eq!(m, back);
        assert!(s.contains("\"type\":\"ready\""));
    }

    #[test]
    fn vad_event_serializes_snake_case() {
        let m = ServerMessage::Vad {
            state: VadEvent::SpeechStart,
            ts_ms: 42,
        };
        let s = serde_json::to_string(&m).unwrap();
        assert!(s.contains("\"state\":\"speech_start\""), "{s}");
    }

    #[test]
    fn client_control_round_trip() {
        let cases = [
            ClientMessage::MuteInput { value: true },
            ClientMessage::StopOutput,
            ClientMessage::Ping,
        ];
        for c in cases {
            let s = serde_json::to_string(&c).unwrap();
            let back: ClientMessage = serde_json::from_str(&s).unwrap();
            assert_eq!(c, back);
        }
    }
}
