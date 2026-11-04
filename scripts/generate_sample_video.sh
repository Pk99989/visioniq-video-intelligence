#!/usr/bin/env bash
# Generate a small test video (no copyrighted material) for smoke tests.
set -euo pipefail
ffmpeg -y -v error -f lavfi -i "testsrc=duration=10:size=640x360:rate=10" \
  -c:v libx264 -pix_fmt yuv420p "${1:-sample.mp4}"
echo "Wrote ${1:-sample.mp4}"
