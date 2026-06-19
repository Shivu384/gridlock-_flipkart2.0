"""
violation_engine.py
-------------------
Stateless violation-rule functions and the ``ViolationEngine`` orchestrator.

Architecture
~~~~~~~~~~~~
Each rule is an **independent function** with the signature::

    rule_<name>(
        detections: List[DetectionRecord],
        frame_id: int,
        timestamp: str,
        **kwargs,
    ) -> List[ViolationEvent]

The ``ViolationEngine`` class calls all rules and aggregates their results.
New rules can be added without modifying existing ones.

Rules implemented
~~~~~~~~~~~~~~~~~
1. ``rule_without_helmet``  – ``WithoutHelmet`` class detected.
2. ``rule_triple_riding``   – ``TripleRiding`` class detected.
3. ``rule_illegal_parking`` – Polygon ROI occupancy with dwell guard.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np

from backend.core.config import AppConfig, ViolationConfig
from backend.core.state_manager import (
    BoundingBox,
    DetectionRecord,
    ViolationEvent,
    StateManager,
)
from backend.services.tracker import TrackManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _bbox_centre(bbox: BoundingBox) -> Tuple[int, int]:
    """Return the (x, y) centre pixel of a bounding box."""
    return (bbox.x1 + bbox.x2) // 2, (bbox.y1 + bbox.y2) // 2


def _point_in_polygon(point: Tuple[int, int], polygon: List[Tuple[int, int]]) -> bool:
    """
    Return ``True`` if *point* is inside *polygon* using OpenCV.

    Parameters
    ----------
    point:
        (x, y) pixel coordinate.
    polygon:
        List of (x, y) vertices defining the ROI.
    """
    if len(polygon) < 3:
        return False
    pts = np.array(polygon, dtype=np.int32)
    result = cv2.pointPolygonTest(pts, point, measureDist=False)
    return result >= 0  # 0 = on boundary, > 0 = inside


def _roi_bounding_box(polygon: List[Tuple[int, int]]) -> Tuple[int, int, int, int]:
    """Return the axis-aligned bounding box of the polygon as (x1, y1, x2, y2)."""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_iou_with_rect(
    bbox: BoundingBox,
    rect: Tuple[int, int, int, int],
) -> float:
    """
    Compute IoU between *bbox* and an axis-aligned rectangle *rect*.

    Parameters
    ----------
    bbox:
        Detection bounding box.
    rect:
        (x1, y1, x2, y2) rectangle (e.g. ROI bounding box).
    """
    rx1, ry1, rx2, ry2 = rect
    ix1, iy1 = max(bbox.x1, rx1), max(bbox.y1, ry1)
    ix2, iy2 = min(bbox.x2, rx2), min(bbox.y2, ry2)

    inter_w = max(0, ix2 - ix1)
    inter_h = max(0, iy2 - iy1)
    inter = inter_w * inter_h

    if inter == 0:
        return 0.0

    area_a = (bbox.x2 - bbox.x1) * (bbox.y2 - bbox.y1)
    area_b = (rx2 - rx1) * (ry2 - ry1)
    union = area_a + area_b - inter

    return inter / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Rule 1: Without Helmet
# ---------------------------------------------------------------------------

def rule_without_helmet(
    detections: List[DetectionRecord],
    frame_id: int,
    timestamp: str,
    **_kwargs,
) -> List[ViolationEvent]:
    """
    Raise a violation for every ``WithoutHelmet`` detection.

    Parameters
    ----------
    detections:
        All detections in the current frame.
    frame_id:
        Current processed-frame counter.
    timestamp:
        ISO-8601 timestamp string for the current frame.

    Returns
    -------
    List[ViolationEvent]
    """
    events: List[ViolationEvent] = []
    for det in detections:
        if det.class_name == "WithoutHelmet":
            events.append(
                ViolationEvent(
                    violation_type="WithoutHelmet",
                    frame_id=frame_id,
                    timestamp=timestamp,
                    track_id=det.track_id,
                    plate_text=det.plate_text,
                    bbox=det.bbox,
                    confidence=det.confidence,
                    metadata={"class_id": det.class_id},
                )
            )
            logger.debug(
                "Rule1: WithoutHelmet | track_id=%s | frame=%d",
                det.track_id,
                frame_id,
            )
    return events


# ---------------------------------------------------------------------------
# Rule 2: Triple Riding
# ---------------------------------------------------------------------------

def rule_triple_riding(
    detections: List[DetectionRecord],
    frame_id: int,
    timestamp: str,
    **_kwargs,
) -> List[ViolationEvent]:
    """
    Raise a violation for every ``TripleRiding`` detection.

    Parameters
    ----------
    detections:
        All detections in the current frame.
    frame_id:
        Current processed-frame counter.
    timestamp:
        ISO-8601 timestamp string.

    Returns
    -------
    List[ViolationEvent]
    """
    events: List[ViolationEvent] = []
    for det in detections:
        if det.class_name == "TripleRiding":
            events.append(
                ViolationEvent(
                    violation_type="TripleRiding",
                    frame_id=frame_id,
                    timestamp=timestamp,
                    track_id=det.track_id,
                    plate_text=det.plate_text,
                    bbox=det.bbox,
                    confidence=det.confidence,
                    metadata={"class_id": det.class_id},
                )
            )
            logger.debug(
                "Rule2: TripleRiding | track_id=%s | frame=%d",
                det.track_id,
                frame_id,
            )
    return events


# ---------------------------------------------------------------------------
# Rule 3: Illegal Parking (ROI + dwell)
# ---------------------------------------------------------------------------

def rule_illegal_parking(
    detections: List[DetectionRecord],
    frame_id: int,
    timestamp: str,
    violation_cfg: Optional[ViolationConfig] = None,
    track_manager: Optional[TrackManager] = None,
    state_manager: Optional[StateManager] = None,
    **_kwargs,
) -> List[ViolationEvent]:
    """
    Detect vehicles illegally parked inside the configurable polygon ROI.

    The rule fires only when a tracked vehicle has spent at least
    ``violation_cfg.parking_min_frames`` **consecutive** processed frames
    inside the ROI.

    Algorithm
    ---------
    1. Fast pre-filter: check IoU of detection bbox against the ROI
       axis-aligned bounding box.
    2. Precise test: ``pointPolygonTest`` on the bbox centre point.
    3. Dwell guard: use ``TrackManager`` / ``StateManager`` to count
       consecutive frames inside the ROI; raise violation only when the
       threshold is met.
    4. On exit: reset the dwell counter so the violation is not re-raised
       until the vehicle re-enters.

    Parameters
    ----------
    detections:
        All detections in the current frame.
    frame_id:
        Current processed-frame counter.
    timestamp:
        ISO-8601 timestamp string.
    violation_cfg:
        ``ViolationConfig`` containing the parking polygon and thresholds.
    track_manager:
        ``TrackManager`` instance for dwell counter storage.
    state_manager:
        ``StateManager`` instance (alternative / additional dwell storage).

    Returns
    -------
    List[ViolationEvent]
    """
    if violation_cfg is None:
        logger.warning("rule_illegal_parking: no ViolationConfig supplied – skipping")
        return []

    events: List[ViolationEvent] = []
    polygon: List[Tuple[int, int]] = violation_cfg.parking_roi
    min_frames: int = violation_cfg.parking_min_frames
    iou_thresh: float = violation_cfg.parking_roi_iou_threshold

    if len(polygon) < 3:
        logger.warning("Parking ROI polygon has fewer than 3 vertices – rule disabled")
        return []

    roi_rect = _roi_bounding_box(polygon)

    # Collect which track_ids are currently inside the ROI
    inside_ids: set[int] = set()

    for det in detections:
        # Only test vehicles (not helmets or plates – they don't park)
        if det.class_name not in ("WithHelmet", "WithoutHelmet", "TripleRiding"):
            continue

        if det.track_id is None:
            continue

        # Fast pre-filter
        if _bbox_iou_with_rect(det.bbox, roi_rect) < iou_thresh:
            _reset_dwell(det.track_id, track_manager, state_manager)
            continue

        # Precise point-in-polygon test on the bottom-centre of the bbox
        # (approximates the vehicle's ground contact point)
        centre_x = (det.bbox.x1 + det.bbox.x2) // 2
        bottom_y = det.bbox.y2
        inside = _point_in_polygon((centre_x, bottom_y), polygon)

        if not inside:
            _reset_dwell(det.track_id, track_manager, state_manager)
            continue

        inside_ids.add(det.track_id)
        dwell = _increment_dwell(det.track_id, track_manager, state_manager)

        logger.debug(
            "Parking dwell | track_id=%d | dwell=%d/%d | frame=%d",
            det.track_id, dwell, min_frames, frame_id,
        )

        if dwell >= min_frames:
            # Resolve plate from track cache
            plate_text: Optional[str] = None
            if track_manager is not None:
                track = track_manager.get(det.track_id)
                if track is not None:
                    plate_text = track.plate_text
            if plate_text is None and state_manager is not None:
                cached = state_manager.get_cached_ocr(det.track_id)
                if cached:
                    plate_text = cached[0]

            events.append(
                ViolationEvent(
                    violation_type="IllegalParking",
                    frame_id=frame_id,
                    timestamp=timestamp,
                    track_id=det.track_id,
                    plate_text=plate_text,
                    bbox=det.bbox,
                    confidence=det.confidence,
                    metadata={
                        "dwell_frames": dwell,
                        "parking_roi": polygon,
                    },
                )
            )
            # Reset so we don't spam events on every subsequent frame
            _reset_dwell(det.track_id, track_manager, state_manager)

            logger.info(
                "Rule3: IllegalParking | track_id=%d | plate=%s | dwell=%d | frame=%d",
                det.track_id, plate_text, dwell, frame_id,
            )

    return events


# ---------------------------------------------------------------------------
# Dwell helpers (handle both TrackManager and StateManager)
# ---------------------------------------------------------------------------

def _increment_dwell(
    track_id: int,
    track_manager: Optional[TrackManager],
    state_manager: Optional[StateManager],
) -> int:
    """Increment dwell via whichever managers are available and return the count."""
    dwell = 0
    if track_manager is not None:
        dwell = track_manager.increment_parking_dwell(track_id)
    if state_manager is not None:
        dwell = state_manager.increment_parking_dwell(track_id)
    return dwell


def _reset_dwell(
    track_id: int,
    track_manager: Optional[TrackManager],
    state_manager: Optional[StateManager],
) -> None:
    """Reset dwell via whichever managers are available."""
    if track_manager is not None:
        track_manager.reset_parking_dwell(track_id)
    if state_manager is not None:
        state_manager.reset_parking_dwell(track_id)


# ---------------------------------------------------------------------------
# ViolationEngine orchestrator
# ---------------------------------------------------------------------------

class ViolationEngine:
    """
    Orchestrates all violation rules for a processed frame.

    Usage
    -----
    >>> engine = ViolationEngine(config, state_manager, track_manager)
    >>> violations = engine.evaluate(detections, frame_id, timestamp)
    """

    # Registry of all rule functions.  Add new rules here.
    _RULES = [
        rule_without_helmet,
        rule_triple_riding,
        rule_illegal_parking,
    ]

    def __init__(
        self,
        config: AppConfig,
        state_manager: StateManager,
        track_manager: TrackManager,
    ) -> None:
        self._vcfg: ViolationConfig = config.violation
        self._state: StateManager = state_manager
        self._tracks: TrackManager = track_manager

    def evaluate(
        self,
        detections: List[DetectionRecord],
        frame_id: int,
        timestamp: str,
    ) -> List[ViolationEvent]:
        """
        Run all registered rules against *detections* and return all events.

        Parameters
        ----------
        detections:
            Typed detection records for the current frame.
        frame_id:
            Current processed-frame counter.
        timestamp:
            ISO-8601 UTC timestamp of the current frame.

        Returns
        -------
        List[ViolationEvent]
            Aggregated violation events from all rules.
        """
        shared_kwargs = {
            "violation_cfg": self._vcfg,
            "track_manager": self._tracks,
            "state_manager": self._state,
        }

        all_events: List[ViolationEvent] = []
        for rule_fn in self._RULES:
            try:
                events = rule_fn(
                    detections=detections,
                    frame_id=frame_id,
                    timestamp=timestamp,
                    **shared_kwargs,
                )
                all_events.extend(events)
            except Exception as exc:
                logger.error(
                    "Rule %s raised an exception: %s",
                    rule_fn.__name__,
                    exc,
                    exc_info=True,
                )

        return all_events
