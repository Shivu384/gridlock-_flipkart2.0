"""
routes.py
---------
All REST API endpoints for the Gridlock traffic violation platform.

Endpoints
~~~~~~~~~
POST  /api/start       – Start inference on a video source.
POST  /api/stop        – Stop the running pipeline.
GET   /api/state       – Current detection snapshot.
GET   /api/violations  – Paginated violation history.
GET   /api/metrics     – Live performance statistics.
GET   /api/stream      – MJPEG annotated video stream.
GET   /health          – Liveness probe.

Dependency injection
~~~~~~~~~~~~~~~~~~~~
All endpoints access shared state via ``request.app.state`` rather than
module-level globals.  The ``get_pipeline_state`` dependency helper
provides typed access to the ``PipelineState`` singleton.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import deque
from typing import AsyncGenerator, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from backend.schemas import (
    AnalyticsResponse,
    BoundingBoxSchema,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    DetectionSchema,
    EvidenceSchema,
    HealthResponse,
    HeatmapPoint,
    HeatmapResponse,
    MetricsResponse,
    PlateCount,
    StartRequest,
    StartResponse,
    StopResponse,
    SystemStateSchema,
    UploadResponse,
    ViolationsResponse,
    ViolationSchema,
    WSEventType,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["api"])


# ---------------------------------------------------------------------------
# Dependency helper
# ---------------------------------------------------------------------------

def get_app_state(request: Request):
    """
    FastAPI dependency that returns the ``PipelineState`` singleton stored
    in ``app.state``.  Raises ``503`` if the app has not finished starting.
    """
    state = getattr(request.app, "state", None)
    if state is None or not hasattr(state, "pipeline"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application state not initialised.",
        )
    return state


# ---------------------------------------------------------------------------
# Helper: convert internal dataclass → Pydantic schema
# ---------------------------------------------------------------------------

def _violation_to_schema(v) -> ViolationSchema:
    """Convert a ``ViolationEvent`` dataclass to a ``ViolationSchema``."""
    return ViolationSchema(
        violation_type=v.violation_type,
        frame_id=v.frame_id,
        timestamp=v.timestamp,
        track_id=v.track_id,
        plate_text=v.plate_text,
        bbox=BoundingBoxSchema(
            x1=v.bbox.x1,
            y1=v.bbox.y1,
            x2=v.bbox.x2,
            y2=v.bbox.y2,
        ),
        confidence=v.confidence,
        metadata=v.metadata,
    )


def _detection_to_schema(d) -> DetectionSchema:
    """Convert a ``DetectionRecord`` dataclass to a ``DetectionSchema``."""
    return DetectionSchema(
        class_id=d.class_id,
        class_name=d.class_name,
        confidence=d.confidence,
        bbox=BoundingBoxSchema(
            x1=d.bbox.x1,
            y1=d.bbox.y1,
            x2=d.bbox.x2,
            y2=d.bbox.y2,
        ),
        track_id=d.track_id,
        plate_text=d.plate_text,
        plate_confidence=d.plate_confidence,
    )


# ---------------------------------------------------------------------------
# POST /api/start
# ---------------------------------------------------------------------------

@router.post(
    "/api/start",
    response_model=StartResponse,
    status_code=status.HTTP_200_OK,
    summary="Start the inference pipeline",
)
async def start_inference(
    body: StartRequest,
    request: Request,
    app_state=Depends(get_app_state),
) -> StartResponse:
    """
    Start the YOLOv8 detection pipeline on the given video source.

    If the pipeline is already running, the request is rejected with ``409``.

    The pipeline runs in a background **daemon** thread so that this endpoint
    returns immediately.
    """
    pipeline = app_state.pipeline

    if pipeline.is_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline is already running.  POST /api/stop first.",
        )

    # Apply per-request overrides to the config
    cfg = pipeline.app_config
    if body.frame_skip is not None:
        cfg.video.frame_skip = body.frame_skip
    if body.device is not None:
        cfg.detection.device = body.device

    # Resolve source (integer if digit string)
    source: str | int = body.video_path
    try:
        source = int(body.video_path)
    except ValueError:
        pass

    # Launch in background asyncio task (which internally spawns threads)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, pipeline.start, source, loop)

    # Notify WebSocket clients
    app_state.broadcaster.broadcast_from_thread(
        app_state.broadcaster.make_event(
            WSEventType.ENGINE_STARTED,
            {"source": str(source), "frame_skip": cfg.video.frame_skip},
        ),
        loop,
    )

    logger.info("Pipeline started via API | source=%s", source)
    return StartResponse(status="started", message=f"Processing '{source}'")


# ---------------------------------------------------------------------------
# POST /api/stop
# ---------------------------------------------------------------------------

@router.post(
    "/api/stop",
    response_model=StopResponse,
    summary="Stop the running inference pipeline",
)
async def stop_inference(
    request: Request,
    app_state=Depends(get_app_state),
) -> StopResponse:
    """Gracefully stop the pipeline."""
    pipeline = app_state.pipeline

    if not pipeline.is_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline is not running.",
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, pipeline.stop)

    app_state.broadcaster.broadcast_from_thread(
        app_state.broadcaster.make_event(WSEventType.ENGINE_STOPPED, {}),
        loop,
    )

    logger.info("Pipeline stopped via API")
    return StopResponse(status="stopped")


# ---------------------------------------------------------------------------
# GET /api/state
# ---------------------------------------------------------------------------

@router.get(
    "/api/state",
    response_model=SystemStateSchema,
    summary="Current detection snapshot",
)
async def get_state(
    app_state=Depends(get_app_state),
) -> SystemStateSchema:
    """
    Return the most recently processed frame's detections and violations.

    The response is a snapshot of ``StateManager.current_frame()`` and
    is updated on every processed frame (~10 FPS).
    """
    pipeline = app_state.pipeline
    frame = pipeline.current_frame_state()

    return SystemStateSchema(
        frame_id=frame.frame_id,
        timestamp=frame.timestamp,
        detections=[_detection_to_schema(d) for d in frame.detections],
        violations=[_violation_to_schema(v) for v in frame.violations],
    )


# ---------------------------------------------------------------------------
# GET /api/violations
# ---------------------------------------------------------------------------

@router.get(
    "/api/violations",
    response_model=ViolationsResponse,
    summary="Violation history",
)
async def get_violations(
    app_state=Depends(get_app_state),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    violation_type: Optional[str] = Query(
        None, description="Filter by type: WithoutHelmet | TripleRiding | IllegalParking"
    ),
) -> ViolationsResponse:
    """
    Return paginated violation history accumulated since the pipeline started.

    Violations are returned newest-first.
    """
    pipeline = app_state.pipeline
    history = pipeline.violation_history()

    if violation_type:
        history = [v for v in history if v.violation_type == violation_type]

    # Newest first
    history = list(reversed(history))
    total = len(history)
    start = (page - 1) * page_size
    page_items = history[start : start + page_size]

    return ViolationsResponse(
        violations=[_violation_to_schema(v) for v in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /api/metrics
# ---------------------------------------------------------------------------

@router.get(
    "/api/metrics",
    response_model=MetricsResponse,
    summary="Live performance and detection metrics",
)
async def get_metrics(
    app_state=Depends(get_app_state),
) -> MetricsResponse:
    """
    Return live performance counters:

    * ``fps`` – rolling average of processed frames per second.
    * ``total_violations`` – cumulative violation count since start.
    * ``vehicles_tracked`` – number of active ByteTrack IDs.
    * ``ocr_reads`` – number of completed OCR cache entries.
    * ``frames_processed`` – total processed frame count.
    * ``uptime_seconds`` – seconds elapsed since pipeline start.
    * ``is_running`` – whether the pipeline is currently active.
    """
    pipeline = app_state.pipeline
    metrics = pipeline.metrics()
    return MetricsResponse(**metrics)


# ---------------------------------------------------------------------------
# GET /api/stream  (MJPEG)
# ---------------------------------------------------------------------------

@router.get(
    "/api/stream",
    summary="MJPEG annotated video stream",
    response_class=StreamingResponse,
)
async def mjpeg_stream(
    request: Request,
    app_state=Depends(get_app_state),
):
    """
    Serve the annotated video as an **MJPEG** stream.

    Compatible with ``<img src="/api/stream">`` in any browser or HTML page.

    The stream emits the latest annotated frame at the pipeline's effective FPS
    (approx. 10 fps for a 720p T4-GPU setup with frame_skip=3).
    """
    pipeline = app_state.pipeline

    async def generate() -> AsyncGenerator[bytes, None]:
        """Pull JPEG bytes from the pipeline's frame buffer and yield MJPEG chunks."""
        frame_queue: asyncio.Queue = app_state.mjpeg_queue

        while True:
            # Respect client disconnect
            if await request.is_disconnected():
                logger.debug("MJPEG: client disconnected")
                break
            try:
                jpeg_bytes: bytes = await asyncio.wait_for(
                    frame_queue.get(), timeout=2.0
                )
            except asyncio.TimeoutError:
                # No new frame yet – yield an empty chunk to keep connection alive
                continue
            except asyncio.CancelledError:
                break

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n"
                b"\r\n" + jpeg_bytes + b"\r\n"
            )

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# POST /api/upload  (on-demand single-image analysis)
# ---------------------------------------------------------------------------

