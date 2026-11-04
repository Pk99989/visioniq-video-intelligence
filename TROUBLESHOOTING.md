# TROUBLESHOOTING

- **Video stuck at "processing"**: the server marks interrupted jobs
  `failed` on restart (see worker recovery). Open Processing and click
  Retry. Check the backend log for the `error_message` on the video.
- **"Detection available: false"** on /health: expected without weights.
  Run `scripts/download_yolo.py` (needs ultralytics) and place
  `yolov8n.pt` in `backend/`, then restart.
- **Captions say "Template caption"**: expected with `VLM_PROVIDER=fallback`.
  Set a real provider + `VLM_BASE_URL` (Ollama vision model or NVIDIA NIM)
  and re-process the video (delete + re-upload, or retry after clearing
  captions — captions are per-processing-run).
- **Search returns nothing**: the video must be `ready` first; agent Q&A
  also applies a 0.45 score floor, while raw `/search` does not — try the
  Search page with the same query to compare.
- **Frontend can't reach the backend**: check `NEXT_PUBLIC_API_URL`
  (default http://localhost:8000) and that CORS allows
  http://localhost:3000 (it does in `app/main.py`).
- **Docker not found (this build machine)**: Docker is not installed in
  the Muse execution environment. Docker paths are for your WSL machine;
  use `scripts/run_dev.sh` (no Docker) to run here.
- **GPU not found**: expected on CPU-only machines. Nothing in v0.1.0
  requires a GPU; YOLO/VLM will run on CPU (slower) if enabled.
