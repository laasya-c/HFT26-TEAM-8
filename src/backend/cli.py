"""WILDSCOPE AI — Administrative Command Line Interface.

Provides:
- Secure administrator bootstrap utility.
- Zero predictable default passwords.
- Protection against unintentional overwrites.
- Password complexity verification.
"""
import argparse
import getpass
import sys
import uuid
from typing import Optional

from src.backend.core.exceptions import ValidationException
from src.backend.core.security import hash_password, validate_password_complexity
from src.backend.db.session import SessionLocal
from src.backend.models.auth import User, UserRole


def create_admin_user(
    username: str,
    email: str,
    password: Optional[str] = None,
    full_name: Optional[str] = None,
    force: bool = False,
    db_session=None,
) -> User:
    """Provisions a new administrator account with complexity validation and duplicate guards."""
    clean_username = username.strip()
    clean_email = email.strip().lower()

    if not clean_username or len(clean_username) < 3:
        raise ValidationException("Username must be at least 3 characters long.")
    if "@" not in clean_email or "." not in clean_email:
        raise ValidationException("A valid email address is required.")

    # Secure prompt if password not supplied in non-interactive environment
    if not password:
        pw1 = getpass.getpass("Enter administrator password: ")
        pw2 = getpass.getpass("Confirm administrator password: ")
        if pw1 != pw2:
            raise ValidationException("Password confirmation does not match.")
        password = pw1

    validate_password_complexity(password)

    db = db_session if db_session is not None else SessionLocal()
    should_close = db_session is None

    try:
        existing = (
            db.query(User)
            .filter((User.username == clean_username) | (User.email == clean_email))
            .first()
        )

        if existing:
            if not force:
                raise ValidationException(
                    f"Administrator or user with username '{clean_username}' or email '{clean_email}' already exists. Use --force to overwrite."
                )
            existing.hashed_password = hash_password(password)
            existing.role = UserRole.ADMIN.value
            existing.is_active = True
            if full_name:
                existing.full_name = full_name
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return existing

        hashed_pw = hash_password(password)
        admin = User(
            id=str(uuid.uuid4()),
            username=clean_username,
            email=clean_email,
            hashed_password=hashed_pw,
            full_name=full_name or "System Administrator",
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin
    finally:
        if should_close:
            db.close()


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(description="WILDSCOPE AI Administrative CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-admin command
    admin_parser = subparsers.add_parser("create-admin", help="Bootstrap a new platform administrator")
    admin_parser.add_argument("--username", "-u", required=True, help="Administrator username")
    admin_parser.add_argument("--email", "-e", required=True, help="Administrator email address")
    admin_parser.add_argument("--password", "-p", required=False, default=None, help="Plaintext password (prompts securely if omitted)")
    admin_parser.add_argument("--full-name", "-n", required=False, default=None, help="Administrator full name")
    admin_parser.add_argument("--force", "-f", action="store_true", help="Force overwrite existing administrator account")

    args = parser.parse_args()

    if args.command == "create-admin":
        try:
            admin = create_admin_user(
                username=args.username,
                email=args.email,
                password=args.password,
                full_name=args.full_name,
                force=args.force,
            )
            print(f"[WILDSCOPE Security] Successfully provisioned administrator '{admin.username}' ({admin.email}).")
        except Exception as exc:
            print(f"[WILDSCOPE CLI Error] {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
