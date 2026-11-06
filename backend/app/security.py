"""Auth: PBKDF2 password hashing + PyJWT (Phase 9, H5). RBAC is
role=user|admin; every video query is additionally scoped to owner_id
(admins exempt).

H5: the hand-rolled HMAC JWT is gone. PyJWT enforces the algorithm
(HS256 only — alg=none and alg confusion are rejected), the signature,
and the registered claims: exp, iat, iss="visioniq", aud="visioniq",
jti. Tokens minted by the old hand-rolled code (no iss/aud/iat) are
rejected — they lived at most 24 h, so a re-login covers the upgrade.

Phase 3: every JWT carries a ``jti`` so logout can revoke it
(RevokedToken table), and video streaming uses a short-lived signed
URL token — the <video> tag cannot send a bearer token, so the signed
URL is how the browser seeks with HTTP Range requests.

Phase 9 (M13): access tokens live 60 minutes. Renewal uses a rotating
opaque refresh token stored hashed in the DB and sent as an httpOnly
cookie (see routers/auth.py).
"""
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import RevokedToken, User

_bearer = HTTPBearer(auto_error=False)

# Claims PyJWT must find on every access token. A token without any of
# these (including every token the old hand-rolled code minted) fails.
_REQUIRED_CLAIMS = ("exp", "iat", "jti")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2$200000${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, _, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_token(user: User) -> str:
    """Short-lived access token (M13: 60 min by default)."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user.id), "email": user.email, "role": user.role,
         "jti": secrets.token_hex(16),
         "iat": now,
         "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
         "iss": settings.JWT_ISSUER, "aud": settings.JWT_AUDIENCE},
        settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Verify an access token. Returns the claims or None. PyJWT
    rejects: wrong/no algorithm (alg=none, alg confusion), bad
    signature, expired tokens, wrong issuer/audience, missing claims."""
    try:
        return jwt.decode(
            token, settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE, issuer=settings.JWT_ISSUER,
            options={"require": _REQUIRED_CLAIMS})
    except Exception:
        return None


def revoke_token(db: Session, user_id: int, jti: str, exp: int) -> None:
    db.add(RevokedToken(jti=jti, user_id=user_id,
                        expires_at=datetime.utcfromtimestamp(exp)))
    db.commit()


def is_revoked(db: Session, jti: Optional[str]) -> bool:
    if not jti:
        return False
    return db.query(RevokedToken).filter_by(jti=jti).first() is not None


def create_stream_token(user: User, video_id: int, minutes: int = 5) -> str:
    """Short-lived signed token for <video src>: payload is
    user_id.video_id.exp, signed with the JWT secret."""
    exp = int(time.time()) + minutes * 60
    payload = f"{user.id}.{video_id}.{exp}"
    sig = hmac.new(settings.JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_stream_token(token: str) -> Optional[tuple[int, int]]:
    try:
        user_id, video_id, exp, sig = token.split(".")
        payload = f"{user_id}.{video_id}.{exp}"
        expect = hmac.new(settings.JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        if int(exp) < time.time():
            return None
        return int(user_id), int(video_id)
    except Exception:
        return None


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    data = decode_token(creds.credentials)
    if not data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if is_revoked(db, data.get("jti")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked (logged out)")
    user = db.get(User, int(data["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def video_visible_to(video, user: User) -> bool:
    return user.role == "admin" or video.owner_id == user.id
