# -*- coding: utf-8 -*-
"""
test_routes.py
--------------
Comprehensive API route tester for the Gridlock Traffic Violation Detection API.

Tests all REST endpoints:
  GET  /health
  GET  /api/state
  GET  /api/metrics
  GET  /api/violations
  GET  /api/analytics
  GET  /api/heatmap
  POST /api/start
  POST /api/stop
  POST /api/upload
  PATCH /api/config

Usage
-----
  # Make sure the server is running first:
  #   cd e:/gridlock
  #   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

  # Then run this script (from project root):
  #   python test_routes.py

  # Or target a different host:
  #   python test_routes.py --host http://localhost:8000

Requirements
------------
  pip install requests Pillow
"""

import argparse
import io
import json
import sys
import time
from typing import Any, Dict, Optional

import requests

# ─────────────────────────────────────────────────────────────
#  Colour helpers (no external dep)
# ─────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS = f"{GREEN}[PASS]{RESET}"
FAIL = f"{RED}[FAIL]{RESET}"
WARN = f"{YELLOW}[WARN]{RESET}"
INFO = f"{CYAN}[INFO]{RESET}"


# ─────────────────────────────────────────────────────────────
#  Result accumulator
# ─────────────────────────────────────────────────────────────
results: list[dict] = []


def record(name: str, passed: bool, detail: str = ""):
    symbol = PASS if passed else FAIL
    print(f"  {symbol}  {name}")
    if detail:
        print(f"        {detail}")
    results.append({"name": name, "passed": passed, "detail": detail})


def section(title: str):
    print(f"\n{BOLD}{CYAN}{'-'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'-'*60}{RESET}")


def pretty(data: Any, indent: int = 6) -> str:
    return json.dumps(data, indent=2).replace("\n", "\n" + " " * indent)


# ─────────────────────────────────────────────────────────────
#  Request helpers
# ─────────────────────────────────────────────────────────────
def get(base: str, path: str, params: Optional[Dict] = None, timeout: int = 10):
    try:
        r = requests.get(f"{base}{path}", params=params, timeout=timeout)
        return r
    except requests.exceptions.ConnectionError:
        print(f"\n{RED}  ✗  Cannot connect to {base}.  Is the server running?{RESET}")
        sys.exit(1)


def post(base: str, path: str, json_body: Optional[Dict] = None,
         files=None, timeout: int = 15):
    try:
        r = requests.post(f"{base}{path}", json=json_body, files=files, timeout=timeout)
        return r
    except requests.exceptions.ConnectionError:
        print(f"\n{RED}  ✗  Cannot connect to {base}.  Is the server running?{RESET}")
        sys.exit(1)


def patch(base: str, path: str, json_body: Optional[Dict] = None, timeout: int = 10):
    try:
        r = requests.patch(f"{base}{path}", json=json_body, timeout=timeout)
        return r
    except requests.exceptions.ConnectionError:
        print(f"\n{RED}  ✗  Cannot connect to {base}.  Is the server running?{RESET}")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────
#  Individual test groups
# ─────────────────────────────────────────────────────────────

def test_health(base: str):
    section("GET /health — Liveness probe")
    r = get(base, "/health")
    passed = r.status_code == 200
    record("Status 200", passed, f"HTTP {r.status_code}")

    if passed:
        data = r.json()
        print(f"      Response: {pretty(data)}")
        record("has 'status' field",   "status" in data)
        record("status == ok/OK",      str(data.get("status", "")).lower() == "ok")
        record("has 'version' field",  "version" in data)
        record("has 'engine_running'", "engine_running" in data)


def test_metrics(base: str):
    section("GET /api/metrics — Live performance metrics")
    r = get(base, "/api/metrics")
    passed = r.status_code == 200
    record("Status 200", passed, f"HTTP {r.status_code}")

    if passed:
        data = r.json()
        print(f"      Response: {pretty(data)}")
        for field in ["fps", "total_violations", "vehicles_tracked",
                      "ocr_reads", "frames_processed", "uptime_seconds", "is_running"]:
            record(f"has '{field}'", field in data)


