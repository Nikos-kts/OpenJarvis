//! Linear-interpolation resampler for converting between the capture device's
//! native sample rate and the daemon's canonical 16 kHz output.
//!
//! Linear interpolation is adequate for speech in the 300–3400 Hz band. For
//! higher-fidelity resampling (e.g. music), swap in `rubato`. The public
//! `Resampler::process` contract is the only thing callers depend on.

/// Streaming linear resampler. Maintains a single-sample history across
/// `process` calls so chunk boundaries don't introduce discontinuities.
pub struct Resampler {
    in_rate: u32,
    out_rate: u32,
    /// Position in the *input* stream, in samples, as a fractional index.
    /// We consume `input` sequentially, advancing this by the rate ratio
    /// for each output sample we emit.
    pos: f64,
    /// Last input sample seen; used for interpolation when the next output
    /// point's integer floor equals the previous chunk's tail.
    last: f32,
    initialised: bool,
}

impl Resampler {
    pub fn new(in_rate: u32, out_rate: u32) -> Self {
        assert!(in_rate > 0 && out_rate > 0, "rates must be > 0");
        Self {
            in_rate,
            out_rate,
            pos: 0.0,
            last: 0.0,
            initialised: false,
        }
    }

    /// No-op resampling when rates match, used as a fast path by callers.
    pub fn is_identity(&self) -> bool {
        self.in_rate == self.out_rate
    }

    /// Resample one chunk of PCM16 samples. Appends output samples to `out`.
    pub fn process(&mut self, input: &[i16], out: &mut Vec<i16>) {
        if input.is_empty() {
            return;
        }
        if self.is_identity() {
            out.extend_from_slice(input);
            return;
        }
        let ratio = self.in_rate as f64 / self.out_rate as f64;

        // On the very first call, seed `last` with the first sample so the
        // first interpolated point (at pos=0) equals input[0] exactly.
        if !self.initialised {
            self.last = input[0] as f32;
            self.initialised = true;
        }

        // Local position relative to the start of `input`. We persist `pos`
        // across calls as a running offset into the logical input stream so
        // we only use its fractional part within this chunk.
        let mut local = self.pos;
        let input_len = input.len() as f64;

        while local < input_len {
            let idx_floor = local.floor() as i64;
            let frac = (local - local.floor()) as f32;

            // Fetch the two samples we need to interpolate between. The
            // "left" sample may be the tail of the previous chunk (`last`).
            let left = if idx_floor <= 0 {
                self.last
            } else {
                input[(idx_floor - 1) as usize] as f32
            };
            let right_idx = idx_floor.max(0) as usize;
            if right_idx >= input.len() {
                break;
            }
            let right = input[right_idx] as f32;

            let sample = left + (right - left) * frac;
            out.push(sample.round().clamp(i16::MIN as f32, i16::MAX as f32) as i16);
            local += ratio;
        }

        // Remember the last input sample for cross-chunk continuity, then
        // fold the leftover fractional offset back into `self.pos`.
        self.last = *input.last().unwrap() as f32;
        self.pos = local - input_len;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identity_passthrough() {
        let mut r = Resampler::new(16_000, 16_000);
        assert!(r.is_identity());
        let mut out = Vec::new();
        r.process(&[1, 2, 3, 4, 5], &mut out);
        assert_eq!(out, vec![1, 2, 3, 4, 5]);
    }

    #[test]
    fn downsample_48k_to_16k_preserves_length_ratio() {
        let mut r = Resampler::new(48_000, 16_000);
        let input: Vec<i16> = (0..480).map(|i| (i % 100) as i16).collect();
        let mut out = Vec::new();
        r.process(&input, &mut out);
        // 480 input samples @ 3:1 → roughly 160 output samples.
        assert!(
            (out.len() as i64 - 160).abs() <= 1,
            "expected ~160 samples, got {}",
            out.len()
        );
    }

    #[test]
    fn upsample_8k_to_16k_preserves_length_ratio() {
        let mut r = Resampler::new(8_000, 16_000);
        let input: Vec<i16> = (0..80).map(|i| (i * 100) as i16).collect();
        let mut out = Vec::new();
        r.process(&input, &mut out);
        assert!(
            (out.len() as i64 - 160).abs() <= 1,
            "expected ~160 samples, got {}",
            out.len()
        );
    }

    #[test]
    fn chunked_resample_matches_single_call_length() {
        let input: Vec<i16> = (0..960).map(|i| ((i % 200) as i16 - 100) * 50).collect();

        let mut single = Vec::new();
        Resampler::new(48_000, 16_000).process(&input, &mut single);

        let mut chunked = Vec::new();
        let mut r = Resampler::new(48_000, 16_000);
        for slice in input.chunks(137) {
            r.process(slice, &mut chunked);
        }
        // Allow ±1 sample drift from rounding at chunk boundaries.
        assert!(
            (single.len() as i64 - chunked.len() as i64).abs() <= 1,
            "single={} chunked={}",
            single.len(),
            chunked.len()
        );
    }
}
