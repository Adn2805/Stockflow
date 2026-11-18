"""Provision a local account interactively using the configured PostgreSQL database."""

import argparse
from getpass import getpass

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import User, Username, password_hasher
from app.core.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("role", choices=["admin", "staff", "guest"])
    args = parser.parse_args()
    try:
        username = TypeAdapter(Username).validate_python(args.username)
    except ValidationError:
        parser.error("Username must contain 3–64 letters, digits, dots, underscores, or hyphens.")
    password = getpass("Password: ")
    if not 12 <= len(password) <= 128 or password != getpass("Confirm password: "):
        parser.error("Passwords must match and contain 12–128 characters.")
    engine = create_engine(Settings().database_url.get_secret_value(), hide_parameters=True)
    try:
        with Session(engine) as db, db.begin():
            db.add(User(username=username, password_hash=password_hasher.hash(password), role=args.role))
    except IntegrityError:
        parser.error("Account could not be created. Choose an unused username.")
    finally:
        engine.dispose()
    print(f"Created {args.role} account {username}.")


if __name__ == "__main__":
    main()
