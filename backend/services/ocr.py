"""
ocr.py
------
Asynchronous EasyOCR plate-reading service with per-track caching.

Design
~~~~~~
* A fixed-size ``ThreadPoolExecutor`` (size = ``config.ocr.ocr_workers``)
  runs OCR off the critical inference path.
* Results are written back to ``StateManager`` and ``TrackManager`` via
  callbacks so that they are available for subsequent frames.
* A ``track_id`` is checked against the cache **before** submitting a job,
  which avoids redundant re-reads of the same plate across many frames.
* The ``OCRService`` class owns no global state; all state lives in
  ``StateManager`` or ``TrackManager``.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from backend.core.config import AppConfig, OCRConfig
from backend.core.state_manager import BoundingBox, StateManager
from backend.services.tracker import TrackManager

logger = logging.getLogger(__name__)

# Type alias for the completion callback supplied by callers
OCRCallback = Callable[[int, str, float], None]


def _crop_bbox(frame: np.ndarray, bbox: BoundingBox, padding: int = 4) -> np.ndarray:
    """
    Extract and return the region of interest for a plate bounding box.

    Parameters
    ----------
    frame:
        Full BGR source frame.
    bbox:
        Bounding box of the plate detection.
    padding:
        Extra pixels added around the crop (clipped to image bounds).

    Returns
    -------
    np.ndarray
        Cropped BGR image, or an empty array if the crop is degenerate.
    """
    h, w = frame.shape[:2]
    x1 = max(0, bbox.x1 - padding)
    y1 = max(0, bbox.y1 - padding)
    x2 = min(w, bbox.x2 + padding)
    y2 = min(h, bbox.y2 + padding)

    if x2 <= x1 or y2 <= y1:
        return np.empty((0,), dtype=np.uint8)

    return frame[y1:y2, x1:x2].copy()


def _run_easyocr(
    reader,
    crop: np.ndarray,
    min_confidence: float,
) -> Tuple[str, float]:
    """
    Run EasyOCR on a cropped plate image.

    Parameters
    ----------
    reader:
        An initialised ``easyocr.Reader`` instance.
    crop:
        Cropped BGR plate image.
    min_confidence:
        Minimum confidence threshold.  Results below this are discarded.

    Returns
    -------
    Tuple[str, float]
        ``(plate_text, confidence)`` – both empty/0 if nothing passes threshold.
    """
    if crop.size == 0:
        return "UNREADABLE", 0.0

    try:
        ocr_results = reader.readtext(crop, detail=1)
    except Exception as exc:
        logger.error("EasyOCR inference failed: %s", exc, exc_info=True)
        return "UNREADABLE", 0.0

    # Collect all text snippets that pass the confidence threshold
    accepted: List[Tuple[str, float]] = []
    for (_bbox, text, conf) in ocr_results:
        if conf >= min_confidence and text.strip():
            accepted.append((text.strip().upper(), conf))

    if not accepted:
        return "UNREADABLE", 0.0

    # Return the highest-confidence reading
    best = max(accepted, key=lambda t: t[1])
    return best


class OCRService:
    """
    Manages an async pool of EasyOCR workers with per-track result caching.

    Usage
    -----
    >>> svc = OCRService(config, state_manager, track_manager)
    >>> svc.submit(track_id=7, frame=frame, plate_bbox=bbox)
    >>> # … result appears in state_manager / track_manager automatically
    >>> svc.shutdown()
    """

    def __init__(
        self,
        config: AppConfig,
        state_manager: StateManager,
        track_manager: TrackManager,
    ) -> None:
        self._cfg: OCRConfig = config.ocr
        self._state: StateManager = state_manager
        self._tracks: TrackManager = track_manager

        # Pending futures by track_id – avoids submitting the same track twice
        self._pending: Dict[int, Future] = {}
        self._pending_lock = threading.Lock()

        if self._cfg.enabled:
            logger.info("Initialising EasyOCR (languages=%s) …", self._cfg.languages)
            self._reader = self._init_reader()
        else:
            logger.info("OCR disabled in config – skipping EasyOCR initialization")
            self._reader = None

        self._executor = ThreadPoolExecutor(
            max_workers=self._cfg.ocr_workers,
            thread_name_prefix="ocr-worker",
        )
        logger.info(
            "OCRService ready | enabled=%s | workers=%d | gpu=%s",
            self._cfg.enabled,
            self._cfg.ocr_workers,
            self._cfg.gpu,
        )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_reader(self):
        """Import and initialise EasyOCR reader (slow – runs once at start)."""
        try:
            import easyocr  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "easyocr is not installed.  Run: pip install easyocr"
            ) from exc

        return easyocr.Reader(
            self._cfg.languages,
            gpu=self._cfg.gpu,
            verbose=False,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def needs_ocr(self, track_id: int) -> bool:
        """
        Return ``True`` if OCR should be run for this track.

        OCR is skipped when:
        * The track already has a cached result in ``StateManager``, OR
        * An OCR job is already pending for this track_id.
        """
        if self._state.has_cached_ocr(track_id):
            return False
        with self._pending_lock:
            if track_id in self._pending and not self._pending[track_id].done():
                return False
        return True

    def submit(
        self,
        track_id: int,
        frame: np.ndarray,
        plate_bbox: BoundingBox,
        callback: Optional[OCRCallback] = None,
    ) -> None:
        """
        Submit an OCR job for the plate at *plate_bbox* in *frame*.

        The job runs on a background thread.  Once complete, the result is:
        1. Stored in ``StateManager._ocr_cache`` (via ``cache_ocr``).
        2. Stored in the ``VehicleTrack.plate_text`` field.
        3. Passed to *callback(track_id, plate_text, confidence)* if provided.

        Parameters
        ----------
        track_id:
            ByteTrack ID of the vehicle this plate belongs to.
        frame:
            Full BGR source frame (will be cropped internally).
        plate_bbox:
            Bounding box of the plate detection.
        callback:
            Optional function called on completion in the worker thread.
        """
        if not self.needs_ocr(track_id):
            logger.debug("OCR skipped (cached or pending) | track_id=%d", track_id)
            return

        # Crop immediately on the calling thread to avoid holding a reference
        # to the full (potentially large) frame inside the queue.
        crop = _crop_bbox(frame, plate_bbox)

        future = self._executor.submit(
            self._ocr_job,
            track_id=track_id,
            crop=crop,
            callback=callback,
        )

        with self._pending_lock:
            self._pending[track_id] = future

        logger.debug("OCR job submitted | track_id=%d", track_id)

    def get_result(self, track_id: int) -> Optional[Tuple[str, float]]:
        """
        Return the cached OCR result for *track_id*, or ``None``.

        Equivalent to ``state_manager.get_cached_ocr(track_id)``.
        """
        return self._state.get_cached_ocr(track_id)

    def shutdown(self, wait: bool = True) -> None:
        """Gracefully shut down the thread pool."""
        logger.info("Shutting down OCRService …")
        self._executor.shutdown(wait=wait)
        logger.info("OCRService shut down")

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    def _ocr_job(
        self,
        track_id: int,
        crop: np.ndarray,
        callback: Optional[OCRCallback],
    ) -> None:
        """
        Background worker: run OCR and persist results.

        This method runs inside the ``ThreadPoolExecutor``; it must not
        mutate any unprotected shared state.
        """
        try:
            plate_text, confidence = _run_easyocr(
                self._reader, crop, self._cfg.min_confidence
            )

            if plate_text:
                # Persist in state manager cache
                self._state.cache_ocr(track_id, plate_text, confidence)

                # Persist in track metadata
                track = self._tracks.get(track_id)
                if track is not None:
                    track.plate_text = plate_text
                    track.plate_confidence = confidence

                logger.info(
                    "OCR result | track_id=%d | plate=%s | conf=%.2f",
                    track_id, plate_text, confidence,
                )

                if callback is not None:
                    try:
                        callback(track_id, plate_text, confidence)
                    except Exception as cb_exc:  # noqa: BLE001
                        logger.error("OCR callback raised: %s", cb_exc)
            else:
                logger.debug("OCR returned no result | track_id=%d", track_id)

        except Exception as exc:
            logger.error(
                "OCR job failed | track_id=%d | %s", track_id, exc, exc_info=True
            )
        finally:
            with self._pending_lock:
                self._pending.pop(track_id, None)
