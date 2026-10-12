"""Explicit local account bootstrap; no public registration endpoint."""
import argparse
import getpass

from sqlalchemy import select

from .config import Settings
from .db import database
from .identity import LoginInput, Profile, User, password_hasher


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create-user"])
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password (at least 12 characters): ")
    if len(password) < 12 or len(password) > 256:
        raise SystemExit("Password must contain 12–256 characters")
    if getpass.getpass("Repeat password: ") != password:
        raise SystemExit("Passwords do not match")
    email = LoginInput(email=args.email, password=password).email
    engine, sessions = database(Settings.from_env().database_url)
    with sessions() as db:
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit("Account already exists")
        user = User(email=email, password_hash=password_hasher.hash(password))
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id, data={}))
        db.commit()
    engine.dispose()
    print("Account created. You can sign in now.")


if __name__ == "__main__":
    main()
