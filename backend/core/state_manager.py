"""
state_manager.py
----------------
Thread-safe state container for the Gridlock detection pipeline.

Design goals
~~~~~~~~~~~~
* Zero uncontrolled globals – all mutable state lives inside ``StateManager``.
* All public mutators acquire an ``RLock`` so they are safe to call from
  multiple threads (producer, consumer, OCR worker, etc.).
* Serialisation (to JSON-compatible dicts) is built in via ``to_dict()``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data-classes for individual records
# ---------------------------------------------------------------------------

@dataclass
class BoundingBox:
    """Pixel-space bounding box."""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class DetectionRecord:
    """Single detection within a frame, including optional tracking data."""

    class_id: int
    class_name: str
    confidence: float
    bbox: BoundingBox
    track_id: Optional[int] = None
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None


@dataclass
class ViolationEvent:
    """Describes a confirmed traffic violation."""

    violation_type: str
    """Human-readable type string, e.g. 'WithoutHelmet', 'TripleRiding', 'IllegalParking'."""

    frame_id: int
    timestamp: str
    track_id: Optional[int]
    plate_text: Optional[str]
    bbox: BoundingBox
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FrameState:
    """Snapshot of all detections and violations for a single processed frame."""

    frame_id: int
    timestamp: str
    detections: List[DetectionRecord] = field(default_factory=list)
    violations: List[ViolationEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------

class StateManager:
    """
    Thread-safe repository for pipeline state.

    Usage
    -----
    >>> sm = StateManager()
    >>> sm.begin_frame(42)
    >>> sm.add_detection(DetectionRecord(...))
    >>> sm.add_violation(ViolationEvent(...))
    >>> snapshot = sm.current_frame()
    >>> json_dict = sm.to_dict()
    """

    def __init__(self, history_limit: int = 500) -> None:
        """
        Parameters
        ----------
        history_limit:
            Maximum number of ``FrameState`` objects retained in memory.
            Older entries are discarded (FIFO).
        """
        self._lock: threading.RLock = threading.RLock()
        self._current: FrameState = FrameState(frame_id=0, timestamp=_now())
        self._history: List[FrameState] = []
        self._history_limit: int = history_limit

        # Parking dwell counter: track_id → consecutive-frame count
        self._parking_dwell: Dict[int, int] = {}

        # OCR cache: track_id → (plate_text, plate_confidence)
        self._ocr_cache: Dict[int, tuple[str, float]] = {}

        logger.debug("StateManager initialised (history_limit=%d)", history_limit)

    # ------------------------------------------------------------------
    # Frame lifecycle
    # ------------------------------------------------------------------

    def begin_frame(self, frame_id: int) -> None:
        """
        Start a new frame.  Flushes the previous frame to history and
        resets the mutable current-frame buffer.

        Parameters
        ----------
        frame_id:
            Monotonically increasing identifier for the frame (not the
            raw VideoCapture frame index – this is the *processed* frame
            counter).
        """
        with self._lock:
            if self._current.detections or self._current.violations:
                self._history.append(self._current)
                if len(self._history) > self._history_limit:
                    self._history.pop(0)

            self._current = FrameState(
                frame_id=frame_id,
                timestamp=_now(),
            )
            logger.debug("Frame %d begun", frame_id)

    def add_detection(self, record: DetectionRecord) -> None:
        """Append a detection to the current frame (thread-safe)."""
        with self._lock:
            self._current.detections.append(record)

    def add_violation(self, event: ViolationEvent) -> None:
        """Append a violation event to the current frame (thread-safe)."""
        with self._lock:
            self._current.violations.append(event)
            logger.info(
                "Violation [%s] | track_id=%s | plate=%s | frame=%d",
                event.violation_type,
                event.track_id,
                event.plate_text,
                event.frame_id,
            )

    # ------------------------------------------------------------------
    # Parking dwell tracking
    # ------------------------------------------------------------------

    def increment_parking_dwell(self, track_id: int) -> int:
        """
        Increment and return the parking dwell counter for *track_id*.

        The dwell counter represents how many consecutive processed frames
        the tracked object has been inside the parking ROI.
        """
        with self._lock:
            self._parking_dwell[track_id] = self._parking_dwell.get(track_id, 0) + 1
            return self._parking_dwell[track_id]

    def reset_parking_dwell(self, track_id: int) -> None:
        """Reset the dwell counter when a track leaves the ROI."""
        with self._lock:
            self._parking_dwell.pop(track_id, None)

    def get_parking_dwell(self, track_id: int) -> int:
        """Return current dwell count for *track_id* (0 if unknown)."""
        with self._lock:
            return self._parking_dwell.get(track_id, 0)

    # ------------------------------------------------------------------
    # OCR cache
    # ------------------------------------------------------------------

    def cache_ocr(self, track_id: int, plate_text: str, confidence: float) -> None:
        """Store an OCR result keyed by *track_id*."""
        with self._lock:
            self._ocr_cache[track_id] = (plate_text, confidence)
            logger.debug("OCR cached | track_id=%d | plate=%s", track_id, plate_text)

    def get_cached_ocr(self, track_id: int) -> Optional[tuple[str, float]]:
        """Return cached ``(plate_text, confidence)`` or ``None``."""
        with self._lock:
            return self._ocr_cache.get(track_id)

    def has_cached_ocr(self, track_id: int) -> bool:
        """Return ``True`` if a cached OCR result exists for *track_id*."""
        with self._lock:
            return track_id in self._ocr_cache

    # ------------------------------------------------------------------
    # Read-only access
    # ------------------------------------------------------------------

    def current_frame(self) -> FrameState:
        """Return a **shallow copy** of the current FrameState."""
        with self._lock:
            return FrameState(
                frame_id=self._current.frame_id,
                timestamp=self._current.timestamp,
                detections=list(self._current.detections),
                violations=list(self._current.violations),
            )

    def history(self) -> List[FrameState]:
        """Return a shallow copy of the history list."""
        with self._lock:
            return list(self._history)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialise the current frame snapshot to a JSON-compatible dict.

        Schema
        ------
        .. code-block:: json

            {
              "frame_id": 0,
              "timestamp": "2025-01-01T00:00:00Z",
              "detections": [...],
              "violations": [...]
            }
        """
        with self._lock:
            frame = self._current
            return {
                "frame_id": frame.frame_id,
                "timestamp": frame.timestamp,
                "detections": [asdict(d) for d in frame.detections],
                "violations": [asdict(v) for v in frame.violations],
            }

    def clear_ocr_cache(self) -> None:
        """Purge the entire OCR cache (useful on source switch)."""
        with self._lock:
            self._ocr_cache.clear()
            logger.debug("OCR cache cleared")

    def clear_parking_dwell(self) -> None:
        """Purge all parking dwell counters."""
        with self._lock:
            self._parking_dwell.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds")
