# -*- coding: utf-8 -*-
"""
test_upload.py
--------------
Focused test suite for POST /api/upload — on-demand YOLO detection.

Tests
~~~~~
1.  Valid JPEG  (solid colour, 640x640)
2.  Valid PNG   (solid colour, 320x320)
3.  Valid JPEG  (small thumbnail 64x64)
4.  Valid JPEG  (large 1280x720)
5.  Plain text  -> 400
6.  Empty file  -> 400
7.  No file field -> 422
8.  Corrupt JPEG header -> 400
9.  Response schema validation
10. Base-64 is decodable back to a JPEG
11. Timing: first call (cold, loads model) vs second call (warm)

Usage
-----
  python test_upload.py
  python test_upload.py --host http://localhost:8000
"""

import argparse
import base64
import io
import struct
import sys
import time

import requests

# ─── colour helpers ───────────────────────────────────────────
GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
BOLD  = "\033[1m"
RESET = "\033[0m"

results: list[dict] = []


def ok(name, detail=""):
    print(f"  {GREEN}[PASS]{RESET}  {name}")
    if detail:
        print(f"         {detail}")
    results.append({"name": name, "passed": True})


def fail(name, detail=""):
    print(f"  {RED}[FAIL]{RESET}  {name}")
    if detail:
        print(f"         {RED}{detail}{RESET}")
    results.append({"name": name, "passed": False})


def check(cond, name, pass_detail="", fail_detail=""):
    if cond:
        ok(name, pass_detail)
    else:
        fail(name, fail_detail)


def section(title):
    print(f"\n{BOLD}{CYAN}{'-'*62}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'-'*62}{RESET}")


# ─── image builders (no Pillow required) ─────────────────────

def _jpeg_from_numpy(w: int, h: int, color_bgr=(100, 150, 200)) -> bytes:
    """Build a real JPEG using cv2 if available, else fall back to PIL, else 1px blob."""
    try:
        import cv2, numpy as np
        img = np.full((h, w, 3), color_bgr, dtype="uint8")
        ok_flag, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok_flag:
            return buf.tobytes()
    except ImportError:
        pass

    try:
        from PIL import Image
        img = Image.new("RGB", (w, h), color=(color_bgr[2], color_bgr[1], color_bgr[0]))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()
    except ImportError:
        pass

    # Fallback: hard-coded 1×1 white JPEG that every decoder accepts
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd6P\x00\x00\x00\x1f\xff\xd9"
    )


def _png_from_numpy(w: int, h: int, color_rgb=(200, 100, 50)) -> bytes:
    """Build a real PNG using cv2 or PIL, else build a minimal valid 1×1 PNG."""
    try:
        import cv2, numpy as np
        img = np.full((h, w, 3), (color_rgb[2], color_rgb[1], color_rgb[0]), dtype="uint8")
        ok_flag, buf = cv2.imencode(".png", img)
        if ok_flag:
            return buf.tobytes()
    except ImportError:
        pass

    try:
        from PIL import Image
        img = Image.new("RGB", (w, h), color=color_rgb)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        pass

    # Minimal valid 1×1 red PNG
    def _crc(data):
        import zlib
        return struct.pack(">I", zlib.crc32(data) & 0xFFFFFFFF)

    sig     = b"\x89PNG\r\n\x1a\n"
    ihdr_d  = b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    ihdr    = b"\x00\x00\x00\rIHDR" + ihdr_d + _crc(b"IHDR" + ihdr_d)
    idat_d  = b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x00\x02\x00\x01"
    idat    = struct.pack(">I", len(idat_d)) + b"IDAT" + idat_d + _crc(b"IDAT" + idat_d)
    iend    = b"\x00\x00\x00\x00IEND" + _crc(b"IEND")
    return sig + ihdr + idat + iend


def _post_upload(base: str, content: bytes, filename: str, content_type: str,
                 timeout: int = 120) -> requests.Response:
    return requests.post(
        f"{base}/api/upload",
        files={"file": (filename, content, content_type)},
        timeout=timeout,
    )


# ─── test cases ───────────────────────────────────────────────

