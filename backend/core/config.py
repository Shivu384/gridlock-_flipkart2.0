"""
config.py
---------
Centralised configuration for the Gridlock traffic-violation detection engine.

All tuneable parameters live here so that nothing is hard-coded elsewhere.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT_DIR: Path = Path(__file__).resolve().parents[2]  # repo root
MODEL_PATH: Path = ROOT_DIR / "best.pt"


# ---------------------------------------------------------------------------
# Device auto-detection
# ---------------------------------------------------------------------------

def _default_device() -> str:
    """Return 'cuda' if a CUDA-capable GPU is available, else 'cpu'."""
    try:
        import torch  # type: ignore
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _default_half_precision() -> bool:
    """Enable FP16 only when running on GPU."""
    try:
        import torch  # type: ignore
        return torch.cuda.is_available()
    except ImportError:
        return False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL: int = logging.DEBUG
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# ---------------------------------------------------------------------------
# Video processing
# ---------------------------------------------------------------------------

@dataclass
class VideoConfig:
    """Parameters that govern how video frames are ingested and queued."""

    frame_skip: int = 3
    """Process every Nth frame (1 = no skip, 3 = process frames 0,3,6,…)."""

    queue_maxsize: int = 64
    """Maximum depth of the producer→consumer frame queue."""

    target_width: int = 1280
    """Resize frame width before inference (None = no resize)."""

    target_height: int = 720
    """Resize frame height before inference (None = no resize)."""


# ---------------------------------------------------------------------------
# Detection / Tracking
# ---------------------------------------------------------------------------

@dataclass
class DetectionConfig:
    """YOLO inference and ByteTrack settings."""

    model_path: Path = MODEL_PATH
    confidence_threshold: float = 0.40
    iou_threshold: float = 0.45
    device: str = field(default_factory=_default_device)
    half_precision: bool = field(default_factory=_default_half_precision)
    image_size: int = 640         # YOLO input size (must be multiple of 32)

    # ByteTrack / BoT-SORT parameters (passed through to ultralytics tracker)
    tracker_config: str = "bytetrack.yaml"
    track_buffer: int = 30
    """Number of frames a lost track is kept alive (handles frame skipping)."""


# ---------------------------------------------------------------------------
# Class labels (must match best.pt training order)
# ---------------------------------------------------------------------------

@dataclass
class ClassConfig:
    """Maps model class indices to human-readable labels."""

    # Key = class index in the model output
    labels: dict[int, str] = field(default_factory=lambda: {
        0: "Plate",
        1: "WithHelmet",
        2: "WithoutHelmet",
        3: "TripleRiding",
    })

    @property
    def index_of(self) -> dict[str, int]:
        """Reverse mapping: label → class index."""
        return {v: k for k, v in self.labels.items()}


# ---------------------------------------------------------------------------
# Violation rules
# ---------------------------------------------------------------------------

@dataclass
class ViolationConfig:
    """Parameters for each violation rule."""

    # Rule 3 – Illegal Parking
    # Polygon defined as a list of (x, y) pixel coordinates in the source
    # video frame.  Change these points to match the parking zone in your
    # camera feed.
    parking_roi: List[Tuple[int, int]] = field(default_factory=lambda: [
        (200, 300),
        (800, 300),
        (800, 600),
        (200, 600),
    ])

    # Minimum consecutive frames a vehicle must be inside the ROI before the
    # parking violation is raised (avoids false positives on transient overlap).
    parking_min_frames: int = 30

    # Minimum IoU between a detection bbox and the parking ROI bounding box
    # used as a fast pre-filter before the expensive point-in-polygon check.
    parking_roi_iou_threshold: float = 0.10


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

@dataclass
class OCRConfig:
    """EasyOCR settings."""

    languages: List[str] = field(default_factory=lambda: ["en"])
    gpu: bool = True
    # Async thread-pool workers dedicated to OCR
    ocr_workers: int = 2
    # Minimum OCR confidence to accept a plate reading
    min_confidence: float = 0.50
    # Seconds before a cached plate reading is considered stale
    cache_ttl_seconds: float = 30.0


# ---------------------------------------------------------------------------
# Output / Annotation
# ---------------------------------------------------------------------------

@dataclass
class OutputConfig:
    """Colours and font settings for frame annotation."""

    bbox_colours: dict[str, Tuple[int, int, int]] = field(default_factory=lambda: {
        "Plate":          (0, 255, 255),   # cyan
        "WithHelmet":     (0, 200, 0),     # green
        "WithoutHelmet":  (0, 0, 255),     # red
        "TripleRiding":   (255, 100, 0),   # orange
        "IllegalParking": (128, 0, 255),   # purple
    })

    violation_text_colour: Tuple[int, int, int] = (255, 255, 255)
    font_scale: float = 0.55
    thickness: int = 2
    parking_roi_colour: Tuple[int, int, int] = (255, 0, 128)


# ---------------------------------------------------------------------------
# Master config singleton
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    """Aggregate of all sub-configurations – instantiate once and pass around."""

    video: VideoConfig = field(default_factory=VideoConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    classes: ClassConfig = field(default_factory=ClassConfig)
    violation: ViolationConfig = field(default_factory=ViolationConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


# Module-level default instance (used when no explicit config is supplied)
DEFAULT_CONFIG: AppConfig = AppConfig()
