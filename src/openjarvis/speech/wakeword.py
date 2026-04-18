"""Wake word detection using openwakeword.

Provides a WakeWordDetector that wraps the openwakeword library,
processing raw 16-bit 16 kHz PCM audio frames and returning detection
scores for "hey jarvis".
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_oww: Any = None
_AVAILABLE = False

try:
    import openwakeword  # noqa: F401
    from openwakeword.model import Model as OWWModel

    _AVAILABLE = True
except ImportError:
    OWWModel = None  # type: ignore[assignment,misc]


class WakeWordDetector:
    """Thin wrapper around openwakeword's Model class.

    Usage::

        detector = WakeWordDetector()
        # feed 16-bit 16 kHz mono PCM chunks (bytes or int16 ndarray)
        scores = detector.process_audio(pcm_chunk)
        if scores.get("hey_jarvis", 0) > detector.threshold:
            print("Wake word detected!")
    """

    def __init__(self, threshold: float = 0.5) -> None:
        if not _AVAILABLE:
            raise RuntimeError(
                "openwakeword is not installed. "
                "Install it with: pip install 'openjarvis[speech-wakeword]'"
            )
        self.threshold = threshold
        # Ensure models are downloaded
        try:
            self._model = OWWModel(
                wakeword_models=["hey_jarvis"],
                inference_framework="onnx",
            )
        except Exception:
            # Model files may not be downloaded yet
            logger.info("Downloading openwakeword models...")
            from openwakeword.utils import download_models
            download_models()
            self._model = OWWModel(
                wakeword_models=["hey_jarvis"],
                inference_framework="onnx",
            )
        logger.info("openwakeword loaded with model: hey_jarvis (threshold=%.2f)", threshold)

    def process_audio(self, pcm_data: bytes | Any) -> dict[str, float]:
        """Feed a chunk of 16-bit 16 kHz mono PCM audio.

        Args:
            pcm_data: Raw PCM bytes or a numpy int16 array.
                      Recommended chunk size: 1280 samples (80 ms at 16 kHz).

        Returns:
            Dict mapping model name to detection score (0.0–1.0).
        """
        import numpy as np

        if isinstance(pcm_data, (bytes, bytearray)):
            audio = np.frombuffer(pcm_data, dtype=np.int16)
        else:
            audio = pcm_data

        prediction = self._model.predict(audio)
        return dict(prediction)

    def detected(self, pcm_data: bytes | Any) -> bool:
        """Convenience: returns True if wake word score exceeds threshold."""
        scores = self.process_audio(pcm_data)
        return any(v >= self.threshold for v in scores.values())

    def reset(self) -> None:
        """Reset internal detection state (call between utterances)."""
        self._model.reset()

    @staticmethod
    def available() -> bool:
        return _AVAILABLE