_ANNOT_COLORS = {
    "WithHelmet":    (34,  197, 94),
    "WithoutHelmet": (239, 68,  68),
    "TripleRiding":  (249, 115, 22),
    "Plate":         (250, 204, 21),
}


def _annotate_upload(frame: np.ndarray, detections) -> np.ndarray:
    """Draw bounding boxes and labels onto a copy of *frame*."""
    out = frame.copy()
    for det in detections:
        color = _ANNOT_COLORS.get(det.class_name, (148, 163, 184))
        cv2.rectangle(out, (det.bbox.x1, det.bbox.y1), (det.bbox.x2, det.bbox.y2), color, 2)
        label = f"{det.class_name} {det.confidence:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (det.bbox.x1, det.bbox.y1 - th - 6), (det.bbox.x1 + tw + 4, det.bbox.y1), color, -1)
        cv2.putText(out, label, (det.bbox.x1 + 2, det.bbox.y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return out


def _get_analysis_detector(app_state):
    """Return a lazily-initialised standalone Detector for image uploads."""
    if not hasattr(app_state, "analysis_detector") or app_state.analysis_detector is None:
        from backend.services.detector import Detector  # local import avoids circular
        app_state.analysis_detector = Detector(app_state.pipeline.app_config)
    return app_state.analysis_detector


@router.post(
    "/api/upload",
    response_model=UploadResponse,
    summary="Run on-demand YOLO detection on an uploaded image",
)
async def upload_image(
    file: UploadFile = File(..., description="JPEG / PNG image to analyse"),
    app_state=Depends(get_app_state),
) -> UploadResponse:
    """
    Accept an image file, run YOLOv8 detection, and return the annotated
    image (base-64 JPEG) together with all detection records.
    """
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Could not decode image. Ensure it is a valid JPEG or PNG.")

    h, w = frame.shape[:2]

    detector = await asyncio.get_running_loop().run_in_executor(
        None, _get_analysis_detector, app_state
    )
    detections = await asyncio.get_running_loop().run_in_executor(
        None, detector.detect, frame, False
    )

    annotated = _annotate_upload(frame, detections)
    _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 88])
    img_b64 = base64.b64encode(buf.tobytes()).decode()

    return UploadResponse(
        annotated_image_b64=img_b64,
        detections=[_detection_to_schema(d) for d in detections],
        width=w,
        height=h,
        detection_count=len(detections),
    )