def test_state(base: str):
    section("GET /api/state — Current detection snapshot")
    r = get(base, "/api/state")
    passed = r.status_code == 200
    record("Status 200", passed, f"HTTP {r.status_code}")

    if passed:
        data = r.json()
        print(f"      Response: {pretty(data)}")
        for field in ["frame_id", "timestamp", "detections", "violations"]:
            record(f"has '{field}'", field in data)
        record("detections is list", isinstance(data.get("detections"), list))
        record("violations is list", isinstance(data.get("violations"), list))


def test_violations(base: str):
    section("GET /api/violations — Paginated violation history")

    # Default page
    r = get(base, "/api/violations")
    passed = r.status_code == 200
    record("Status 200 (default params)", passed, f"HTTP {r.status_code}")

    if passed:
        data = r.json()
        print(f"      Response: {pretty(data)}")
        for field in ["violations", "total", "page", "page_size"]:
            record(f"has '{field}'", field in data)
        record("violations is list", isinstance(data.get("violations"), list))
        record("page == 1",           data.get("page") == 1)
        record("page_size == 50",     data.get("page_size") == 50)

    # Custom pagination
    r2 = get(base, "/api/violations", params={"page": 1, "page_size": 5})
    record("Status 200 (page_size=5)", r2.status_code == 200, f"HTTP {r2.status_code}")
    if r2.status_code == 200:
        d2 = r2.json()
        record("page_size respected", d2.get("page_size") == 5)
        record("len(violations) <= 5", len(d2.get("violations", [])) <= 5)

    # Filter by violation_type
    r3 = get(base, "/api/violations",
             params={"violation_type": "WithoutHelmet"})
    record("Status 200 (filter WithoutHelmet)", r3.status_code == 200, f"HTTP {r3.status_code}")

    # Bad page param
    r4 = get(base, "/api/violations", params={"page": 0})
    record("page=0 -> 422 Unprocessable",
           r4.status_code == 422,
           f"HTTP {r4.status_code}")


def test_analytics(base: str):
    section("GET /api/analytics — Aggregated analytics")
    r = get(base, "/api/analytics")
    passed = r.status_code == 200
    record("Status 200", passed, f"HTTP {r.status_code}")

    if passed:
        data = r.json()
        print(f"      Response: {pretty(data)}")
        for field in ["type_breakdown", "hourly_violations", "top_plates",
                      "total_violations", "total_vehicles", "avg_fps",
                      "uptime_seconds", "ocr_success_rate"]:
            record(f"has '{field}'", field in data)
        record("top_plates is list", isinstance(data.get("top_plates"), list))


def test_heatmap(base: str):
    section("GET /api/heatmap — Violation heatmap points")
    r = get(base, "/api/heatmap")
    passed = r.status_code == 200
    record("Status 200", passed, f"HTTP {r.status_code}")

    if passed:
        data = r.json()
        print(f"      Response: {pretty(data)}")
        record("has 'points'", "points" in data)
        record("has 'total'",  "total"  in data)
        record("points is list", isinstance(data.get("points"), list))
        record("total matches len(points)",
               data.get("total") == len(data.get("points", [])))


def test_config_patch(base: str):
    section("PATCH /api/config — Hot-reload detection parameters")

    # Valid update
    body = {"confidence_threshold": 0.55, "frame_skip": 4}
    r = patch(base, "/api/config", json_body=body)
    passed = r.status_code == 200
    record("Status 200 (valid body)", passed, f"HTTP {r.status_code}")

    if passed:
        data = r.json()
        print(f"      Response: {pretty(data)}")
        record("status == 'updated'",             data.get("status") == "updated")
        record("confidence_threshold returned",   "confidence_threshold" in data)
        record("frame_skip returned",             "frame_skip" in data)
        record("confidence_threshold == 0.55",
               abs(data.get("confidence_threshold", 0) - 0.55) < 1e-6)
        record("frame_skip == 4",                data.get("frame_skip") == 4)

    # Partial update (only frame_skip)
    r2 = patch(base, "/api/config", json_body={"frame_skip": 2})
    record("Status 200 (partial body)", r2.status_code == 200, f"HTTP {r2.status_code}")

    # Out-of-range value
    r3 = patch(base, "/api/config", json_body={"confidence_threshold": 5.0})
    record("confidence=5.0 → 422", r3.status_code == 422, f"HTTP {r3.status_code}")

    # Empty body (no-op)
    r4 = patch(base, "/api/config", json_body={})
    record("Empty body → 200", r4.status_code == 200, f"HTTP {r4.status_code}")


