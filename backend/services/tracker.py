"""
tracker.py
----------
Lightweight spatial utilities that augment ByteTrack results.

This module does NOT replace ByteTrack – Ultralytics handles the actual
multi-object tracking.  Instead, ``TrackManager`` provides:

* A ``VehicleTrack`` record per ``track_id`` that accumulates per-track
  metadata (class history, plate association, dwell counters, etc.).
* Convenience helpers used by the violation engine
  (e.g. ``get_dominant_class``).

The class is intentionally *stateless* with respect to pixel positions – it
cares only about class labels and violation metadata.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from backend.core.state_manager import DetectionRecord

logger = logging.getLogger(__name__)


@dataclass
class VehicleTrack:
    """
    Accumulated metadata for a single tracked object.

    Attributes
    ----------
    track_id:
        Unique identifier assigned by ByteTrack.
    seen_classes:
        Counter of how often each class_name has been observed for this ID.
    plate_text:
        Most recently confirmed plate reading (or None).
    plate_confidence:
        Confidence of the most recent plate reading.
    first_frame:
        Frame ID when this track was first seen.
    last_frame:
        Frame ID when this track was most recently updated.
    parking_dwell:
        Consecutive processed frames spent inside the parking ROI.
    """

    track_id: int
    seen_classes: Dict[str, int] = field(default_factory=dict)
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    first_frame: int = 0
    last_frame: int = 0
    parking_dwell: int = 0

    def observe_class(self, class_name: str) -> None:
        """Record a class observation (increments counter)."""
        self.seen_classes[class_name] = self.seen_classes.get(class_name, 0) + 1

    @property
    def dominant_class(self) -> Optional[str]:
        """Return the most frequently observed class name for this track."""
        if not self.seen_classes:
            return None
        return max(self.seen_classes, key=lambda k: self.seen_classes[k])

    @property
    def observation_count(self) -> int:
        return sum(self.seen_classes.values())


class TrackManager:
    """
    Thread-safe registry of ``VehicleTrack`` objects keyed by ``track_id``.

    Lifecycle
    ---------
    1. ``update()`` is called once per processed frame with all new detections.
    2. ``prune()`` should be called periodically to remove stale tracks.
    3. ``get()`` / ``all_tracks()`` provide read access.
    """

    def __init__(self, stale_frame_limit: int = 90) -> None:
        """
        Parameters
        ----------
        stale_frame_limit:
            A track is considered stale if it has not been updated for this
            many processed frames.  Stale tracks are purged by ``prune()``.
        """
        self._lock = threading.RLock()
        self._tracks: Dict[int, VehicleTrack] = {}
        self._stale_limit = stale_frame_limit

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, detections: List[DetectionRecord], frame_id: int) -> None:
        """
        Ingest a batch of detections and update (or create) their tracks.

        Parameters
        ----------
        detections:
            Detections from ``Detector.detect()`` for the current frame.
        frame_id:
            Current processed-frame counter (used for staleness tracking).
        """
        with self._lock:
            for det in detections:
                if det.track_id is None:
                    continue  # untracked detection – skip

                tid = det.track_id
                if tid not in self._tracks:
                    self._tracks[tid] = VehicleTrack(
                        track_id=tid, first_frame=frame_id
                    )
                    logger.debug("New track registered: track_id=%d", tid)

                track = self._tracks[tid]
                track.observe_class(det.class_name)
                track.last_frame = frame_id

                # Propagate OCR data from DetectionRecord → VehicleTrack
                if det.plate_text is not None:
                    track.plate_text = det.plate_text
                    track.plate_confidence = det.plate_confidence

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, track_id: int) -> Optional[VehicleTrack]:
        """Return the ``VehicleTrack`` for *track_id*, or ``None``."""
        with self._lock:
            return self._tracks.get(track_id)

    def all_tracks(self) -> Dict[int, VehicleTrack]:
        """Return a shallow copy of the track registry."""
        with self._lock:
            return dict(self._tracks)

    def increment_parking_dwell(self, track_id: int) -> int:
        """Increment and return the parking dwell counter for *track_id*."""
        with self._lock:
            if track_id in self._tracks:
                self._tracks[track_id].parking_dwell += 1
                return self._tracks[track_id].parking_dwell
            return 0

    def reset_parking_dwell(self, track_id: int) -> None:
        """Reset the parking dwell counter for *track_id* to zero."""
        with self._lock:
            if track_id in self._tracks:
                self._tracks[track_id].parking_dwell = 0

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune(self, current_frame: int) -> int:
        """
        Remove tracks that have not been seen for ``stale_frame_limit`` frames.

        Returns
        -------
        int
            Number of tracks removed.
        """
        with self._lock:
            stale_ids = [
                tid
                for tid, track in self._tracks.items()
                if (current_frame - track.last_frame) > self._stale_limit
            ]
            for tid in stale_ids:
                del self._tracks[tid]
                logger.debug("Track pruned: track_id=%d", tid)
            return len(stale_ids)

    def __len__(self) -> int:
        with self._lock:
            return len(self._tracks)