# ---------------------------------------------------------------------------
# PATCH /api/config  (hot-reload detection parameters)
# ---------------------------------------------------------------------------

@router.patch(
    "/api/config",
    response_model=ConfigUpdateResponse,
    summary="Update detection config without restarting the pipeline",
)
async def update_config(
    body: ConfigUpdateRequest,
    app_state=Depends(get_app_state),
) -> ConfigUpdateResponse:
    """
    Adjust ``confidence_threshold`` and/or ``frame_skip`` on the fly.
    Changes are applied to the running pipeline immediately.
    """
    pipeline = app_state.pipeline
    pipeline.update_detection_config(
        confidence_threshold=body.confidence_threshold,
        frame_skip=body.frame_skip,
    )
    cfg = pipeline.app_config
    return ConfigUpdateResponse(
        status="updated",
        confidence_threshold=cfg.detection.confidence_threshold,
        frame_skip=cfg.video.frame_skip,
    )


# ---------------------------------------------------------------------------
# GET /api/analytics
# ---------------------------------------------------------------------------

@router.get(
    "/api/analytics",
    response_model=AnalyticsResponse,
    summary="Aggregated violation analytics",
)
async def get_analytics(
    app_state=Depends(get_app_state),
) -> AnalyticsResponse:
    """
    Return aggregated statistics over all violations collected since the
    pipeline started: counts by type, hourly breakdown, top plates, and
    current performance metrics.
    """
    pipeline = app_state.pipeline
    history = pipeline.violation_history()
    metrics = pipeline.metrics()

    type_breakdown: dict[str, int] = {}
    hourly: dict[str, int] = {}
    plate_counts: dict[str, int] = {}

    for v in history:
        type_breakdown[v.violation_type] = type_breakdown.get(v.violation_type, 0) + 1
        hour_key = v.timestamp[:13]  # "2025-01-01T12"
        hourly[hour_key] = hourly.get(hour_key, 0) + 1
        if v.plate_text:
            plate_counts[v.plate_text] = plate_counts.get(v.plate_text, 0) + 1

    top_plates = sorted(plate_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    vehicles = max(metrics["vehicles_tracked"], 1)

    return AnalyticsResponse(
        type_breakdown=type_breakdown,
        hourly_violations=hourly,
        top_plates=[PlateCount(plate=p, count=c) for p, c in top_plates],
        total_violations=metrics["total_violations"],
        total_vehicles=metrics["vehicles_tracked"],
        avg_fps=metrics["fps"],
        uptime_seconds=metrics["uptime_seconds"],
        ocr_success_rate=round(metrics["ocr_reads"] / vehicles * 100, 1),
    )


# ---------------------------------------------------------------------------
# GET /api/heatmap
# ---------------------------------------------------------------------------

@router.get(
    "/api/heatmap",
    response_model=HeatmapResponse,
    summary="Violation bbox centres for heatmap rendering",
)
async def get_heatmap(
    app_state=Depends(get_app_state),
) -> HeatmapResponse:
    """
    Return the centre-point of every recorded violation bounding box.
    The frontend uses these points to render a canvas heatmap.
    """
    pipeline = app_state.pipeline
    history = pipeline.violation_history()

    points = [
        HeatmapPoint(
            x=(v.bbox.x1 + v.bbox.x2) // 2,
            y=(v.bbox.y1 + v.bbox.y2) // 2,
            violation_type=v.violation_type,
        )
        for v in history
    ]

    return HeatmapResponse(points=points, total=len(points))


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    tags=["health"],
)
async def health_check(
    app_state=Depends(get_app_state),
) -> HealthResponse:
    """
    Liveness probe used by load-balancers, Kubernetes, and Docker health checks.

    Always returns ``200 OK`` while the process is alive.
    """
    return HealthResponse(
        status="ok",
        version="1.0.0",
        engine_running=app_state.pipeline.is_running,
    )