def _make_dummy_jpeg() -> bytes:
    """
    Generate a minimal valid 64x64 JPEG in pure Python (no Pillow needed
    at import time; Pillow is only used if available, otherwise we embed
    a raw 1×1 JPEG byte blob that every decoder accepts).
    """
    # Tiny valid JPEG (1x1 white pixel)  – always available
    _ONE_PIX_JPEG = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
        b"B\xc8\x01\x00\x00\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x10\xff\xc0\x00\x0b\x08\x00\x01\x00\x01"
        b"\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01"
        b"\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06"
        b"\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04"
        b"\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05"
        b"\x12!1A\x06\x13Qa\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1"
        b"\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWX"
        b"YZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94"
        b"\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2"
        b"\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8"
        b"\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4"
        b"\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9"
        b"\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd6P\x00\x00\x00"
        b"\x1f\xff\xd9"
    )
    try:
        from PIL import Image
        img = Image.new("RGB", (64, 64), color=(200, 100, 50))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()
    except ImportError:
        return _ONE_PIX_JPEG


def test_upload(base: str):
    section("POST /api/upload — On-demand image YOLO analysis")

    jpeg = _make_dummy_jpeg()

    r = post(
        base, "/api/upload",
        files={"file": ("test_image.jpg", jpeg, "image/jpeg")},
    )
    passed = r.status_code == 200
    record("Status 200 (valid JPEG)", passed, f"HTTP {r.status_code}")

    if passed:
        data = r.json()
        record("has 'annotated_image_b64'", "annotated_image_b64" in data)
        record("has 'detections'",          "detections" in data)
        record("has 'width'",               "width" in data)
        record("has 'height'",              "height" in data)
        record("has 'detection_count'",     "detection_count" in data)
        record("annotated_image_b64 non-empty",
               bool(data.get("annotated_image_b64", "")))
        record("detection_count int",
               isinstance(data.get("detection_count"), int))
        print(f"      Detections found: {data.get('detection_count')}  "
              f"Image: {data.get('width')}×{data.get('height')}")

    # Invalid file (plain text)
    r2 = post(
        base, "/api/upload",
        files={"file": ("bad.txt", b"not an image", "text/plain")},
    )
    record("Invalid file → 400", r2.status_code == 400, f"HTTP {r2.status_code}")