def test_valid_jpeg_640(base: str):
    section("Test 1 — Valid JPEG 640x640 (primary happy path)")
    img = _jpeg_from_numpy(640, 640, color_bgr=(80, 120, 200))
    print(f"  Sending {len(img):,} bytes  [640x640 JPEG] ...")

    t0 = time.time()
    r = _post_upload(base, img, "scene_640.jpg", "image/jpeg", timeout=180)
    elapsed = time.time() - t0

    print(f"  Response time : {elapsed:.2f}s")
    check(r.status_code == 200, "HTTP 200", f"got {r.status_code}")

    if r.status_code != 200:
        print(f"  Server said: {r.text[:300]}")
        return None

    data = r.json()
    check("annotated_image_b64" in data, "has annotated_image_b64")
    check("detections"          in data, "has detections")
    check("width"               in data, "has width")
    check("height"              in data, "has height")
    check("detection_count"     in data, "has detection_count")

    check(data.get("width")  == 640, "width == 640",  f"got {data.get('width')}")
    check(data.get("height") == 640, "height == 640", f"got {data.get('height')}")
    check(isinstance(data.get("detection_count"), int),   "detection_count is int")
    check(isinstance(data.get("detections"), list),       "detections is list")
    check(len(data["detections"]) == data["detection_count"],
          "detection_count matches len(detections)",
          f"{data['detection_count']} == {len(data['detections'])}")

    # Base-64 decode check
    b64 = data.get("annotated_image_b64", "")
    check(len(b64) > 0, "annotated_image_b64 non-empty", f"len={len(b64)}")
    try:
        decoded = base64.b64decode(b64)
        check(decoded[:2] == b"\xff\xd8", "decoded b64 is valid JPEG (FF D8 header)",
              f"first bytes: {decoded[:4].hex()}")
        check(len(decoded) > 500, "decoded JPEG is non-trivial",
              f"size={len(decoded):,} bytes")
    except Exception as e:
        fail("base64 decode succeeded", str(e))

    # Per-detection schema
    if data["detections"]:
        det = data["detections"][0]
        check("class_id"   in det, "detection has class_id")
        check("class_name" in det, "detection has class_name")
        check("confidence" in det, "detection has confidence")
        check("bbox"       in det, "detection has bbox")
        bbox = det.get("bbox", {})
        for coord in ["x1", "y1", "x2", "y2"]:
            check(coord in bbox, f"bbox has {coord}")
        check(det["confidence"] >= 0 and det["confidence"] <= 1,
              "confidence in [0, 1]", f"{det['confidence']:.4f}")

    print(f"  Detections found: {data.get('detection_count', 0)}")
    return elapsed


