"""VLM provider abstraction. `fallback` never pretends to see: it builds a
template caption from scene timing + detections, labelled provider=fallback.
OpenAI-compatible providers (OpenAI, NVIDIA NIM, Ollama with a vision
model) send the frame image and return real captions. The caller always
records which provider produced each caption."""
import base64
import json
from pathlib import Path

import httpx

from ..config import settings


def provider_name() -> str:
    return settings.VLM_PROVIDER


def _openai_compatible_caption(frame_path: str, prompt: str) -> str | None:
    if not settings.VLM_BASE_URL:
        return None
    image_b64 = base64.b64encode(Path(frame_path).read_bytes()).decode()
    headers = {"Content-Type": "application/json"}
    if settings.VLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.VLM_API_KEY}"
    body = {
        "model": settings.VLM_MODEL or "vision-model",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]}],
        "max_tokens": 300,
    }
    try:
        r = httpx.post(f"{settings.VLM_BASE_URL.rstrip('/')}/chat/completions",
                       json=body, headers=headers, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def caption_scene(scene: dict, detections: list[str], frame_path: str) -> tuple[str, str]:
    """Returns (caption_text, provider). Fallback text is explicitly templated."""
    prompt = ("Describe this video frame briefly: main subjects, actions, setting. "
              "Only describe what is visible; do not invent details.")
    if settings.VLM_PROVIDER in ("openai_compatible", "nvidia_nim", "ollama"):
        text = _openai_compatible_caption(frame_path, prompt)
        if text:
            return text, settings.VLM_PROVIDER
    labels = ", ".join(sorted(set(detections))) if detections else "no tracked objects"
    text = (
        f"Scene {scene['index'] + 1} from {scene['start_seconds']:.1f}s to "
        f"{scene['end_seconds']:.1f}s. Detected: {labels}. "
        f"(Template caption: no vision-language model was configured, so this "
        f"caption is derived from timing and detection metadata only.)"
    )
    return text, "fallback"
