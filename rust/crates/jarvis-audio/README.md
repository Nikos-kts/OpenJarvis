# jarvis-audio

Standalone audio daemon for OpenJarvis. Captures from the system microphone,
emits 16 kHz mono PCM16 frames with inline VAD events, and plays audio queued
by a backend client — all over a single WebSocket connection.

The daemon is the canonical audio boundary for OpenJarvis: the Python
backend is the single source of truth, and the browser / Tauri frontend does
**not** touch the microphone directly.

## Build & run

```bash
# From repo root:
cargo build -p jarvis-audio --release

# Start the daemon on 127.0.0.1:8765 with default devices
./rust/target/release/jarvis-audio

# Enumerate devices visible to cpal
./rust/target/release/jarvis-audio list-devices

# Pick a specific input / output device
./rust/target/release/jarvis-audio \
    --input-device "USB Microphone" \
    --output-device "External Headphones"
```

### Ubuntu / Debian prerequisites

`cpal` links against ALSA, so Linux builds need:

```bash
sudo apt-get install -y libasound2-dev
```

## CLI flags

| Flag | Default | Description |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Interface to bind the WebSocket server to |
| `--port` | `8765` | TCP port |
| `--sample-rate` | `16000` | Canonical output sample rate (Hz) |
| `--frame-ms` | `20` | Emitted frame length (milliseconds) |
| `--vad-threshold` | `0.5` | Sensitivity in `[0.0, 1.0]`; higher = less sensitive |
| `--input-device` | *(system default)* | cpal input device name |
| `--output-device` | *(system default)* | cpal output device name |
| `--no-capture` | `false` | Disable microphone capture path |
| `--no-playback` | `false` | Disable speaker playback path |

## Protocol

One WebSocket endpoint at `ws://<host>:<port>/`.

### Handshake

On connect, the server sends a single text frame:

```json
{
  "type": "ready",
  "sample_rate": 16000,
  "channels": 1,
  "format": "pcm_s16le",
  "frame_ms": 20,
  "capture_enabled": true,
  "playback_enabled": true
}
```

### Server → client

- **Binary frames**: raw PCM16 little-endian mono samples at `sample_rate`,
  in fixed-size chunks of `frame_ms` (e.g. 20 ms = 320 samples = 640 bytes).
- **Text frames** (JSON, tagged by `type`):
  - `{"type":"vad","state":"speech_start","ts_ms":12345}`
  - `{"type":"vad","state":"speech_end","ts_ms":12678}`
  - `{"type":"error","message":"..."}`
  - `{"type":"pong"}` in response to a client `ping`.

### Client → server

- **Binary frames**: PCM16 LE mono at `sample_rate`; any size. Enqueued
  directly for speaker playback (resampled to the output device's native
  rate; stereo devices duplicate across channels).
- **Text frames** (JSON, tagged by `type`):
  - `{"type":"mute_input","value":true}` — pause mic frame forwarding
    without tearing down the cpal stream.
  - `{"type":"stop_output"}` — drop any queued playback samples.
  - `{"type":"ping"}` — keepalive; server replies with `pong`.

## Latency

End-to-end capture-to-frame target is **< 50 ms**:

- cpal default buffer (device-dependent): typically 10–30 ms on Linux/ALSA.
- Framer pacing: one frame every `frame_ms` (20 ms default).
- Linear resampler: O(n), negligible.

The VAD runs inline on the framer thread before the frame is broadcast, so
`speech_start` events land no later than the frame that triggered them.

## Swap points

- **VAD** — `vad.rs` implements an energy-based detector. For higher quality
  replace `Vad::push_frame` with a Silero-VAD ONNX runner; the public API is
  stable.
- **Resampler** — `resample.rs` is linear interpolation (fine for speech in
  the 300–3400 Hz band). Swap for `rubato` if music-grade playback is ever
  required.
- **Wake-word** — not implemented. Add a module that taps the broadcast
  channel's `CaptureEvent::Frame` stream.

## Unit tests

```bash
cargo test -p jarvis-audio
```

Tests exercise pure-Rust modules only (VAD, resampler, protocol codec,
PCM16 byte framing). No audio hardware is touched.
