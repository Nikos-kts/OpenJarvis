import threading
import time

from openjarvis.speech.clap_detector import ClapConfig, ClapDetector


def _make_detector(config: ClapConfig) -> ClapDetector:
    detector = object.__new__(ClapDetector)
    detector._cfg = config
    detector._stop_event = threading.Event()
    detector._thread = None
    detector._last_clap_time = 0.0
    detector._sequence_started_at = 0.0
    detector._sequence_count = 0
    detector._last_trigger_time = -999.0
    detector._pending_double_timer = None
    detector._lock = threading.Lock()
    return detector


def test_double_clap_fires_after_triple_window_passes() -> None:
    events: list[str] = []
    detector = _make_detector(
        ClapConfig(
            min_gap=0.01,
            max_gap=0.03,
            cooldown=0.05,
            on_double_clap=lambda: events.append("double"),
        )
    )

    detector._register_clap(1.0)
    detector._register_clap(1.02)
    time.sleep(0.06)

    assert events == ["double"]
    detector.stop()


def test_triple_clap_cancels_pending_double() -> None:
    events: list[str] = []
    detector = _make_detector(
        ClapConfig(
            min_gap=0.01,
            max_gap=0.03,
            cooldown=0.05,
            on_double_clap=lambda: events.append("double"),
            on_triple_clap=lambda: events.append("triple"),
        )
    )

    detector._register_clap(1.0)
    detector._register_clap(1.02)
    detector._register_clap(1.04)
    time.sleep(0.06)

    assert events == ["triple"]
    detector.stop()