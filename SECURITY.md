# SECURITY

- **Secrets**: only via environment (`.env`, never committed — see
  `.gitignore`). `.env.example` contains placeholders only. No API key,
  password, private video or credential is in this repo.
- **Auth**: PBKDF2-HMAC-SHA256 (200,000 iterations). Access tokens are
  PyJWT HS256 (v0.11.0, H5 — the hand-rolled HMAC JWT is gone): the
  library enforces the algorithm, signature, `exp`, `iat`, `iss`,
  `aud` and `jti`. Tokens minted before v0.11.0 (no iss/aud/iat) are
  rejected — users re-login once after the upgrade. Access tokens
  live 60 minutes (`JWT_EXPIRE_MINUTES`).
- **Refresh tokens (M13, v0.11.0)**: rotating opaque tokens, stored
  SHA-256-hashed, sent as an httpOnly cookie (SameSite=Lax, Secure in
  production, path `/api/v1/auth`, 7 days by default). Each refresh
  revokes the presented token and issues a new one; replaying a
  rotated token revokes the whole token family. Logout revokes both
  the access token (jti blocklist) and the refresh token. The
  frontend retries once on 401 via `/api/v1/auth/refresh`.
- **Rate limits (M5, v0.11.0)**: Redis-backed fixed windows —
  login 10/min per IP+email, register and password-reset-request
  5/min per IP (429 beyond). Without Redis the limiter fails open
  and logs a warning (the laptop profile has no Redis). Set
  `RATE_LIMIT_ENABLED=0` to disable it (e.g. a deployment that rate
  limits upstream).
- **Admin provisioning (H6, v0.11.0)**: no self-service admin signup.
  The first admin is made from the server shell:
  `python scripts/make_admin.py user@example.com` (promote) or
  `... --create` (create + promote). See the script's docstring.
- **Authorisation**: RBAC (user/admin); every video/frame/report access
  checks ownership (admins exempt). Cross-user access returns 404.
  Tested on every video-scoped route (see `tests/test_security.py`).
- **Uploads**: extension allow-list (mp4/mov/webm/mkv/avi) + magic-byte
  sniffing (v0.11.0 — a renamed .txt/.zip is rejected before anything
  is written) + streaming size cap (default 500 MB, 413 beyond).
  Files are stored per-video under `storage/videos/<id>/original.<ext>`,
  never by user-supplied path. Deleting a video deletes its stored
  files. Optional virus scan: set `CLAMSCAN_CMD` (e.g.
  `clamscan --no-summary`); a non-zero exit rejects the upload.
- **VLM SSRF guard (v0.11.0)**: at startup, `VLM_BASE_URL` is
  validated — localhost, `127.0.0.1` and `host.docker.internal` are
  allowed; any other host must resolve to a public IP. Private,
  loopback, link-local (169.254/16, the cloud metadata endpoint) and
  multicast addresses are refused, so a crafted URL cannot make the
  backend call an internal service.
- **Password reset (H1)**: the reset token is never returned in the
  API response unless `DEV_RETURN_RESET_TOKEN=1` AND `ENV` is not
  production. Tokens are single-use, hashed in the DB, 1 h expiry.
  Reset requests always return the same 200 (no email enumeration).
- **Input validation**: Pydantic models on all JSON bodies; multipart
  form fields are typed; query length limits are enforced.
- **Prompt injection**: agent answers are built from retrieved captions
  only; user questions are never executed as instructions, and VLM/LLM
  prompts instruct the model to answer only from the supplied evidence.
  Captions and user text are rendered as data, not as commands, in the
  frontend (React escaping).
- **Known gaps**: the MCP HTTP server trusts a valid backend JWT but
  has no separate scope. The frontend stores the access token in
  localStorage (short-lived, 60 min; the refresh token is the httpOnly
  cookie) — moving the access token out of localStorage is a future
  item (M13 follow-up). No email service is wired yet, so password
  reset tokens are only usable via the dev flag or direct DB access.
- **Reporting**: if you find a vulnerability, do not open a public issue
  with exploit details; contact the repo owner first.
