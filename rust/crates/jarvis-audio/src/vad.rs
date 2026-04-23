//! Energy-based Voice Activity Detection.
//!
//! Operates on 16 kHz mono PCM16 samples fed in 20 ms frames (320 samples).
//! Emits `SpeechStart` / `SpeechEnd` transitions with hangover smoothing so
//! short inter-word silences don't close the segment prematurely.
//!
//! This implementation is deliberately dependency-free. For higher-quality
//! speech/non-speech classification, swap this module for a Silero-VAD ONNX
//! runner — the public API (`Vad::push_frame`) is the only contract callers
//! depend on.

use serde::{Deserialize, Serialize};

/// One emitted transition from the VAD state machine.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VadEvent {
    SpeechStart,
    SpeechEnd,
}

/// Detector configuration.
#[derive(Debug, Clone, Copy)]
pub struct VadConfig {
    /// Sensitivity knob in [0.0, 1.0]. Higher = less sensitive (needs louder
    /// audio to trigger). Mapped to an absolute RMS threshold in PCM16 units.
    pub threshold: f32,
    /// Consecutive speech frames required before emitting `SpeechStart`.
    pub speech_frames: u32,
    /// Consecutive silence frames required before emitting `SpeechEnd`
    /// (i.e. hangover length, in 20 ms frames).
    pub silence_frames: u32,
}

impl Default for VadConfig {
    fn default() -> Self {
        Self {
            threshold: 0.5,
            speech_frames: 3,   // 60 ms
            silence_frames: 20, // 400 ms
        }
    }
}

/// Voice Activity Detector. One instance per capture stream.
pub struct Vad {
    cfg: VadConfig,
    rms_threshold: f32,
    in_speech: bool,
    speech_run: u32,
    silence_run: u32,
}

impl Vad {
    pub fn new(cfg: VadConfig) -> Self {
        Self {
            rms_threshold: map_threshold(cfg.threshold),
            cfg,
            in_speech: false,
            speech_run: 0,
            silence_run: 0,
        }
    }

    /// Feed one frame of PCM16 samples and get back a state transition, if
    /// any. Frame size is not enforced, but 20 ms (320 samples @ 16 kHz) is
    /// expected for the hangover constants in `VadConfig::default` to match
    /// their documented millisecond values.
    pub fn push_frame(&mut self, samples: &[i16]) -> Option<VadEvent> {
        let rms = rms_i16(samples);
        let is_speech = rms >= self.rms_threshold;

        if is_speech {
            self.silence_run = 0;
            self.speech_run = self.speech_run.saturating_add(1);
            if !self.in_speech && self.speech_run >= self.cfg.speech_frames {
                self.in_speech = true;
                return Some(VadEvent::SpeechStart);
            }
        } else {
            self.speech_run = 0;
            self.silence_run = self.silence_run.saturating_add(1);
            if self.in_speech && self.silence_run >= self.cfg.silence_frames {
                self.in_speech = false;
                return Some(VadEvent::SpeechEnd);
            }
        }
        None
    }

    #[allow(dead_code)] // consumed by tests and future wake-word integration
    pub fn is_in_speech(&self) -> bool {
        self.in_speech
    }
}

/// Map a user-facing [0,1] sensitivity knob to an absolute PCM16 RMS cutoff.
/// `threshold = 0.0` → very sensitive (~80 units RMS, roughly a quiet room
/// plus faint speech). `threshold = 1.0` → requires loud speech (~5000 RMS).
/// Curve is exponential so the low end is fine-grained.
fn map_threshold(t: f32) -> f32 {
    let t = t.clamp(0.0, 1.0);
    // 80 * (5000/80)^t = 80 * 62.5^t
    80.0_f32 * 62.5_f32.powf(t)
}

fn rms_i16(samples: &[i16]) -> f32 {
    if samples.is_empty() {
        return 0.0;
    }
    let mut sum_sq: f64 = 0.0;
    for &s in samples {
        let x = s as f64;
        sum_sq += x * x;
    }
    ((sum_sq / samples.len() as f64).sqrt()) as f32
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f32::consts::PI;

    fn tone_frame(freq_hz: f32, amplitude: i16, sample_rate: u32, n: usize) -> Vec<i16> {
        (0..n)
            .map(|i| {
                let t = i as f32 / sample_rate as f32;
                (amplitude as f32 * (2.0 * PI * freq_hz * t).sin()) as i16
            })
            .collect()
    }

    fn silence_frame(n: usize) -> Vec<i16> {
        vec![0_i16; n]
    }

    #[test]
    fn emits_speech_start_then_end_for_silence_tone_silence() {
        let mut vad = Vad::new(VadConfig {
            threshold: 0.3,
            speech_frames: 2,
            silence_frames: 3,
        });
        let sr = 16_000;
        let frame = 320; // 20 ms

        // Prelude: silence — no events.
        for _ in 0..5 {
            assert!(vad.push_frame(&silence_frame(frame)).is_none());
        }

        // Loud 440 Hz tone: within a few frames we should see SpeechStart.
        let mut events = Vec::new();
        for _ in 0..10 {
            if let Some(e) = vad.push_frame(&tone_frame(440.0, 8000, sr, frame)) {
                events.push(e);
            }
        }
        assert!(
            events.contains(&VadEvent::SpeechStart),
            "expected SpeechStart during tone, got {events:?}"
        );

        // Trailing silence: after hangover we should see SpeechEnd.
        let mut events = Vec::new();
        for _ in 0..10 {
            if let Some(e) = vad.push_frame(&silence_frame(frame)) {
                events.push(e);
            }
        }
        assert!(
            events.contains(&VadEvent::SpeechEnd),
            "expected SpeechEnd after silence, got {events:?}"
        );
        assert!(!vad.is_in_speech());
    }

    #[test]
    fn quiet_tone_below_threshold_does_not_trigger() {
        let mut vad = Vad::new(VadConfig {
            threshold: 0.9, // very high: needs loud audio
            speech_frames: 2,
            silence_frames: 3,
        });
        for _ in 0..20 {
            assert!(vad.push_frame(&tone_frame(440.0, 200, 16_000, 320)).is_none());
        }
        assert!(!vad.is_in_speech());
    }

    #[test]
    fn threshold_mapping_monotonic() {
        assert!(map_threshold(0.0) < map_threshold(0.5));
        assert!(map_threshold(0.5) < map_threshold(1.0));
    }

    #[test]
    fn rms_of_silence_is_zero() {
        assert_eq!(rms_i16(&[0, 0, 0, 0]), 0.0);
    }
}
