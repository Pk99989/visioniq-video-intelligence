# RELEASE CHECKLIST

How to cut a VisionIQ release. Work through it in order; every step
is a check, not a suggestion — the release is not done until each
box is ticked.

## Before the release

- [ ] All phases in the release are done and committed on `main`
      (`git log --oneline` shows the version commit at the top).
- [ ] `backend/app/main.py` version string matches the release
      (`"0.x.0"` in the FastAPI title and in `/health`).
- [ ] `mcp_server/server.py` `VERSION` matches the release.
- [ ] CHANGELOG.md has an entry for the release (what changed,
      what was measured, what is still open).
- [ ] PROJECT_STATE.md is current (version, test counts, next steps).
- [ ] TASK_TRACKER.md has a row for the release.

## Tests (run, do not assume)

- [ ] Backend: `cd backend && .venv/bin/python -m pytest tests/ -q`
      — all pass except the vlm/e2e tests, which are marked and run
      separately (see TESTING.md).
- [ ] Real-VLM e2e (if the release touches the VLM or the pipeline):
      `VISIONIQ_VLM_E2E=1 .venv/bin/python -m pytest tests/test_vlm_e2e.py tests/test_rag_eval.py -q`
- [ ] Browser e2e (if the release touches the frontend or the API):
      `VISIONIQ_E2E=1 .venv/bin/python -m pytest tests/test_e2e_browser.py -q`
      against a backend + freshly built frontend.
- [ ] Frontend: `cd frontend && npm test && npm run build` — green.

## Docker (the release must start from a clean checkout)

- [ ] `docker compose config` (full stack) and
      `docker compose -f docker-compose.laptop.yml config` parse.
- [ ] From a clean clone: `docker compose -f docker-compose.laptop.yml up --build -d`
      reaches healthy on all services (`docker compose -f docker-compose.laptop.yml ps`).
- [ ] `curl localhost:8000/health` returns `{"status": "ok", ...}` with
      the release version.
- [ ] Register → upload a video → it reaches `ready` → search finds it.
- [ ] `docker compose -f docker-compose.laptop.yml down` stops cleanly;
      a second `up` reuses the data (uploads survive).

## Tag and ship

- [ ] `git tag -a v0.x.0 -m "v0.x.0: <short description>"` on the
      release commit; `git log --oneline --decorate -1` shows the tag.
- [ ] Push the tag when the GitHub remote exists
      (`git push origin v0.x.0`).
- [ ] Build the release zip from a clean export
      (`git archive -o visioniq-v0.x.0.zip HEAD`, plus the YOLO
      weights note in DEPLOYMENT.md — weights are NOT in git).
- [ ] Update `~/MEMORY.md` (version, phases done, next phase).

## Notes for this machine (the dev VM)

- Docker's daemon cannot create bridge networks here (the VM blocks
  iptables / interface creation), so `docker compose up` runs with
  host networking only: start the daemon with
  `dockerd --iptables=false --bridge=none` and pass
  `network_mode: host` (see `scripts/docker_pull.py` for the image
  pulls — the daemon's Go TLS handshake is filtered by the egress
  proxy, so base images are pulled with Python and `docker load`ed).
  The compose files themselves are written for normal Docker
  (bridge networking, healthchecks, `depends_on`); the host-network
  mode is a limitation of this VM, not of the release.
- The user verifies the same release on their own machine
  (Windows 11 / WSL2 / Docker Desktop), where bridge networking
  works normally.
