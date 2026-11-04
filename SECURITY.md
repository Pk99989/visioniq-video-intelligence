# SECURITY

- **Secrets**: only via environment (`.env`, never committed — see
  `.gitignore`). `.env.example` contains placeholders only. No API key,
  password, private video or credential is in this repo.
- **Auth**: PBKDF2-HMAC-SHA256 (200,000 iterations), HMAC-SHA256 JWT
  with expiry (`JWT_EXPIRE_MINUTES`, default 1440). Login is rate-limited
  (30 attempts/min/IP, 429 beyond).
- **Authorisation**: RBAC (user/admin); every video/frame/report access
  checks ownership (admins exempt). Cross-user access returns 404.
- **Uploads**: extension allow-list (mp4/mov/webm/mkv/avi) + streaming
  size cap (default 500 MB). Files are stored per-video under
  `storage/videos/<id>/`, never by user-supplied path. Deleting a video
  deletes its stored files.
- **Input validation**: Pydantic models on all JSON bodies; multipart
  form fields are typed; query length limits are enforced.
- **Prompt injection**: agent answers are built from retrieved captions
  only; user questions are never executed as instructions, and VLM/LLM
  prompts instruct the model to answer only from the supplied evidence.
  Captions and user text are rendered as data, not as commands, in the
  frontend (React escaping).
- **Known gaps**: JWTs are not revoked on logout (sign-out = delete the
  browser token); there is no refresh-token rotation yet; the MCP HTTP
  server trusts a valid backend JWT but has no separate scope. File
  type is checked by extension + ffprobe success, not by deep magic-byte
  sniffing — a future hardening item.
- **Reporting**: if you find a vulnerability, do not open a public issue
  with exploit details; contact the repo owner first.
