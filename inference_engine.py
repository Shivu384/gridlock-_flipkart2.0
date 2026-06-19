"""
inference_engine.py
-------------------
Top-level façade for the Gridlock traffic violation detection system.

This is the **single entry-point** for external consumers (REST APIs,
CLI scripts, Jupyter notebooks, integration tests, etc.).

Example usage
-------------
CLI (file):

.. code-block:: bash

    python inference_engine.py --source traffic.mp4 --show

Python API:

.. code-block:: python

    from inference_engine import InferenceEngine, InferenceConfig
    from backend.core.config import AppConfig

    engine = InferenceEngine(AppConfig())
    engine.run(source="traffic.mp4", show=False, output_path="out.mp4")

Design notes
~~~~~~~~~~~~
* ``InferenceEngine`` owns no mutable state itself – it delegates entirely
  to ``VideoProcessor`` which contains all threaded state.
* The ``__main__`` block provides a self-contained CLI entry-point for quick
  smoke-testing without writing a separate script.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import cv2
import numpy as np

from backend.core.config import AppConfig, DEFAULT_CONFIG, LOG_FORMAT, LOG_LEVEL
from backend.services.video_processor import FrameResult, VideoProcessor

# ---------------------------------------------------------------------------
# Configure root logger once (callers can override after import)
# ---------------------------------------------------------------------------
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# InferenceConfig
# ---------------------------------------------------------------------------

@dataclass
class InferenceConfig:
    """
    Runtime parameters for a single inference run.

    These are **not** model or detection parameters (those live in
    ``AppConfig``); they govern how results are consumed.
    """

    show: bool = False
    """Display annotated frames in a cv2 window."""

    output_path: Optional[str] = None
    """If set, write annotated video to this file path."""

    json_output_path: Optional[str] = None
    """If set, append JSON state dicts (one per frame) to this file."""

    max_frames: Optional[int] = None
    """Stop after this many *processed* frames (None = run to end)."""

    display_scale: float = 1.0
    """Scale factor applied to frames before displaying (does not affect output)."""


# ---------------------------------------------------------------------------
# InferenceEngine
# ---------------------------------------------------------------------------

class InferenceEngine:
    """
    Façade that initialises and coordinates the full pipeline.

    Parameters
    ----------
    app_config:
        Master configuration.  Defaults to ``DEFAULT_CONFIG`` (all defaults).
    """

    def __init__(self, app_config: AppConfig = DEFAULT_CONFIG) -> None:
        self._app_cfg: AppConfig = app_config
        self._processor: Optional[VideoProcessor] = None
        self._running: bool = False

        # Accumulated output for the current run
        self._all_results: List[FrameResult] = []
        self._json_lines: List[dict] = []

        logger.info("InferenceEngine initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        source: str | int,
        inference_config: Optional[InferenceConfig] = None,
        extra_callback: Optional[Callable[[FrameResult], None]] = None,
    ) -> List[FrameResult]:
        """
        Execute the full detection pipeline on *source*.

        This method **blocks** until the video is exhausted or ``stop()``
        is called.

        Parameters
        ----------
        source:
            Video file path, RTSP URL, or integer device index.
        inference_config:
            Runtime output parameters.
        extra_callback:
            Optional additional per-frame callback (e.g. for streaming to
            a WebSocket).

        Returns
        -------
        List[FrameResult]
            Ordered list of all processed frame results.
        """
        icfg = inference_config or InferenceConfig()
        self._all_results.clear()
        self._json_lines.clear()

        # Prepare video writer (if requested)
        writer: Optional[cv2.VideoWriter] = None

        def _result_callback(result: FrameResult) -> None:
            nonlocal writer

            self._all_results.append(result)

            # JSON logging
            if icfg.json_output_path:
                self._json_lines.append(result.state_dict)

            # Display
            if icfg.show:
                display = result.annotated_frame
                if icfg.display_scale != 1.0:
                    h, w = display.shape[:2]
                    display = cv2.resize(
                        display,
                        (int(w * icfg.display_scale), int(h * icfg.display_scale)),
                    )
                cv2.imshow("Gridlock – Traffic Violation Detection", display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    self.stop()
                    return

            # Video writer init on first frame
            if icfg.output_path and writer is None:
                h, w = result.annotated_frame.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(icfg.output_path, fourcc, 10.0, (w, h))
                logger.info("VideoWriter opened: %s (%dx%d @ 10fps)", icfg.output_path, w, h)

            if writer is not None:
                writer.write(result.annotated_frame)

            # Max-frame guard
            if icfg.max_frames and result.frame_id >= icfg.max_frames:
                self.stop()

            # Extra callback
            if extra_callback:
                try:
                    extra_callback(result)
                except Exception as exc:
                    logger.error("extra_callback raised: %s", exc)

            # Per-frame summary log
            if result.violations:
                logger.info(
                    "Frame %d | %d violations | %s",
                    result.frame_id,
                    len(result.violations),
                    [v.violation_type for v in result.violations],
                )

        # Build processor
        self._processor = VideoProcessor(self._app_cfg, _result_callback)
        self._running = True

        try:
            self._processor.start(source)
            self._processor.join()
        finally:
            self._running = False
            if writer is not None:
                writer.release()
                logger.info("VideoWriter released: %s", icfg.output_path)

            if icfg.json_output_path and self._json_lines:
                self._write_json(icfg.json_output_path, self._json_lines)

            if icfg.show:
                cv2.destroyAllWindows()

        logger.info(
            "Run complete | total_frames=%d | total_violations=%d",
            len(self._all_results),
            sum(len(r.violations) for r in self._all_results),
        )
        return self._all_results

    def stop(self) -> None:
        """Request the pipeline to stop gracefully."""
        if self._processor and self._running:
            logger.info("InferenceEngine: stop requested")
            self._processor.stop()

    def get_state_json(self) -> Optional[dict]:
        """
        Return the current ``StateManager`` snapshot as a dict, or ``None``
        if no processor is active.
        """
        if self._processor:
            return self._processor.state_manager.to_dict()
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_json(path: str, records: List[dict]) -> None:
        """Write *records* as a JSON array to *path*."""
        try:
            out_path = Path(path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(records, fh, indent=2, default=str)
            logger.info("JSON output written: %s (%d records)", path, len(records))
        except Exception as exc:
            logger.error("Failed to write JSON: %s", exc)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gridlock – Traffic Violation Detection Engine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source", "-s",
        default="0",
        help="Video source: file path, RTSP URL, or camera index (int).",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display annotated frames in a window (press Q to quit).",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Path to write annotated output video (mp4v).",
    )
    parser.add_argument(
        "--json-output", "-j",
        default=None,
        dest="json_output",
        help="Path to write per-frame JSON state records.",
    )
    parser.add_argument(
        "--max-frames", "-n",
        type=int,
        default=None,
        dest="max_frames",
        help="Stop after N processed frames.",
    )
    parser.add_argument(
        "--frame-skip",
        type=int,
        default=3,
        dest="frame_skip",
        help="Process every Nth raw frame (1 = no skip).",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        choices=["cuda", "cpu"],
        help="Inference device.",
    )
    parser.add_argument(
        "--no-half",
        action="store_true",
        dest="no_half",
        help="Disable FP16 half-precision (use when running on CPU).",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Display scale factor (display only, does not affect output).",
    )
    return parser


def _parse_source(raw: str) -> str | int:
    """Convert the CLI source argument to int if it looks like a device index."""
    try:
        return int(raw)
    except ValueError:
        return raw


def main() -> None:
    """CLI entry-point."""
    parser = _build_parser()
    args = parser.parse_args()

    # Build AppConfig from CLI args
    cfg = AppConfig()
    cfg.video.frame_skip = args.frame_skip
    cfg.detection.device = args.device
    cfg.detection.half_precision = not args.no_half

    icfg = InferenceConfig(
        show=args.show,
        output_path=args.output,
        json_output_path=args.json_output,
        max_frames=args.max_frames,
        display_scale=args.scale,
    )

    engine = InferenceEngine(cfg)

    # Graceful shutdown on Ctrl-C / SIGTERM
    def _signal_handler(sig, _frame):
        logger.info("Signal %s received – stopping …", sig)
        engine.stop()

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    source = _parse_source(args.source)
    logger.info("Starting Gridlock engine | source=%s", source)
    engine.run(source=source, inference_config=icfg)


if __name__ == "__main__":
    main()
