# Gridlock — Traffic Violation Detection Engine

Modular, multi-threaded traffic violation detection using **YOLOv8**, **EasyOCR**, and **OpenCV**.

---

## Architecture

```
gridlock/
├── inference_engine.py          ← Top-level façade & CLI entry-point
├── best.pt                      ← Custom YOLOv8 model (place here)
├── requirements.txt
└── backend/
    ├── core/
    │   ├── config.py            ← All configuration (including parking ROI)
    │   └── state_manager.py     ← Thread-safe state (RLock-protected)
    └── services/
        ├── detector.py          ← YOLOv8 wrapper with ByteTrack tracking
        ├── tracker.py           ← Per-track metadata registry
        ├── ocr.py               ← Async EasyOCR with per-track caching
        ├── violation_engine.py  ← Rule functions + orchestrator
        └── video_processor.py  ← Producer/Consumer pipeline
```

---

## Quick Start

### 1. Install dependencies

```bash
# Create venv (recommended)
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt

# CUDA GPU support (adjust cu121 to your CUDA version)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

### 2. Place your model

```
gridlock/best.pt
```

### 3. Run on a video file

```bash
python inference_engine.py --source traffic.mp4 --show --output out.mp4 --json-output results.json
```

### 4. Run on a webcam

```bash
python inference_engine.py --source 0 --show
```

---

## CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--source` / `-s` | `0` | Video file, RTSP URL, or camera index |
| `--show` | off | Display annotated frames (Q to quit) |
| `--output` / `-o` | None | Write annotated mp4 to this path |
| `--json-output` / `-j` | None | Write per-frame JSON to this path |
| `--max-frames` / `-n` | None | Stop after N processed frames |
| `--frame-skip` | `3` | Process every Nth raw frame |
| `--device` | `cuda` | `cuda` or `cpu` |
| `--no-half` | off | Disable FP16 (required for CPU) |
| `--scale` | `1.0` | Display scale (does not affect output) |

---

## Configuration

All system parameters live in [`backend/core/config.py`](backend/core/config.py).

### Parking ROI

Edit the `parking_roi` list in `ViolationConfig`:

```python
# config.py → ViolationConfig
parking_roi: List[Tuple[int, int]] = [
    (200, 300),   # top-left
    (800, 300),   # top-right
    (800, 600),   # bottom-right
    (200, 600),   # bottom-left
]
```

Coordinates are pixel positions in the **resized** 1280×720 frame.

### Frame Skip

```python
# config.py → VideoConfig
frame_skip: int = 3   # process frames 0, 3, 6, 9, …
```

---

## Violation Rules

| # | Rule | Trigger |
|---|------|---------|
| 1 | `WithoutHelmet` | Model detects class `WithoutHelmet` |
| 2 | `TripleRiding` | Model detects class `TripleRiding` |
| 3 | `IllegalParking` | Vehicle inside ROI polygon for ≥ 30 consecutive processed frames |

---

## Python API

```python
from inference_engine import InferenceEngine, InferenceConfig
from backend.core.config import AppConfig, ViolationConfig

# Customise the parking ROI
cfg = AppConfig()
cfg.violation.parking_roi = [(100, 200), (700, 200), (700, 500), (100, 500)]
cfg.video.frame_skip = 3

icfg = InferenceConfig(show=True, output_path="annotated.mp4")

engine = InferenceEngine(cfg)
results = engine.run(source="traffic.mp4", inference_config=icfg)

for r in results:
    if r.violations:
        print(r.frame_id, [v.violation_type for v in r.violations])
```

---

## Output Schema

Each frame produces a `FrameResult` with:

```json
{
  "frame_id": 42,
  "timestamp": "2025-01-01T12:00:00.000+00:00",
  "detections": [
    {
      "class_id": 2,
      "class_name": "WithoutHelmet",
      "confidence": 0.87,
      "bbox": {"x1": 120, "y1": 80, "x2": 200, "y2": 160},
      "track_id": 7,
      "plate_text": "MH12AB1234",
      "plate_confidence": 0.93
    }
  ],
  "violations": [
    {
      "violation_type": "WithoutHelmet",
      "frame_id": 42,
      "timestamp": "...",
      "track_id": 7,
      "plate_text": "MH12AB1234",
      "bbox": {"x1": 120, "y1": 80, "x2": 200, "y2": 160},
      "confidence": 0.87,
      "metadata": {}
    }
  ]
}
```

---

## Performance Targets

| Metric | Target |
|--------|--------|
| Resolution | 720p (1280×720) |
| Processing rate | ≥ 10 FPS on T4 GPU |
| Frame skip | 3 (every 3rd frame decoded) |
| OCR | Async, cached per track ID |
| ROI filter | IoU pre-check + pointPolygonTest |
