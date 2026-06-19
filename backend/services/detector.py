"""
detector.py
-----------
YOLOv8 inference wrapper with persistent ByteTrack tracking.

Responsibilities
~~~~~~~~~~~~~~~~
* Load and warm-up the custom ``best.pt`` model once.
* Run ``model.track()`` so track IDs persist across skipped frames.
* Convert raw Ultralytics results into typed ``DetectionRecord`` objects.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from backend.core.config import AppConfig, DetectionConfig
from backend.core.state_manager import BoundingBox, DetectionRecord

logger = logging.getLogger(__name__)


class Detector:
    """
    Wraps a YOLOv8 model with persistent tracking.

    Parameters
    ----------
    config:
        Application configuration.  Only ``config.detection`` and
        ``config.classes`` are consumed by this class.

    Notes
    -----
    * ``model.track()`` is called instead of ``model.predict()`` so that
      ByteTrack assigns IDs that survive the frame-skip gaps in the
      ``VideoProcessor`` pipeline.
    * The first call performs a warm-up pass on a blank frame to avoid
      latency spikes on the first real frame.
    """

    def __init__(self, config: AppConfig) -> None:
        self._cfg: DetectionConfig = config.detection
        self._class_labels: dict[int, str] = config.classes.labels

        logger.info("Loading YOLO model from %s …", self._cfg.model_path)
        self._model = self._load_model()
        self._warmup()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _load_model(self):
        """Import Ultralytics lazily and return a loaded YOLO model."""
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "ultralytics is not installed.  Run: pip install ultralytics"
            ) from exc

        model_path = Path(self._cfg.model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found at: {model_path}")

        model = YOLO(str(model_path))
        model.to(self._cfg.device)
        logger.info(
            "Model loaded | device=%s | half=%s",
            self._cfg.device,
            self._cfg.half_precision,
        )
        return model

    def _warmup(self) -> None:
        """
        Run inference on a blank frame to initialise CUDA kernels and
        avoid first-frame latency spikes.
        """
        logger.debug("Warming up model …")
        blank = np.zeros(
            (self._cfg.image_size, self._cfg.image_size, 3), dtype=np.uint8
        )
        try:
            self._model.predict(
                source=blank,
                imgsz=self._cfg.image_size,
                verbose=False,
                half=self._cfg.half_precision,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Warm-up failed (non-fatal): %s", exc)
        logger.debug("Model warm-up complete")

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def detect(
        self,
        frame: np.ndarray,
        persist: bool = True,
    ) -> List[DetectionRecord]:
        """
        Run YOLO inference with tracking on a single BGR frame.

        Parameters
        ----------
        frame:
            BGR image as a NumPy array (H × W × 3, uint8).
        persist:
            Whether to carry ByteTrack state between calls.  Always
            ``True`` in normal operation so track IDs survive frame skips.

        Returns
        -------
        List[DetectionRecord]
            One record per detected object, sorted by confidence descending.
        """
        if frame is None or frame.size == 0:
            logger.warning("detect() received an empty frame – skipping")
            return []

        try:
            results = self._model.track(
                source=frame,
                conf=self._cfg.confidence_threshold,
                iou=self._cfg.iou_threshold,
                imgsz=self._cfg.image_size,
                half=self._cfg.half_precision,
                persist=persist,
                verbose=False,
                tracker=self._cfg.tracker_config,
            )
        except Exception as exc:
            logger.error("YOLO inference failed: %s", exc, exc_info=True)
            return []

        return self._parse_results(results)

    # ------------------------------------------------------------------
    # Result parsing
    # ------------------------------------------------------------------

    def _parse_results(self, results) -> List[DetectionRecord]:
        """
        Convert Ultralytics ``Results`` objects to ``DetectionRecord`` list.

        Parameters
        ----------
        results:
            The list returned by ``model.track()``.

        Returns
        -------
        List[DetectionRecord]
        """
        records: List[DetectionRecord] = []

        for result in results:
            if result.boxes is None:
                continue

            boxes = result.boxes
            n = len(boxes)

            # xyxy coordinates (N × 4), confidence (N,), class (N,)
            xyxy: np.ndarray = boxes.xyxy.cpu().numpy() if n else np.empty((0, 4))
            confs: np.ndarray = boxes.conf.cpu().numpy() if n else np.empty((0,))
            cls_ids: np.ndarray = boxes.cls.cpu().numpy().astype(int) if n else np.empty((0,), dtype=int)

            # Track IDs may be None if tracking hasn't assigned them yet
            track_ids: Optional[np.ndarray] = None
            if boxes.id is not None:
                track_ids = boxes.id.cpu().numpy().astype(int)

            for i in range(n):
                cls_id = int(cls_ids[i])
                label = self._class_labels.get(cls_id, f"class_{cls_id}")
                x1, y1, x2, y2 = map(int, xyxy[i])
                track_id = int(track_ids[i]) if track_ids is not None else None

                records.append(
                    DetectionRecord(
                        class_id=cls_id,
                        class_name=label,
                        confidence=float(confs[i]),
                        bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                        track_id=track_id,
                    )
                )

        records.sort(key=lambda r: r.confidence, reverse=True)
        logger.debug("Detected %d objects", len(records))
        return records
