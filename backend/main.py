"""
main.py
-------
FastAPI application factory for the Gridlock traffic violation platform.

Architecture
~~~~~~~~~~~~

.. code-block:: text

    ┌─────────────────────────────────────────────────────────┐
    │  FastAPI (asyncio event loop)                           │
    │                                                         │
    │  app.state.pipeline  →  PipelineState                  │
    │  app.state.broadcaster → WebSocketBroadcaster          │
    │  app.state.mjpeg_queue → asyncio.Queue[bytes]          │
    │                                ▲                        │
    │                      run_coroutine_threadsafe           │
    │                                │                        │
    │  ┌─────────────────────────────┴──────────────────┐    │
    │  │  VideoProcessor (OS threads)                    │    │
    │  │  ├── producer thread  (VideoCapture)            │    │
    │  │  └── consumer thread  (YOLO → OCR → Violation) │    │
    │  └────────────────────────────────────────────────┘    │
    └─────────────────────────────────────────────────────────┘

No mutable module-level globals.  All shared state is stored in
``app.state`` and accessed via FastAPI dependency injection.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router as api_router
from backend.api.websocket import WebSocketBroadcaster, router as ws_router
from backend.core.config import AppConfig, DEFAULT_CONFIG, LOG_FORMAT, LOG_LEVEL
from backend.core.state_manager import FrameState, ViolationEvent
from backend.schemas import WSEventType
from backend.services.video_processor import FrameResult, VideoProcessor

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MJPEG queue capacity (latest-frame semantics – old frames dropped)
# ---------------------------------------------------------------------------
_MJPEG_QUEUE_MAXSIZE = 2


# ---------------------------------------------------------------------------
# PipelineState  –  the central bridge between threads and asyncio
# ---------------------------------------------------------------------------

class PipelineState:
    """
    Owns the ``VideoProcessor`` and all cross-thread communication artefacts.

    This class is **not** a global.  A single instance is stored in
    ``app.state.pipeline`` and injected into endpoints via ``request.app.state``.

    Thread safety
    ~~~~~~~~~~~~~
    * ``_violations`` is protected by ``_lock``.
    * ``_metrics_*`` counters use ``_lock``.
    * All asyncio interactions go through ``run_coroutine_threadsafe``.
    """

    def __init__(
        self,
        app_config: AppConfig,
        broadcaster: WebSocketBroadcaster,
        mjpeg_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.app_config = app_config
        self._broadcaster = broadcaster
        self._mjpeg_queue = mjpeg_queue
        self._loop = loop

        # Processor (created fresh on each start())
        self._processor: Optional[VideoProcessor] = None
        self._processor_thread: Optional[threading.Thread] = None

        # State
        self.is_running: bool = False
        self._lock = threading.RLock()

        # Metrics
        self._start_time: Optional[float] = None
        self._frames_processed: int = 0
        self._frame_timestamps: Deque[float] = deque(maxlen=60)  # rolling FPS window
        self._total_violations: int = 0
        self._ocr_reads: int = 0
        self._seen_track_ids: set[int] = set()

        # Violation history (capped at 10 000 entries)
        self._violations: Deque[ViolationEvent] = deque(maxlen=10_000)

        # Current frame state (latest snapshot from consumer thread)
        self._current_frame: FrameState = FrameState(
            frame_id=0,
            timestamp=_utcnow(),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, source: str | int, loop: asyncio.AbstractEventLoop) -> None:
        """
        Instantiate a fresh ``VideoProcessor`` and launch it on a daemon thread.

        This method is called from an ``asyncio.run_in_executor`` so it runs
        on a thread-pool worker, keeping the event loop unblocked.
        """
        with self._lock:
            if self.is_running:
                logger.warning("PipelineState.start() called while already running")
                return

            # Reset counters
            self._start_time = time.monotonic()
            self._frames_processed = 0
            self._frame_timestamps.clear()
            self._total_violations = 0
            self._ocr_reads = 0
            self._seen_track_ids.clear()
            self._violations.clear()
            self._loop = loop

            self._processor = VideoProcessor(
                config=self.app_config,
                result_callback=self._on_frame_result,
            )

            # Run VideoProcessor.start() + join() on a dedicated daemon thread
            # so that the asyncio event loop is never blocked.
            self._processor_thread = threading.Thread(
                target=self._run_processor,
                args=(source,),
                name="pipeline-runner",
                daemon=True,
            )
            self.is_running = True

        self._processor_thread.start()
        logger.info("PipelineState started | source=%s", source)

    def stop(self) -> None:
        """
        Signal the processor to stop.  Blocks until the processor thread exits
        (called from a thread-pool worker, never from the event loop).
        """
        with self._lock:
            if not self.is_running:
                return
            processor = self._processor

        if processor:
            processor.stop()

        if self._processor_thread and self._processor_thread.is_alive():
            self._processor_thread.join(timeout=10.0)

        with self._lock:
            self.is_running = False

        logger.info("PipelineState stopped")

    def _run_processor(self, source: str | int) -> None:
        """
        Target for the pipeline-runner thread.

        Calls ``VideoProcessor.start()`` (non-blocking) and then ``join()``
        (blocking until source is exhausted or ``stop()`` is called).
        """
        try:
            if self._processor:
                self._processor.start(source)
                self._processor.join()
        except Exception as exc:
            logger.error("Pipeline runner error: %s", exc, exc_info=True)
        finally:
            with self._lock:
                self.is_running = False
            logger.info("Pipeline runner thread exited")

            # Notify WebSocket clients that the engine has stopped
            self._broadcaster.broadcast_from_thread(
                self._broadcaster.make_event(WSEventType.ENGINE_STOPPED, {}),
                self._loop,
            )

    # ------------------------------------------------------------------
    # Frame result callback  (called from VideoProcessor consumer thread)
    # ------------------------------------------------------------------

    def _on_frame_result(self, result: FrameResult) -> None:
        """
        Process a completed frame from the VideoProcessor consumer thread.

        Responsibilities
        ~~~~~~~~~~~~~~~~
        1. Update metrics counters.
        2. Persist new violations.
        3. Push WebSocket events (violation, ocr_completed, vehicle_tracked).
        4. Encode frame as JPEG and push to MJPEG queue.
        5. Update the current frame state snapshot.
        """
        now_ts = time.monotonic()

        with self._lock:
            self._frames_processed += 1
            self._frame_timestamps.append(now_ts)

            # Update current frame state
            self._current_frame = FrameState(
                frame_id=result.frame_id,
                timestamp=result.timestamp,
                detections=list(result.detections),
                violations=list(result.violations),
            )

            # Accumulate violations
            for viol in result.violations:
                self._violations.append(viol)
            self._total_violations += len(result.violations)

            # OCR reads = total entries in state manager cache
            if self._processor:
                self._ocr_reads = len(
                    self._processor.state_manager._ocr_cache
                )

            # New track IDs
            new_tracks: list[int] = []
            for det in result.detections:
                if det.track_id is not None and det.track_id not in self._seen_track_ids:
                    self._seen_track_ids.add(det.track_id)
                    new_tracks.append(det.track_id)

        loop = self._loop
        if loop.is_closed():
            return

        # --- WebSocket: new violations --------------------------------
        for viol in result.violations:
            self._broadcaster.broadcast_from_thread(
                self._broadcaster.make_event(
                    WSEventType.VIOLATION,
                    {
                        "violation_type": viol.violation_type,
                        "track_id": viol.track_id,
                        "plate_text": viol.plate_text,
                        "frame_id": viol.frame_id,
                        "timestamp": viol.timestamp,
                        "confidence": viol.confidence,
                        "bbox": asdict(viol.bbox),
                        "metadata": viol.metadata,
                    },
                ),
                loop,
            )

        # --- WebSocket: OCR completions (check for newly cached plates)
        for det in result.detections:
            if det.plate_text and det.track_id is not None:
                self._broadcaster.broadcast_from_thread(
                    self._broadcaster.make_event(
                        WSEventType.OCR_COMPLETED,
                        {
                            "track_id": det.track_id,
                            "plate_text": det.plate_text,
                            "confidence": det.plate_confidence,
                        },
                    ),
                    loop,
                )

        # --- WebSocket: new vehicle tracks -----------------------------
        for tid in new_tracks:
            self._broadcaster.broadcast_from_thread(
                self._broadcaster.make_event(
                    WSEventType.VEHICLE_TRACKED,
                    {"track_id": tid, "frame_id": result.frame_id},
                ),
                loop,
            )

        # --- WebSocket: lightweight frame heartbeat (every 30 frames) --
        if result.frame_id % 30 == 0:
            self._broadcaster.broadcast_from_thread(
                self._broadcaster.make_event(
                    WSEventType.FRAME_PROCESSED,
                    {
                        "frame_id": result.frame_id,
                        "fps": self._rolling_fps(),
                        "total_violations": self._total_violations,
                        "vehicles_tracked": len(self._seen_track_ids),
                        "detections_count": len(result.detections),
                    },
                ),
                loop,
            )

        # --- MJPEG: encode frame to JPEG and push to queue ------------
        self._push_mjpeg_frame(result.annotated_frame, loop)

    # ------------------------------------------------------------------
    # MJPEG helpers
    # ------------------------------------------------------------------

    def _push_mjpeg_frame(
        self,
        frame: np.ndarray,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Encode *frame* as JPEG and schedule it into the asyncio MJPEG queue."""
        try:
            ok, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
            )
            if not ok:
                return
            jpeg_bytes = buf.tobytes()
        except Exception as exc:
            logger.debug("MJPEG encode failed: %s", exc)
            return

        async def _put():
            # Drop the oldest frame if the queue is full (latest-frame semantics)
            if self._mjpeg_queue.full():
                try:
                    self._mjpeg_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await self._mjpeg_queue.put(jpeg_bytes)

        asyncio.run_coroutine_threadsafe(_put(), loop)

    # ------------------------------------------------------------------
    # Read-only accessors  (called from async routes)
    # ------------------------------------------------------------------

    def current_frame_state(self) -> FrameState:
        """Return a snapshot of the latest processed frame."""
        with self._lock:
            return self._current_frame

    def update_detection_config(self, **kwargs) -> None:
        """
        Hot-reload detection parameters without restarting the pipeline.

        Supported keys: ``confidence_threshold``, ``frame_skip``.
        Changes take effect on the next processed frame.
        """
        with self._lock:
            cfg = self.app_config
            if kwargs.get("confidence_threshold") is not None:
                cfg.detection.confidence_threshold = kwargs["confidence_threshold"]
                proc_det = getattr(getattr(self, "_processor", None), "_detector", None)
                if proc_det is not None:
                    proc_det._cfg.confidence_threshold = kwargs["confidence_threshold"]
            if kwargs.get("frame_skip") is not None:
                cfg.video.frame_skip = kwargs["frame_skip"]
        logger.info("Detection config updated: %s", kwargs)

    def violation_history(self) -> List[ViolationEvent]:
        """Return all accumulated violations as a list (oldest first)."""
        with self._lock:
            return list(self._violations)

    def metrics(self) -> Dict[str, Any]:
        """Return a JSON-serialisable metrics dict."""
        with self._lock:
            fps = self._rolling_fps()
            elapsed = (
                time.monotonic() - self._start_time
                if self._start_time
                else 0.0
            )
            return {
                "fps": round(fps, 2),
                "total_violations": self._total_violations,
                "vehicles_tracked": len(self._seen_track_ids),
                "ocr_reads": self._ocr_reads,
                "frames_processed": self._frames_processed,
                "uptime_seconds": round(elapsed, 1),
                "is_running": self.is_running,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rolling_fps(self) -> float:
        """Calculate rolling FPS from the last 60 frame timestamps."""
        if len(self._frame_timestamps) < 2:
            return 0.0
        window = list(self._frame_timestamps)
        elapsed = window[-1] - window[0]
        return len(window) / elapsed if elapsed > 0 else 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Async context manager that manages the full application lifecycle.

    Startup
    ~~~~~~~
    1. Capture the running event loop (needed for thread→asyncio bridge).
    2. Create the ``WebSocketBroadcaster`` and ``asyncio.Queue`` for MJPEG.
    3. Create the ``PipelineState`` singleton and store in ``app.state``.

    Shutdown
    ~~~~~~~~
    1. Stop the inference pipeline (if running).
    2. Log final metrics.
    """
    logger.info("Gridlock API starting up …")

    loop = asyncio.get_running_loop()

    # Shared objects stored on app.state (no module globals)
    broadcaster = WebSocketBroadcaster()
    mjpeg_queue: asyncio.Queue = asyncio.Queue(maxsize=_MJPEG_QUEUE_MAXSIZE)

    pipeline = PipelineState(
        app_config=AppConfig(),       # fresh config per run
        broadcaster=broadcaster,
        mjpeg_queue=mjpeg_queue,
        loop=loop,
    )

    app.state.broadcaster = broadcaster
    app.state.mjpeg_queue = mjpeg_queue
    app.state.pipeline = pipeline
    app.state.is_running = False

    logger.info("Application state initialised.  Ready to accept requests.")
    yield  # ← application serves requests here

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("Gridlock API shutting down …")

    if pipeline.is_running:
        logger.info("Stopping inference pipeline …")
        loop_exec = asyncio.get_running_loop()
        await loop_exec.run_in_executor(None, pipeline.stop)

    logger.info("Shutdown complete.")


def create_app(config: Optional[AppConfig] = None) -> FastAPI:
    """
    Application factory.

    Parameters
    ----------
    config:
        Optional ``AppConfig`` override.  Defaults to ``DEFAULT_CONFIG``.

    Returns
    -------
    FastAPI
        Fully configured FastAPI application instance.
    """
    app = FastAPI(
        title="Gridlock – Traffic Violation Detection API",
        description=(
            "Real-time traffic violation detection powered by YOLOv8, "
            "EasyOCR, and ByteTrack.  Provides REST endpoints and a "
            "WebSocket push stream for live monitoring."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # CORS – allow React dev server and production origins
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",   # React CRA dev server
            "http://localhost:5173",   # Vite dev server
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            # Add production origin(s) here, e.g. "https://gridlock.example.com"
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(api_router)   # REST  →  /api/*  +  /health
    app.include_router(ws_router)    # WS    →  /ws/live

    logger.info("FastAPI application created")
    return app


# ---------------------------------------------------------------------------
# ASGI application instance (used by uvicorn / gunicorn)
# ---------------------------------------------------------------------------
app = create_app()


# ---------------------------------------------------------------------------
# Development entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,          # disable reload – it conflicts with CV threads
        log_level="info",
        workers=1,             # must be 1: VideoProcessor is not fork-safe
    )
