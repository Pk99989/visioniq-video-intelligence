"""End-to-end browser tests (Phase 3 follow-up).

Drives the real Next.js frontend in Chromium against the real FastAPI
backend, with the real Celery worker processing the upload. This is NOT
run as part of the default suite: it needs three live servers, so it is
skipped unless VISIONIQ_E2E=1 and the app answers on VISIONIQ_APP_URL.

Run the servers first (example, from the repo root):

    # terminal 1 — worker (Redis must be running on localhost:6379)
    cd backend && WORKER_MODE=celery .venv/bin/celery \\
        -A app.services.celery_app.celery_app worker --loglevel=info
    # terminal 2 — backend on :8001
    cd backend && WORKER_MODE=celery .venv/bin/uvicorn app.main:app --port 8001
    # terminal 3 — frontend on :3000, pointed at the backend
    cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8001 npm run build
    cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8001 npm start

Then:  VISIONIQ_E2E=1 .venv/bin/python -m pytest tests/test_e2e_browser.py -q

Flow covered: register -> login -> upload a real video -> wait for the
Celery worker to finish -> search "bus" finds it -> video page shows
Detections -> clip download returns an mp4 -> sign out revokes the
session (login page is shown again).

Requires: playwright + chromium (`pip install playwright &&
python -m playwright install chromium`).
"""
import os
import re
import urllib.request

import pytest

APP_URL = os.environ.get("VISIONIQ_APP_URL", "http://localhost:3000")
API_URL = os.environ.get("VISIONIQ_API_URL", "http://localhost:8001")
VIDEO = os.environ.get(
    "VISIONIQ_SAMPLE_VIDEO",
    str(__import__("pathlib").Path(__file__).resolve().parents[3] / "your_files" / "sample-video-bus.mp4"),
)

pytestmark = pytest.mark.e2e


def _reachable(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def page():
    pytest.importorskip("playwright", reason="playwright not installed")
    if os.environ.get("VISIONIQ_E2E") != "1":
        pytest.skip("set VISIONIQ_E2E=1 to run browser tests")
    if not os.path.exists(VIDEO):
        pytest.skip(f"sample video not found: {VIDEO}")
    if not _reachable(APP_URL):
        pytest.skip(f"frontend not reachable at {APP_URL}")
    if not _reachable(API_URL + "/health"):
        pytest.skip(f"backend not reachable at {API_URL}")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        yield pg
        browser.close()


def test_full_flow_register_upload_search_clip_logout(page):
    import uuid

    # Fresh email every run: a previous run's account makes register
    # return 400 "Email already registered" and the page never navigates.
    email = f"e2e-{uuid.uuid4().hex[:8]}@test.com"
    page.goto(f"{APP_URL}/login")
    page.get_by_placeholder("Email").fill(email)
    page.get_by_placeholder("Password (min 8 characters)").fill("password123")
    page.get_by_role("button", name="Create account").click()
    # Register auto-logs in and routes to the dashboard ("/").
    page.get_by_role("heading", name="Dashboard").wait_for(timeout=15000)

    page.goto(f"{APP_URL}/upload")
    page.get_by_placeholder("Title").fill("e2e bus test")
    page.locator("input[type=file]").set_input_files(VIDEO)
    page.get_by_role("button", name="Upload and process").click()
    page.get_by_text(re.compile(r"Uploaded video #\d+")).wait_for(timeout=15000)
    video_id = re.search(r"#(\d+)", page.get_by_text(re.compile(r"Uploaded video #\d+")).inner_text()).group(1)

    # The Celery worker processes the 10s bus video in ~10-30s on CPU.
    page.goto(f"{APP_URL}/video/{video_id}")
    page.get_by_text("Status: ready").wait_for(timeout=180000)
    page.get_by_text(re.compile(r"Detections \(\d+\)")).wait_for(timeout=15000)
    assert "bus" in page.content().lower()

    page.goto(f"{APP_URL}/search")
    page.get_by_placeholder("Describe what you are looking for…").fill("bus")
    page.get_by_role("button", name="Search").click()
    page.get_by_text(re.compile(r"Score \d+\.\d+")).first.wait_for(timeout=15000)
    assert "bus" in page.content().lower()

    with page.expect_download() as dl_info:
        page.get_by_role("button", name="Download clip (±2s)").first.click()
    download = dl_info.value
    assert download.suggested_filename.endswith(".mp4")

    page.get_by_role("button", name="Sign out").click()
    page.wait_for_url(f"{APP_URL}/login", timeout=15000)
    assert "Sign in to VisionIQ" in page.content()
