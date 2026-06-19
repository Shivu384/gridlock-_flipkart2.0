"""
video_processor.py
------------------
Producer/Consumer video ingestion pipeline using a bounded ``queue.Queue``.

Architecture
~~~~~~~~~~~~

.. code-block:: text

    ┌──────────────┐  Queue  ┌─────────────────┐
    │  _producer() │ ──────► │  _consumer()    │
    │  (thread 1)  │         │  (thread 2)     │
    │  VideoCapture│         │  Detector       │
    └──────────────┘         │  ViolationEngine│
                             │  OCRService     │
                             │  Annotator      │
                             └─────────────────┘

The producer reads frames from the source, applies frame-skipping, resizes
them, and enqueues them.  The consumer dequeues frames, runs the full
detection+violation+OCR pipeline, and emits results via a callback.

Thread safety
~~~~~~~~~~~~~
All shared state is in ``StateManager`` (``RLock``-protected).
No unguarded globals are used.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from backend.core.config import AppConfig
from backend.core.state_manager import (
    BoundingBox,
    DetectionRecord,
    FrameState,
    StateManager,
    ViolationEvent,
    _now,
)
from backend.services.detector import Detector
from backend.services.ocr import OCRService
from backend.services.tracker import TrackManager
from backend.services.violation_engine import ViolationEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentinel object used to signal producer EOF to consumer
# ---------------------------------------------------------------------------
_SENTINEL = object()


# ---------------------------------------------------------------------------
# Result dataclass returned per processed frame
# ---------------------------------------------------------------------------

@dataclass
class FrameResult:
    """Aggregated output for a single processed frame."""

    frame_id: int
    timestamp: str
    annotated_frame: np.ndarray
    detections: List[DetectionRecord]
    violations: List[ViolationEvent]
    state_dict: Dict  # JSON-serialisable snapshot from StateManager


# ---------------------------------------------------------------------------
# Annotator (inline – kept here to avoid circular imports)
# ---------------------------------------------------------------------------

class _Annotator:
    """
    Draws bounding boxes, labels, and the parking ROI on a BGR frame.
    """

    def __init__(self, config: AppConfig) -> None:
        self._out_cfg = config.output
        self._vcfg = config.violation

    def annotate(
        self,
        frame: np.ndarray,
        detections: List[DetectionRecord],
        violations: List[ViolationEvent],
    ) -> np.ndarray:
        """Return a new annotated copy of *frame*."""
        out = frame.copy()
        self._draw_roi(out)
        violation_track_ids = {v.track_id for v in violations}

        for det in detections:
            colour = self._out_cfg.bbox_colours.get(
                det.class_name, (200, 200, 200)
            )
            # Highlight violating tracks with a thicker border
            thickness = (
                self._out_cfg.thickness + 2
                if det.track_id in violation_track_ids
                else self._out_cfg.thickness
            )
            cv2.rectangle(
                out,
                (det.bbox.x1, det.bbox.y1),
                (det.bbox.x2, det.bbox.y2),
                colour,
                thickness,
            )
            label = f"{det.class_name}"
            if det.track_id is not None:
                label += f" #{det.track_id}"
            if det.plate_text:
                label += f" [{det.plate_text}]"
            label += f" {det.confidence:.2f}"

            self._put_label(out, label, det.bbox.x1, det.bbox.y1, colour)

        # Overlay violation banners
        for i, viol in enumerate(violations):
            text = f"! {viol.violation_type}"
            if viol.plate_text:
                text += f" | {viol.plate_text}"
            cv2.putText(
                out,
                text,
                (10, 30 + i * 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                self._out_cfg.violation_text_colour,
                2,
                cv2.LINE_AA,
            )

        return out

    def _draw_roi(self, frame: np.ndarray) -> None:
        """Draw the parking ROI polygon on *frame* (in-place)."""
        pts = np.array(self._vcfg.parking_roi, dtype=np.int32)
        cv2.polylines(
            frame,
            [pts.reshape(-1, 1, 2)],
            isClosed=True,
            color=self._out_cfg.parking_roi_colour,
            thickness=2,
        )

    def _put_label(
        self,
        frame: np.ndarray,
        text: str,
        x: int,
        y: int,
        colour: Tuple[int, int, int],
    ) -> None:
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = self._out_cfg.font_scale
        thickness = self._out_cfg.thickness

        (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
        # Background pill
        cv2.rectangle(frame, (x, y - th - 6), (x + tw + 4, y), colour, -1)
        cv2.putText(
            frame,
            text,
            (x + 2, y - 3),
            font,
            scale,
            (0, 0, 0),
            thickness,
            cv2.LINE_AA,
        )


# ---------------------------------------------------------------------------
# VideoProcessor
# ---------------------------------------------------------------------------

class VideoProcessor:
    """
    Manages the full producer/consumer pipeline for a video source.

    Parameters
    ----------
    config:
        Application configuration.
    result_callback:
        Called in the consumer thread for every processed frame.
        Signature: ``callback(result: FrameResult) -> None``.

    Usage
    -----
    >>> def on_frame(result: FrameResult) -> None:
    ...     cv2.imshow("out", result.annotated_frame)
    ...     cv2.waitKey(1)
    >>> vp = VideoProcessor(config, on_frame)
    >>> vp.start("traffic.mp4")
    >>> vp.join()
    """

    def __init__(
        self,
        config: AppConfig,
        result_callback: Callable[[FrameResult], None],
    ) -> None:
        self._cfg = config
        self._callback = result_callback

        # Shared objects (created once, reused across start/stop cycles)
        self._state = StateManager()
        self._track_mgr = TrackManager(
            stale_frame_limit=config.detection.track_buffer * 3
        )
        self._detector = Detector(config)
        self._ocr_svc = OCRService(config, self._state, self._track_mgr)
        self._violation_engine = ViolationEngine(config, self._state, self._track_mgr)
        self._annotator = _Annotator(config)

        # Threading primitives
        self._frame_queue: queue.Queue = queue.Queue(
            maxsize=config.video.queue_maxsize
        )
        self._stop_event = threading.Event()
        self._producer_thread: Optional[threading.Thread] = None
        self._consumer_thread: Optional[threading.Thread] = None

        # Counters
        self._raw_frame_count: int = 0    # total frames read from source
        self._processed_frame_count: int = 0  # total frames through pipeline

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, source: str | int) -> None:
        """
        Open *source* and launch producer + consumer threads.

        Parameters
        ----------
        source:
            Video file path, RTSP URL, or integer camera index.
        """
        self._stop_event.clear()
        self._raw_frame_count = 0
        self._processed_frame_count = 0
        self._state.clear_ocr_cache()
        self._state.clear_parking_dwell()

        self._producer_thread = threading.Thread(
            target=self._producer,
            args=(source,),
            name="video-producer",
            daemon=True,
        )
        self._consumer_thread = threading.Thread(
            target=self._consumer,
            name="video-consumer",
            daemon=True,
        )

        self._consumer_thread.start()
        self._producer_thread.start()
        logger.info("VideoProcessor started | source=%s", source)

    def stop(self) -> None:
        """Signal both threads to terminate cleanly."""
        logger.info("VideoProcessor stop requested")
        self._stop_event.set()
        # Drain + unblock queue so producer/consumer don't deadlock
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break
        self._frame_queue.put(_SENTINEL)

    def join(self, timeout: Optional[float] = None) -> None:
        """Block until both threads finish."""
        if self._producer_thread:
            self._producer_thread.join(timeout=timeout)
        if self._consumer_thread:
            self._consumer_thread.join(timeout=timeout)
        self._ocr_svc.shutdown(wait=True)
        logger.info(
            "VideoProcessor finished | raw_frames=%d | processed=%d",
            self._raw_frame_count,
            self._processed_frame_count,
        )

    @property
    def state_manager(self) -> StateManager:
        """Expose the underlying ``StateManager`` for external inspection."""
        return self._state

    # ------------------------------------------------------------------
    # Producer thread
    # ------------------------------------------------------------------

    def _producer(self, source: str | int) -> None:
        """
        Read frames from *source* and enqueue them for the consumer.

        Only every ``frame_skip``-th frame is enqueued; the rest are
        discarded after a ``cap.grab()`` to avoid seek overhead.
        """
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            logger.error("Failed to open video source: %s", source)
            self._frame_queue.put(_SENTINEL)
            return

        fps_src = cap.get(cv2.CAP_PROP_FPS) or 30.0
        skip = max(1, self._cfg.video.frame_skip)
        tw = self._cfg.video.target_width
        th = self._cfg.video.target_height

        logger.info(
            "Producer: source opened | fps=%.1f | skip=%d | target=%dx%d",
            fps_src, skip, tw, th,
        )

        try:
            while not self._stop_event.is_set():
                ret = cap.grab()
                if not ret:
                    logger.info("Producer: video source exhausted")
                    break

                self._raw_frame_count += 1

                # Decode only frames we intend to process
                if self._raw_frame_count % skip != 0:
                    continue

                ret, frame = cap.retrieve()
                if not ret or frame is None:
                    continue

                # Resize if configured
                if tw and th:
                    frame = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_LINEAR)

                # Block here if the consumer is behind (back-pressure)
                try:
                    self._frame_queue.put(frame, timeout=2.0)
                except queue.Full:
                    logger.warning("Producer: frame queue full – dropping frame")

        except Exception as exc:
            logger.error("Producer thread error: %s", exc, exc_info=True)
        finally:
            cap.release()
            self._frame_queue.put(_SENTINEL)
            logger.debug("Producer thread exiting")

    # ------------------------------------------------------------------
    # Consumer thread
    # ------------------------------------------------------------------

    def _consumer(self) -> None:
        """
        Dequeue frames and run the full detection → violation → OCR pipeline.

        For each frame:
        1. ``Detector.detect()``  – YOLO inference with ByteTrack.
        2. ``TrackManager.update()`` – update track metadata.
        3. OCR gate – submit OCR if a plate+violation co-occurs and no
           cached result exists.
        4. ``ViolationEngine.evaluate()`` – apply all rules.
        5. ``StateManager`` update – log detections + violations.
        6. Annotation – draw bboxes, labels, ROI.
        7. ``result_callback`` – hand the result to the caller.
        """
        prune_interval = 30  # prune stale tracks every N processed frames

        while not self._stop_event.is_set():
            try:
                item = self._frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is _SENTINEL:
                logger.info("Consumer: received sentinel – shutting down")
                break

            frame: np.ndarray = item
            self._processed_frame_count += 1
            frame_id = self._processed_frame_count
            timestamp = _now()

            # --- 1. Detection -------------------------------------------
            detections = self._detector.detect(frame, persist=True)

            # --- 2. Track update ----------------------------------------
            self._track_mgr.update(detections, frame_id)

            # --- 3. OCR gate --------------------------------------------
            #   Enrich detections with cached plate texts before rule eval
            plate_detections = [d for d in detections if d.class_name == "Plate"]
            violation_classes = {"WithoutHelmet", "TripleRiding"}
            has_violation_candidate = any(
                d.class_name in violation_classes for d in detections
            )

            for plate_det in plate_detections:
                tid = plate_det.track_id
                if tid is None:
                    continue

                cached = self._state.get_cached_ocr(tid)
                if cached:
                    plate_det.plate_text, plate_det.plate_confidence = cached
                elif has_violation_candidate and self._ocr_svc.needs_ocr(tid):
                    self._ocr_svc.submit(
                        track_id=tid,
                        frame=frame,
                        plate_bbox=plate_det.bbox,
                    )

            # Propagate known plate texts to nearby vehicle detections
            self._propagate_plates(detections)

            # --- 4. Violation rules -------------------------------------
            self._state.begin_frame(frame_id)
            violations = self._violation_engine.evaluate(
                detections, frame_id, timestamp
            )

            # --- 5. State update ----------------------------------------
            for det in detections:
                self._state.add_detection(det)
            for viol in violations:
                self._state.add_violation(viol)

            # --- 6. Annotation ------------------------------------------
            annotated = self._annotator.annotate(frame, detections, violations)

            # --- 7. Result callback -------------------------------------
            result = FrameResult(
                frame_id=frame_id,
                timestamp=timestamp,
                annotated_frame=annotated,
                detections=detections,
                violations=violations,
                state_dict=self._state.to_dict(),
            )
            try:
                self._callback(result)
            except Exception as cb_exc:
                logger.error("Result callback raised: %s", cb_exc, exc_info=True)

            # Periodic maintenance
            if frame_id % prune_interval == 0:
                removed = self._track_mgr.prune(frame_id)
                if removed:
                    logger.debug("Pruned %d stale tracks", removed)

            self._frame_queue.task_done()

        logger.debug("Consumer thread exiting")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _propagate_plates(self, detections: List[DetectionRecord]) -> None:
        """
        Assign plate text from ``TrackManager`` cache to matching vehicle
        detections so that violation events carry plate information at
        the time of the rule evaluation (even before OCR completes).

        This is a best-effort heuristic: it looks up the plate text stored
        in the ``VehicleTrack`` (written by the OCR callback) for each
        detection whose ``track_id`` is known.
        """
        for det in detections:
            if det.track_id is None or det.plate_text is not None:
                continue
            track = self._track_mgr.get(det.track_id)
            if track and track.plate_text:
                det.plate_text = track.plate_text
                det.plate_confidence = track.plate_confidence
