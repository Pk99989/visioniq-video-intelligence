#!/usr/bin/env python3
"""Provision an admin user (Phase 9, H6).

The app has no self-service admin signup (that would be a privilege
escalation hole), so the first admin is created from the server shell:

    # Promote an existing account:
    python scripts/make_admin.py user@example.com
    # Or create the account and make it an admin in one step:
    python scripts/make_admin.py new-admin@example.com --create
    # With an explicit password (otherwise a random one is printed
    # once — change it on first login):
    python scripts/make_admin.py new-admin@example.com --create --password '...'

DATABASE_URL must point at the app database (the script reads the
same env vars as the backend). The script refuses to run against a
database that has no users table (migrations not applied).
"""
import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import SessionLocal, engine  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote or create an admin user.")
    parser.add_argument("email", help="email of the account")
    parser.add_argument("--create", action="store_true",
                        help="create the account if it does not exist")
    parser.add_argument("--password", help="password for a new account "
                        "(a random one is generated and printed if omitted)")
    args = parser.parse_args()

    if "@" not in args.email:
        print(f"error: {args.email!r} is not a valid email", file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        with engine.connect() as conn:
            has_users = "users" in engine.dialect.get_table_names(conn)
        if not has_users:
            print("error: the users table does not exist — run the app "
                  "(it applies Alembic migrations) or `alembic upgrade head` first",
                  file=sys.stderr)
            return 2
        user = db.query(User).filter_by(email=args.email).first()
        if user is None:
            if not args.create:
                print(f"error: no account {args.email!r} — pass --create to make one",
                      file=sys.stderr)
                return 2
            password = args.password or secrets.token_urlsafe(16)
            user = User(email=args.email, password_hash=hash_password(password),
                        role="admin")
            db.add(user)
            db.commit()
            print(f"created admin {args.email}")
            if not args.password:
                print(f"one-time password (change it on first login): {password}")
            return 0
        if user.role == "admin":
            print(f"{args.email} is already an admin")
            return 0
        user.role = "admin"
        db.commit()
        print(f"promoted {args.email} to admin")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
