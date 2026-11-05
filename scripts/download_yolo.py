#!/usr/bin/env python3
"""Download YOLOv8n weights so detection becomes available.

Preferred (Phase 2, laptop): the ONNX export, ~12 MB, runs on
onnxruntime without torch:
    python scripts/download_yolo.py            # tries ONNX first
    python scripts/download_yolo.py --pt       # .pt via ultralytics (needs torch)

Without a weights file in backend/, the detection adapter honestly
reports unavailable and returns no boxes.
"""
import argparse
import sys
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
# Verified 2026-11-05: this community ONNX export of YOLOv8n (13 MB,
# input 640x640, output 84x8400) detects person/bus on the standard
# bus.jpg test image with confidence 0.88-0.90 and plausible boxes.
# It is NOT an official Ultralytics release (their repo ships .pt
# only); if you have ultralytics+torch, prefer --pt then export to
# ONNX yourself with `yolo export model=yolov8n.pt format=onnx`.
ONNX_URL = "https://huggingface.co/s1777/yolo-v8n-onnx/resolve/main/yolov8n.onnx?download=true"
PT_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt"


def _download(url: str, dest: Path) -> None:
    print(f"Downloading {url} -> {dest}")
    urllib.request.urlretrieve(url, dest)
    if dest.stat().st_size < 1_000_000:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed (got {dest.stat().st_size if dest.exists() else 0} bytes): {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pt", action="store_true", help="download yolov8n.pt instead of .onnx")
    args = ap.parse_args()
    if args.pt:
        from ultralytics import YOLO

        YOLO("yolov8n.pt")
        print("yolov8n.pt downloaded; place it in backend/ before starting the API.")
        return
    dest = BACKEND / "yolov8n.onnx"
    try:
        _download(ONNX_URL, dest)
    except Exception as e:  # noqa: BLE001
        print(f"ONNX download failed: {e}", file=sys.stderr)
        print("Falling back to .pt via ultralytics (needs torch)...", file=sys.stderr)
        from ultralytics import YOLO

        YOLO("yolov8n.pt")
        return
    print(f"Saved {dest} ({dest.stat().st_size / 1e6:.1f} MB). "
          "Detection is now available (provider yolo-onnx).")


if __name__ == "__main__":
    main()
