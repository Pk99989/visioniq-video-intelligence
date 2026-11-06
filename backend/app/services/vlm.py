"""VLM provider abstraction (Phase 1 upgrade, v0.4.0).

Caption provenance is a first-class fact: every caption records which
tier produced it, and the text itself says so. The three tiers are:

- VLM (`ollama` / `openai_compatible` / `nvidia_nim`): a real
  vision-language model describes the frame. The model is asked for
  structured JSON (description, objects, actions); malformed output
  falls back to the model's raw text, never to invented structure.
- `detection`: no VLM answered, but YOLO saw objects. The caption is
  built from detection labels only and says so.
- `fallback`: no VLM and no detections. A template from scene timing
  only, labelled as such.

Template captions are never presented as VLM output.

Reliability: per-attempt timeout (VLM_TIMEOUT_SECONDS), retries with
exponential backoff (VLM_MAX_RETRIES), a health check
(`check_health()`), and structured inference logs on
`visioniq.vlm` (model, latency, attempts, outcome) so a failed model
is visible instead of silently degrading to templates.
"""
import base64
import json
import logging
import re
import time
from pathlib import Path

import httpx

from ..config import settings

logger = logging.getLogger("visioniq.vlm")

_JSON_PROMPT = (
    "Describe this video frame as JSON only, no other text. "
    "Schema: {\"description\": \"one or two sentences: main subjects, actions, setting\", "
    "\"objects\": [\"visible object labels\"], "
    "\"actions\": [\"visible actions\"]}. "
    "Only describe what is actually visible; do not invent details. "
    "If nothing is clearly visible, use empty lists and say so in the description."
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def provider_name() -> str:
    return settings.VLM_PROVIDER


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.search(text.strip())
    return m.group(1) if m else text.strip()


def _parse_structured(text: str) -> dict | None:
    """Parse the model's JSON. Returns {"description", "objects",
    "actions"} or None when the output is not usable JSON. Never raises."""
    try:
        data = json.loads(_strip_fences(text))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        return None
    objects = data.get("objects") or []
    actions = data.get("actions") or []
    return {
        "description": description.strip(),
        "objects": [str(o) for o in objects if isinstance(o, str)][:20],
        "actions": [str(a) for a in actions if isinstance(a, str)][:20],
    }


def _ask_vlm(frame_path: str, prompt: str, max_tokens: int = 400) -> str | None:
    """One VLM call with retries for an arbitrary text prompt. Returns
    the model's raw reply text, or None when it never answered
    usefully. Never raises."""
    if not settings.VLM_BASE_URL:
        return None
    try:
        image_b64 = base64.b64encode(Path(frame_path).read_bytes()).decode()
    except OSError as exc:
        logger.warning("vlm frame unreadable path=%s error=%s", frame_path, exc)
        return None
    headers = {"Content-Type": "application/json"}
    if settings.VLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.VLM_API_KEY}"
    body = {
        "model": settings.VLM_MODEL or "vision-model",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]}],
        "max_tokens": max_tokens,
    }
    attempts = 1 + max(0, settings.VLM_MAX_RETRIES)
    last_error = "no attempt"
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            # trust_env=False: httpx parses NO_PROXY from the environment,
            # and some runtimes export bracketed IPv6 entries there that
            # httpx rejects (InvalidURL: Invalid port ':1]'), breaking even
            # local Ollama calls. VisionIQ talks to the VLM directly.
            with httpx.Client(trust_env=False, timeout=settings.VLM_TIMEOUT_SECONDS) as client:
                r = client.post(f"{settings.VLM_BASE_URL.rstrip('/')}/chat/completions",
                                json=body, headers=headers)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"] or ""
            latency_ms = int((time.monotonic() - started) * 1000)
            raw = content.strip()
            if raw:
                logger.info("vlm ok model=%s latency_ms=%d attempts=%d",
                            settings.VLM_MODEL, latency_ms, attempt)
                return raw
            last_error = "empty response"
        except (httpx.TimeoutException, httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            latency_ms = int((time.monotonic() - started) * 1000)
            logger.warning("vlm attempt %d/%d failed model=%s latency_ms=%d error=%s",
                           attempt, attempts, settings.VLM_MODEL, latency_ms, last_error)
        if attempt < attempts:
            time.sleep(settings.VLM_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    logger.error("vlm failed model=%s attempts=%d last_error=%s",
                 settings.VLM_MODEL, attempts, last_error)
    return None


def _describe_with_vlm(frame_path: str) -> dict | None:
    """One VLM caption call. Returns the parsed structure, or the
    model's raw text as an unstructured description when JSON parsing
    fails, or None when the model never answered usefully."""
    content = _ask_vlm(frame_path, _JSON_PROMPT)
    if content is None:
        return None
    parsed = _parse_structured(content)
    if parsed is not None:
        logger.info("vlm structured=true")
        return parsed
    raw = content.strip()
    if raw:
        logger.info("vlm structured=false (malformed JSON, using raw text)")
        return {"description": raw, "objects": [], "actions": []}
    return None


def ask_yes_no(frame_path: str, question: str) -> bool | None:
    """Ask the VLM a yes/no question about one frame (Phase 6 event
    verification). Returns True for YES, False for NO, None when the
    model did not answer or its answer was not a clear yes/no. The
    prompt forces a single-word answer so small models stay parseable;
    a "yes, ..." prefix still counts as yes."""
    if settings.VLM_PROVIDER == "fallback" or not settings.VLM_BASE_URL:
        return None
    prompt = (
        "Answer with only one word, YES or NO. "
        f"{question} "
        "Only answer from what is actually visible in the image; "
        "if you cannot tell, answer NO."
    )
    reply = _ask_vlm(frame_path, prompt, max_tokens=10)
    if reply is None:
        return None
    first = reply.strip().lower().split()[0].strip(".,!?:;") if reply.strip() else ""
    if first == "yes":
        return True
    if first == "no":
        return False
    logger.warning("vlm yes/no unparseable reply=%r", reply[:80])
    return None


def _detection_caption(scene: dict, detections: list[str]) -> str:
    labels = ", ".join(sorted(set(detections)))
    return (
        f"Scene {scene['index'] + 1} from {scene['start_seconds']:.1f}s to "
        f"{scene['end_seconds']:.1f}s. Detected: {labels}. "
        f"(Detection description: no vision-language model answered, so this "
        f"caption lists only the objects the detector saw.)"
    )


def _template_caption(scene: dict) -> str:
    return (
        f"Scene {scene['index'] + 1} from {scene['start_seconds']:.1f}s to "
        f"{scene['end_seconds']:.1f}s. Detected: no tracked objects. "
        f"(Template caption: no vision-language model was configured and no "
        f"objects were detected, so this caption is derived from timing "
        f"metadata only.)"
    )


def caption_scene(scene: dict, detections: list[str], frame_path: str) -> tuple[str, str]:
    """Returns (caption_text, provider). Provider is the VLM provider
    name on real model output, else 'detection' or 'fallback'."""
    if settings.VLM_PROVIDER in ("openai_compatible", "nvidia_nim", "ollama"):
        result = _describe_with_vlm(frame_path)
        if result is not None:
            text = result["description"]
            if result["objects"]:
                text += " Visible: " + ", ".join(result["objects"]) + "."
            if result["actions"]:
                text += " Actions: " + ", ".join(result["actions"]) + "."
            return text, settings.VLM_PROVIDER
    if detections:
        return _detection_caption(scene, detections), "detection"
    return _template_caption(scene), "fallback"


def check_health() -> dict:
    """Probe the configured VLM. Returns status ok/error/disabled plus
    latency; never raises, never leaks the API key."""
    provider = settings.VLM_PROVIDER
    if provider == "fallback" or not settings.VLM_BASE_URL:
        return {"status": "disabled", "provider": provider,
                "model": settings.VLM_MODEL or None,
                "detail": "No VLM configured (VLM_PROVIDER=fallback); captions are templates."}
    started = time.monotonic()
    try:
        with httpx.Client(trust_env=False, timeout=settings.VLM_HEALTH_TIMEOUT_SECONDS) as client:
            r = client.get(f"{settings.VLM_BASE_URL.rstrip('/')}/models")
            r.raise_for_status()
            models = [m.get("id") for m in r.json().get("data", []) if isinstance(m, dict)]
    except Exception as exc:  # noqa: BLE001 - health must report, not raise
        return {"status": "error", "provider": provider,
                "model": settings.VLM_MODEL or None,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "detail": f"{type(exc).__name__}: {exc}"}
    latency_ms = int((time.monotonic() - started) * 1000)
    model = settings.VLM_MODEL or None
    # Ollama lists models with a tag ("moondream:latest"); the
    # configured name is often bare ("moondream"). Match either.
    available = (model is None or not models
                 or any(m == model or m.startswith(model + ":") for m in models))
    return {"status": "ok" if available else "error", "provider": provider,
            "model": model, "latency_ms": latency_ms,
            "models_seen": models[:10],
            "detail": ("Model listed by the server." if available
                       else f"Model {model!r} is not in the server's model list.")}
