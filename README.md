---
title: OmniGuard Vision
emoji: 🚦
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# OmniGuard-Vision 🚦

**Production-Grade Edge-to-Cloud AI for Traffic Enforcement**

OmniGuard-Vision is a multi-threaded, full-stack computer vision platform designed to automate traffic violation detection. Using a state-of-the-art **YOLO26n** tracking engine alongside **EasyOCR**, this system accurately flags violations such as Helmetless Riding, Triple Riding, and Illegal Parking in real-time, automatically capturing the license plate of the offender.

## 🌟 Features

- **Full-Stack Architecture:** Lightning-fast FastAPI asynchronous backend paired with a beautiful, dynamic React + Vite frontend dashboard.
- **YOLO26n + ByteTrack:** High-speed, high-accuracy vehicle tracking and violation classification.
- **Asynchronous OCR:** License plate recognition runs in a separate thread pool to prevent video stuttering.
- **Live WebSocket Streaming:** View bounding boxes and tracking IDs drawn over the video stream in real-time with sub-millisecond socket latency.
- **Historical Analytics:** View captured violation records and geographical heatmaps.
- **Hugging Face Ready:** Fully containerised for instant deployment to cloud data centres.

---

## 🚀 Live Cloud Demo

Test the platform instantly without installing anything locally!
👉 **[OmniGuard-Vision on Hugging Face Spaces](https://huggingface.co/spaces/Lokeshm25/OmniGuard-Vision)**

---

## 💻 Instructions to Run Locally

You can run OmniGuard-Vision locally using either the unified Docker container or by running the backend and frontend separately (Development Mode). 

### Method 1: Running via Docker (Recommended)
This method perfectly mirrors our cloud deployment architecture.
*Prerequisite: Docker must be installed.*

1. **Build the Docker image:**
   `bash
   docker build -t omniguard-vision .
   `
2. **Run the container on port 7860:**
   `bash
   docker run -p 7860:7860 omniguard-vision
   `
3. **Open your web browser:** http://localhost:7860

---

### Method 2: Running via Development Mode
Use this method if you wish to test local hardware features like Webcam inference.
*Prerequisites: Python 3.11+ and Node.js v20+*

#### Step A: Start the FastAPI Backend
`bash
# 1. Install the required Python dependencies
pip install -r requirements.txt

# 2. Start the Uvicorn server
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
`

#### Step B: Start the React Frontend
`bash
# 1. Navigate to the frontend directory
cd frontend

# 2. Install the Node package dependencies
npm install

# 3. Start the Vite development server
npm run dev
`
Open your web browser to the local URL provided in the terminal (usually http://localhost:5173).

---

## 🏗️ Project Architecture

`text
OmniGuard-Vision/
├── best.pt                      ← Custom YOLO26n weights
├── Dockerfile                   ← Unified deployment container
├── backend/                     ← FastAPI Application
│   ├── main.py                  ← REST API, WebSocket streams, and SPA routing
│   ├── core/                    
│   │   ├── config.py            ← All configuration & Parking ROI geometry
│   │   └── state_manager.py     ← Thread-safe state (RLock-protected)
│   └── services/
│       ├── detector.py          ← YOLO26n wrapper with ByteTrack tracking
│       ├── ocr.py               ← Async EasyOCR with caching
│       └── video_processor.py   ← Heavy CV Consumer thread
└── frontend/                    ← React + Vite Dashboard
    ├── src/
    │   ├── components/          ← Reusable UI Components
    │   ├── context/             ← React Context (Global State)
    │   └── hooks/               ← useWebSocket with auto-reconnection logic
`

---

## 🚨 Violation Rules Engine

| Violation | Trigger Logic |
|-----------|---------------|
| **Helmetless Riding** | Model detects bounding box of class WithoutHelmet |
| **Triple Riding** | Model detects bounding box of class TripleRiding |
| **Illegal Parking** | Stationary vehicle dwells inside the pre-defined ROI polygon for ≥ 30 frames |