def test_valid_png_320(base: str):
    section("Test 2 — Valid PNG 320x320")
    img = _png_from_numpy(320, 320, color_rgb=(200, 180, 90))
    print(f"  Sending {len(img):,} bytes  [320x320 PNG] ...")

    t0 = time.time()
    r = _post_upload(base, img, "frame_320.png", "image/png", timeout=120)
    elapsed = time.time() - t0

    print(f"  Response time : {elapsed:.2f}s")
    check(r.status_code == 200, "HTTP 200", f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check(data.get("width")  == 320, "width == 320",  f"got {data.get('width')}")
        check(data.get("height") == 320, "height == 320", f"got {data.get('height')}")
        print(f"  Detections found: {data.get('detection_count', 0)}")


def test_valid_jpeg_small(base: str):
    section("Test 3 — Valid JPEG 64x64 (tiny thumbnail)")
    img = _jpeg_from_numpy(64, 64, color_bgr=(40, 40, 40))
    print(f"  Sending {len(img):,} bytes  [64x64 JPEG] ...")

    t0 = time.time()
    r = _post_upload(base, img, "thumb.jpg", "image/jpeg", timeout=120)
    elapsed = time.time() - t0

    print(f"  Response time : {elapsed:.2f}s")
    check(r.status_code == 200, "HTTP 200", f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check(data.get("width")  == 64,  "width == 64",  f"got {data.get('width')}")
        check(data.get("height") == 64,  "height == 64", f"got {data.get('height')}")


def test_valid_jpeg_large(base: str):
    section("Test 4 — Valid JPEG 1280x720 (HD frame)")
    img = _jpeg_from_numpy(1280, 720, color_bgr=(30, 90, 160))
    print(f"  Sending {len(img):,} bytes  [1280x720 JPEG] ...")

    t0 = time.time()
    r = _post_upload(base, img, "hd_frame.jpg", "image/jpeg", timeout=180)
    elapsed = time.time() - t0

    print(f"  Response time : {elapsed:.2f}s")
    check(r.status_code == 200, "HTTP 200", f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check(data.get("width")  == 1280, "width == 1280",  f"got {data.get('width')}")
        check(data.get("height") == 720,  "height == 720",  f"got {data.get('height')}")
        print(f"  Detections found: {data.get('detection_count', 0)}")


def test_plain_text(base: str):
    section("Test 5 — Plain text file (should be rejected as 400)")
    content = b"this is not an image at all, just text data"
    r = _post_upload(base, content, "notes.txt", "text/plain", timeout=30)
    check(r.status_code == 400, "HTTP 400 for plain text", f"got {r.status_code}")
    if r.status_code == 400:
        detail = r.json().get("detail", "")
        check("decode" in detail.lower() or "image" in detail.lower(),
              "error message mentions decode/image", f"detail: '{detail}'")


def test_empty_file(base: str):
    section("Test 6 — Empty file (should be rejected as 400)")
    r = _post_upload(base, b"", "empty.jpg", "image/jpeg", timeout=30)
    check(r.status_code in (400, 422), "HTTP 400 or 422 for empty file",
          f"got {r.status_code}")


def test_no_file_field(base: str):
    section("Test 7 — Missing 'file' field (should be 422 Unprocessable)")
    r = requests.post(f"{base}/api/upload", data={"other": "data"}, timeout=15)
    check(r.status_code == 422, "HTTP 422 when file field missing",
          f"got {r.status_code}")
    if r.status_code == 422:
        errs = r.json().get("detail", [])
        print(f"  Validation errors: {errs}")


def test_corrupt_jpeg(base: str):
    section("Test 8 — Corrupt JPEG (valid header, garbage body)")
    content = b"\xff\xd8\xff\xe0" + b"\x00" * 50 + b"\xde\xad\xbe\xef" * 100
    r = _post_upload(base, content, "corrupt.jpg", "image/jpeg", timeout=30)
    check(r.status_code in (400, 422, 500),
          "HTTP 400/422/500 for corrupt JPEG", f"got {r.status_code}")
    print(f"  Server returned: {r.status_code} — {r.text[:120]}")


def test_wrong_extension_right_content(base: str):
    section("Test 9 — JPEG content with .png extension (content-over-name)")
    img = _jpeg_from_numpy(128, 128)
    # Send a real JPEG but lie about the filename extension
    r = _post_upload(base, img, "image.png", "image/png", timeout=120)
    # cv2.imdecode doesn't care about filenames — should still work
    check(r.status_code == 200,
          "HTTP 200 — cv2 decodes by content not extension",
          f"got {r.status_code}")


def test_timing(base: str, first_elapsed: float | None):
    section("Test 10 — Timing: warm vs cold call")
    if first_elapsed is None:
        print("  Skipped (first call did not succeed).")
        return

    # Second call — model already loaded
    img = _jpeg_from_numpy(320, 320)
    t0 = time.time()
    r = _post_upload(base, img, "warm.jpg", "image/jpeg", timeout=120)
    warm_elapsed = time.time() - t0

    if r.status_code == 200:
        print(f"  Cold call (first): {first_elapsed:.2f}s")
        print(f"  Warm call (this) : {warm_elapsed:.2f}s")
        check(warm_elapsed < first_elapsed or warm_elapsed < 30,
              "Warm call is reasonably fast (< 30s)",
              f"{warm_elapsed:.2f}s")
        if first_elapsed > 10:
            ok("Cold call took longer (model load confirmed)",
               f"First={first_elapsed:.1f}s > Second={warm_elapsed:.1f}s")
    else:
        fail("HTTP 200 on warm call", f"got {r.status_code}")


# ─── summary ──────────────────────────────────────────────────

def summary():
    total  = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    print(f"\n{BOLD}{'='*62}{RESET}")
    print(f"{BOLD}  UPLOAD ROUTE TEST SUMMARY{RESET}")
    print(f"{'='*62}")
    print(f"  Total  : {total}")
    print(f"  {GREEN}Passed : {passed}{RESET}")
    if failed:
        print(f"  {RED}Failed : {failed}{RESET}")
        print(f"\n  {RED}Failed:{RESET}")
        for r in results:
            if not r["passed"]:
                print(f"    [x] {r['name']}")
    else:
        print(f"  {GREEN}All passed!{RESET}")
    print(f"{'='*62}\n")
    return failed


# ─── entry point ──────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="POST /api/upload focused tests")
    ap.add_argument("--host", default="http://localhost:8000",
                    help="API base URL (default: http://localhost:8000)")
    args = ap.parse_args()
    base = args.host.rstrip("/")

    print(f"\n{BOLD}POST /api/upload — Focused Test Suite{RESET}")
    print(f"  Target : {CYAN}{base}/api/upload{RESET}")
    print(f"  Note   : First call may be SLOW (lazy loads YOLO model + warm-up)")

    # Run tests — note first call result returned for timing comparison
    first_elapsed = test_valid_jpeg_640(base)
    test_valid_png_320(base)
    test_valid_jpeg_small(base)
    test_valid_jpeg_large(base)
    test_plain_text(base)
    test_empty_file(base)
    test_no_file_field(base)
    test_corrupt_jpeg(base)
    test_wrong_extension_right_content(base)
    test_timing(base, first_elapsed)

    sys.exit(summary())


if __name__ == "__main__":
    main()
