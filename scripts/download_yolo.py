#!/usr/bin/env python3
"""Download YOLOv8n weights so detection becomes available.
Requires ultralytics (pip install ultralytics). Without the weights file,
the detection adapter honestly reports unavailable and returns no boxes."""
from ultralytics import YOLO

YOLO("yolov8n.pt")
print("yolov8n.pt downloaded; place it in backend/ before starting the API.")
