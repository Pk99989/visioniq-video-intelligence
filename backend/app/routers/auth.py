import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import PasswordResetToken, RefreshToken, RevokedToken, User
from ..schemas import LoginIn, PasswordResetIn, PasswordResetRequestIn, RegisterIn, TokenOut, UserOut
from ..security import (
    create_token, decode_token, get_current_user, hash_password, hash_token,
    require_admin, revoke_token, verify_password,
)
from ..services.rate_limit import check_rate_limit, ip_bucket, login_bucket

logger = logging.getLogger("visioniq.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_REFRESH_COOKIE = "visioniq_refresh"


def _issue_refresh(db: Session, user: User) -> str:
    """Create a rotating refresh token, store only its hash, return the
    raw value for the httpOnly cookie (M13)."""
    raw = secrets.token_urlsafe(32)
    db.add(RefreshToken(user_id=user.id, token_hash=hash_token(raw),
                        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_DAYS)))
    db.commit()
    return raw


def _set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(_REFRESH_COOKIE, raw, httponly=True,
                        secure=settings.ENV == "production",
                        samesite="lax", path="/api/v1/auth",
                        max_age=settings.REFRESH_TOKEN_DAYS * 86400)


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(_REFRESH_COOKIE, path="/api/v1/auth")


def prune_expired_tokens(db: Session) -> int:
    """Delete expired auth rows (M4): revoked JWTs past expiry,
    password-reset tokens that are used or expired, and refresh tokens
    that are expired or revoked. Called at app startup; returns how
    many rows were removed. Never touches a token that is still valid."""
    now = datetime.utcnow()
    expired_revoked = (db.query(RevokedToken)
                       .filter(RevokedToken.expires_at < now)
                       .delete(synchronize_session=False))
    expired_resets = (db.query(PasswordResetToken)
                      .filter((PasswordResetToken.expires_at < now)
                              | (PasswordResetToken.used.is_(True)))
                      .delete(synchronize_session=False))
    expired_refresh = (db.query(RefreshToken)
                       .filter((RefreshToken.expires_at < now)
                               | (RefreshToken.revoked_at.isnot(None)))
                       .delete(synchronize_session=False))
    db.commit()
    return expired_revoked + expired_resets + expired_refresh


@router.post("/register", response_model=UserOut, status_code=201)
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)):
    if not check_rate_limit(request, ip_bucket(request, "register"),
                            settings.RATE_LIMIT_REGISTER_PER_MINUTE):
        raise HTTPException(429, "Too many registrations from this address — try again in a minute")
    if "@" not in body.email or db.query(User).filter_by(email=body.email).first():
        raise HTTPException(400, "Email already registered or invalid")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
def login(request: Request, response: Response, body: LoginIn,
          db: Session = Depends(get_db)):
    if not check_rate_limit(request, login_bucket(request, body.email),
                            settings.RATE_LIMIT_LOGIN_PER_MINUTE):
        raise HTTPException(429, "Too many login attempts for this account — try again in a minute")
    user = db.query(User).filter_by(email=body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    _set_refresh_cookie(response, _issue_refresh(db, user))
    return TokenOut(access_token=create_token(user), token_type="bearer",
                    user=UserOut.model_validate(user))


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Exchange the httpOnly refresh cookie for a new access token.
    Rotation: the presented token is revoked and a new one is issued,
    so a replayed token is useless. If a token that was already
    revoked by rotation is presented again, the whole token family is
    compromised — all of the user's refresh tokens are revoked."""
    raw = request.cookies.get(_REFRESH_COOKIE)
    if not raw:
        raise HTTPException(401, "No refresh token")
    rec = db.query(RefreshToken).filter_by(token_hash=hash_token(raw)).first()
    if not rec:
        raise HTTPException(401, "Invalid refresh token")
    if rec.revoked_at is not None:
        # Replay of a rotated token: revoke the whole family.
        db.query(RefreshToken).filter_by(user_id=rec.user_id).update(
            {"revoked_at": datetime.utcnow()}, synchronize_session=False)
        db.commit()
        logger.warning("refresh token replay for user_id=%s — all tokens revoked", rec.user_id)
        raise HTTPException(401, "Refresh token already used")
    if rec.expires_at < datetime.utcnow():
        raise HTTPException(401, "Refresh token expired")
    user = db.get(User, rec.user_id)
    if not user:
        raise HTTPException(401, "Invalid refresh token")
    rec.revoked_at = datetime.utcnow()
    db.commit()
    _set_refresh_cookie(response, _issue_refresh(db, user))
    return TokenOut(access_token=create_token(user), token_type="bearer",
                    user=UserOut.model_validate(user))


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    # get_current_user validates the token but does not hand it back,
    # so read the raw Authorization header here to revoke its jti.
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    data = decode_token(token)
    if not data or not data.get("jti"):
        raise HTTPException(401, "Invalid or expired token")
    revoke_token(db, user.id, data["jti"], data["exp"])
    # Also revoke this session's refresh token (M13).
    raw = request.cookies.get(_REFRESH_COOKIE)
    if raw:
        rec = db.query(RefreshToken).filter_by(token_hash=hash_token(raw)).first()
        if rec and rec.revoked_at is None:
            rec.revoked_at = datetime.utcnow()
            db.commit()
    _clear_refresh_cookie(response)
    return {"detail": "Logged out. This token will no longer work."}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/password-reset-request")
def password_reset_request(request: Request, body: PasswordResetRequestIn,
                           db: Session = Depends(get_db)):
    if not check_rate_limit(request, ip_bucket(request, "reset"),
                            settings.RATE_LIMIT_RESET_PER_MINUTE):
        raise HTTPException(429, "Too many reset requests from this address — try again in a minute")
    """Always returns 200 so an attacker cannot tell whether an email
    is registered. The reset token is NEVER returned in the response
    unless the dev-only flag DEV_RETURN_RESET_TOKEN=1 is set (and ENV
    is not production) — returning it would let anyone reset any
    account's password with no email access (audit H1). Without the
    flag, the token is created and stored hashed; a real deployment
    must email it to the user (no email service is wired yet — the
    token is then only usable by someone with direct DB access)."""
    user = db.query(User).filter_by(email=body.email).first()
    if user:
        raw = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(user_id=user.id, token_hash=hash_token(raw),
                                  expires_at=datetime.utcnow() + timedelta(hours=1)))
        db.commit()
        if settings.DEV_RETURN_RESET_TOKEN and settings.ENV != "production":
            logger.warning("DEV ONLY: password-reset token returned in response "
                           "for user_id=%s (DEV_RETURN_RESET_TOKEN=1)", user.id)
            return {"detail": "If that email is registered, a reset token was created.",
                    "reset_token": raw, "expires_in_minutes": 60}
        logger.info("password-reset requested for user_id=%s; token created "
                    "(not returned — no email service configured)", user.id)
    return {"detail": "If that email is registered, a reset token was created."}


@router.post("/password-reset")
def password_reset(body: PasswordResetIn, db: Session = Depends(get_db)):
    rec = db.query(PasswordResetToken).filter_by(token_hash=hash_token(body.token)).first()
    if not rec or rec.used or rec.expires_at < datetime.utcnow():
        raise HTTPException(400, "Invalid or expired reset token")
    user = db.get(User, rec.user_id)
    if not user:
        raise HTTPException(400, "Invalid or expired reset token")
    user.password_hash = hash_password(body.new_password)
    rec.used = True
    db.commit()
    return {"detail": "Password has been reset. Please sign in with the new password."}


@router.get("/users", response_model=list[UserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(User).all()
