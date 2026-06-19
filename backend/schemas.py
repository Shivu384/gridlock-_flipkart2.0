"""
schemas.py
----------
Pydantic v2 models for all API request/response contracts.

All models use ``model_config = ConfigDict(from_attributes=True)`` so they
can be populated directly from the internal dataclass objects defined in
``backend.core.state_manager``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Shared geometry
# ---------------------------------------------------------------------------

class BoundingBoxSchema(BaseModel):
    """Pixel-space bounding box returned in detections and violations."""

    model_config = ConfigDict(from_attributes=True)

    x1: int = Field(..., description="Left edge (pixels)")
    y1: int = Field(..., description="Top edge (pixels)")
    x2: int = Field(..., description="Right edge (pixels)")
    y2: int = Field(..., description="Bottom edge (pixels)")

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

class DetectionSchema(BaseModel):
    """Single object detection within a frame."""

    model_config = ConfigDict(from_attributes=True)

    class_id: int = Field(..., description="YOLO class index")
    class_name: str = Field(..., description="Human-readable class label")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence")
    bbox: BoundingBoxSchema
    track_id: Optional[int] = Field(None, description="ByteTrack persistent ID")
    plate_text: Optional[str] = Field(None, description="OCR-read licence plate text")
    plate_confidence: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="OCR confidence score"
    )


# ---------------------------------------------------------------------------
# Violation
# ---------------------------------------------------------------------------

class ViolationSchema(BaseModel):
    """A confirmed traffic violation event."""

    model_config = ConfigDict(from_attributes=True)

    violation_type: str = Field(
        ...,
        description="WithoutHelmet | TripleRiding | IllegalParking",
    )
    frame_id: int = Field(..., description="Processed frame index")
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp")
    track_id: Optional[int] = Field(None, description="ByteTrack ID of the offender")
    plate_text: Optional[str] = Field(None, description="Licence plate (if read)")
    bbox: BoundingBoxSchema
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceSchema(BaseModel):
    """
    Enriched violation record with optional thumbnail (base-64 JPEG).

    The thumbnail is omitted in list responses to reduce payload size.
    """

    violation: ViolationSchema
    frame_id: int
    timestamp: str
    thumbnail_b64: Optional[str] = Field(
        None, description="Base-64 encoded JPEG crop around the violating vehicle"
    )


# ---------------------------------------------------------------------------
# System state
# ---------------------------------------------------------------------------

class SystemStateSchema(BaseModel):
    """
    Current pipeline state snapshot – mirrors ``StateManager.to_dict()``
    output but with typed Pydantic fields.
    """

    frame_id: int = Field(..., description="Most recently processed frame index")
    timestamp: str = Field(..., description="Timestamp of the last processed frame")
    detections: List[DetectionSchema] = Field(default_factory=list)
    violations: List[ViolationSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class MetricsResponse(BaseModel):
    """Live performance and detection statistics."""

    fps: float = Field(..., description="Rolling processed-FPS")
    total_violations: int = Field(..., description="Cumulative violations since start")
    vehicles_tracked: int = Field(..., description="Active ByteTrack IDs")
    ocr_reads: int = Field(..., description="Completed OCR cache entries")
    frames_processed: int = Field(..., description="Total frames through the pipeline")
    uptime_seconds: float = Field(..., description="Seconds since engine started")
    is_running: bool = Field(..., description="Whether the pipeline is active")


# ---------------------------------------------------------------------------
# Request / Response bodies
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    """Body for ``POST /api/start``."""

    video_path: str = Field(
        ...,
        description="Absolute path to a video file, RTSP URL, or '0'–'9' for a webcam.",
    )
    frame_skip: Optional[int] = Field(
        None, ge=1, le=30, description="Override default frame-skip (default 3)"
    )
    device: Optional[str] = Field(
        None, description="'cuda' or 'cpu' – overrides config default"
    )


class StartResponse(BaseModel):
    """Response for ``POST /api/start``."""

    status: str
    message: str = ""


class StopResponse(BaseModel):
    """Response for ``POST /api/stop``."""

    status: str


class ViolationsResponse(BaseModel):
    """Paginated violation history."""

    violations: List[ViolationSchema]
    total: int
    page: int = 1
    page_size: int


# ---------------------------------------------------------------------------
# WebSocket event envelope
# ---------------------------------------------------------------------------

class WSEventType:
    """String constants for WebSocket event ``type`` fields."""

    VIOLATION = "violation"
    OCR_COMPLETED = "ocr_completed"
    VEHICLE_TRACKED = "vehicle_tracked"
    FRAME_PROCESSED = "frame_processed"
    ENGINE_STARTED = "engine_started"
    ENGINE_STOPPED = "engine_stopped"
    METRICS = "metrics"
    ERROR = "error"


class WSEvent(BaseModel):
    """Generic WebSocket push event envelope."""

    type: str = Field(..., description="Event type constant from WSEventType")
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field("", description="ISO-8601 UTC timestamp")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """``GET /health`` response."""

    status: str = "ok"
    version: str = "1.0.0"
    engine_running: bool = False


# ---------------------------------------------------------------------------
# Image upload / on-demand analysis
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    """Response for ``POST /api/upload``."""

    annotated_image_b64: str = Field(..., description="Base-64 JPEG of the annotated frame")
    detections: List[DetectionSchema]
    width: int
    height: int
    detection_count: int


# ---------------------------------------------------------------------------
# Config update
# ---------------------------------------------------------------------------

class ConfigUpdateRequest(BaseModel):
    """Body for ``PATCH /api/config``."""

    confidence_threshold: Optional[float] = Field(None, ge=0.01, le=1.0)
    frame_skip: Optional[int] = Field(None, ge=1, le=30)


class ConfigUpdateResponse(BaseModel):
    """Response for ``PATCH /api/config``."""

    status: str
    confidence_threshold: float
    frame_skip: int


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class PlateCount(BaseModel):
    plate: str
    count: int


class AnalyticsResponse(BaseModel):
    """Response for ``GET /api/analytics``."""

    type_breakdown: Dict[str, int] = Field(description="Violation count per type")
    hourly_violations: Dict[str, int] = Field(description="ISO-hour → count")
    top_plates: List[PlateCount]
    total_violations: int
    total_vehicles: int
    avg_fps: float
    uptime_seconds: float
    ocr_success_rate: float


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------

class HeatmapPoint(BaseModel):
    x: int
    y: int
    violation_type: str


class HeatmapResponse(BaseModel):
    """Response for ``GET /api/heatmap``."""

    points: List[HeatmapPoint]
    total: int