def test_start_stop(base: str):
    """
    Tests the start/stop lifecycle. Since we don't have a real video file
    on the test machine, we test the error paths AND the happy path using
    webcam index 0 (if available).  The pipeline start is non-blocking, so
    we always stop right after.
    """
    section("POST /api/start + POST /api/stop — Pipeline lifecycle")

    # ── 1. Start with a non-existent file (expect 200 – pipeline starts async,
    #        failure only appears later; the endpoint itself just launches it)
    body = {"video_path": "/nonexistent/video.mp4", "frame_skip": 3}
    r = post(base, "/api/start", json_body=body)
    started = r.status_code == 200
    record("Status 200 (async start accepted)", started, f"HTTP {r.status_code}")
    if started:
        data = r.json()
        print(f"      Response: {pretty(data)}")
        record("status == 'started'", data.get("status") == "started")

    # ── 2. Second start while running → 409 Conflict
    if started:
        time.sleep(0.3)  # give it a moment to register as running
        r2 = post(base, "/api/start", json_body=body)
        # It might already have stopped (bad source), so accept 409 or 200
        record(
            "Duplicate start → 409 (or pipeline already stopped → 200)",
            r2.status_code in (409, 200),
            f"HTTP {r2.status_code}",
        )

    # ── 3. Stop
    r3 = post(base, "/api/stop")
    record(
        "Stop → 200 (or 409 if pipeline already stopped)",
        r3.status_code in (200, 409),
        f"HTTP {r3.status_code}",
    )

    # ── 4. Double-stop → 409
    time.sleep(0.3)
    r4 = post(base, "/api/stop")
    record("Double-stop → 409", r4.status_code == 409, f"HTTP {r4.status_code}")

    # ── 5. Start with missing body field
    r5 = post(base, "/api/start", json_body={})   # video_path is required
    record("Missing video_path → 422", r5.status_code == 422, f"HTTP {r5.status_code}")

    # ── 6. Valid frame_skip boundary values
    for fs in [1, 30]:
        rb = post(base, "/api/start", json_body={"video_path": "0", "frame_skip": fs})
        record(f"frame_skip={fs} accepted (200 or 409 if running)",
               rb.status_code in (200, 409),
               f"HTTP {rb.status_code}")
        # Always try to clean up
        post(base, "/api/stop")
        time.sleep(0.2)

    # ── 7. Out-of-range frame_skip
    r6 = post(base, "/api/start", json_body={"video_path": "0", "frame_skip": 99})
    record("frame_skip=99 → 422", r6.status_code == 422, f"HTTP {r6.status_code}")


# ─────────────────────────────────────────────────────────────
#  WebSocket smoke-test (optional)
# ─────────────────────────────────────────────────────────────

def test_websocket_smoke(base: str):
    section("WS /ws/live — WebSocket connection smoke test")
    ws_url = base.replace("http://", "ws://").replace("https://", "wss://") + "/ws/live"
    try:
        import websocket  # websocket-client
        ws = websocket.create_connection(ws_url, timeout=3)
        record("WebSocket connected", True, ws_url)
        ws.close()
    except ImportError:
        record(
            "websocket-client not installed (skip)",
            True,
            "pip install websocket-client to enable this test",
        )
    except Exception as exc:
        record("WebSocket connection", False, str(exc))


# ─────────────────────────────────────────────────────────────
#  Summary
# ─────────────────────────────────────────────────────────────

def print_summary():
    total  = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  TEST SUMMARY{RESET}")
    print(f"{'='*60}")
    print(f"  Total  : {total}")
    print(f"  {GREEN}Passed : {passed}{RESET}")
    if failed:
        print(f"  {RED}Failed : {failed}{RESET}")
        print(f"\n  {RED}Failed tests:{RESET}")
        for r in results:
            if not r["passed"]:
                print(f"    [x] {r['name']}")
                if r["detail"]:
                    print(f"        -> {r['detail']}")
    else:
        print(f"  {GREEN}All tests passed!{RESET}")
    print(f"{'='*60}\n")

    return 0 if failed == 0 else 1


# ─────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gridlock API Route Tester")
    parser.add_argument(
        "--host",
        default="http://localhost:8000",
        help="Base URL of the running API  (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--skip-pipeline",
        action="store_true",
        help="Skip the start/stop pipeline tests (useful if you have no video source)",
    )
    args = parser.parse_args()

    base = args.host.rstrip("/")

    print(f"\n{BOLD}Gridlock API Route Tester{RESET}")
    print(f"  Target : {CYAN}{base}{RESET}")
    print(f"  Time   : {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Run all tests ──────────────────────────────────────────
    test_health(base)
    test_metrics(base)
    test_state(base)
    test_violations(base)
    test_analytics(base)
    test_heatmap(base)
    test_config_patch(base)
    test_upload(base)
    if not args.skip_pipeline:
        test_start_stop(base)
    else:
        print(f"\n{WARN}  Skipping pipeline start/stop tests (--skip-pipeline flag set)")

    test_websocket_smoke(base)

    # ── Print summary and exit ─────────────────────────────────
    sys.exit(print_summary())


if __name__ == "__main__":
    main()
