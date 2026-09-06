#!/usr/bin/env python3
"""Set a Crown user's password.

    python scripts/set_password.py hawk@crown.local

Prompts rather than taking the password as an argument, so it does not end up in
a shell history or a process list.
"""
import argparse
import getpass
import sys

from crown import auth, db


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--dsn", help="override CROWN_DSN")
    args = parser.parse_args(argv)

    password = getpass.getpass("New password (at least 12 characters): ")
    if password != getpass.getpass("Repeat: "):
        print("passwords do not match", file=sys.stderr)
        return 2

    with db.connect(args.dsn) as conn:
        try:
            user_id = auth.set_password(conn, args.email, password)
        except (auth.AuthenticationFailed, ValueError) as exc:
            print(exc, file=sys.stderr)
            return 1
        from crown import audit
        audit.write(conn, audit.new_correlation_id(), "PASSWORD_SET", "app_user",
                    user_id, actor_user_id=user_id, actor_agent="scripts.set_password")
        conn.commit()
    print(f"password set for {args.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
