# ADR 002 — Never present a fallback as model output

**Context**: fallbacks (template captions, hash embeddings, no YOLO)
could easily be mistaken for real model output in a portfolio project.

**Decision**: every fallback is labelled at the point of use —
caption `provider=fallback` with template wording, `/health` reporting
detection availability, agent Q&A with a score floor and an explicit
no-evidence answer, events verified only on high-confidence detections.

**Consequence**: the demo is honest about what it proves. Enabling a
real model is visible in the same fields (provider name, availability).
