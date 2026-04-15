"""
Dhan Authentication Helper — Generate access token using PIN + TOTP.

The access token is needed for all Dhan API calls.
It must be regenerated periodically (tokens expire).

Usage:
    python -m scripts.dhan_auth

You'll need:
    - Your Dhan Client ID (in config/.env as DHAN_CLIENT_ID)
    - Your Dhan PIN (trading PIN)
    - Your TOTP code (from authenticator app)

After running, this script updates config/.env with the fresh access token.
"""

import os
import sys
import getpass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.dhan_client import _load_env

ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", ".env"
)


def generate_token():
    """Interactive token generation."""
    _load_env()
    client_id = os.environ.get("DHAN_CLIENT_ID", "")

    if not client_id or client_id == "your_client_id_here":
        print("Set DHAN_CLIENT_ID in jack/config/.env first.")
        return

    print(f"Client ID: {client_id}")
    print()

    try:
        from dhanhq import DhanLogin
    except ImportError:
        print("Install dhanhq: pip install dhanhq")
        return

    login = DhanLogin(client_id)

    pin = getpass.getpass("Enter your Dhan PIN: ")
    totp = input("Enter your TOTP code: ").strip()

    try:
        result = login.generate_token(pin, totp)
        if isinstance(result, dict) and result.get("status") == "success":
            token = result.get("data", {}).get("access_token", "")
            if token:
                _update_env(token)
                print(f"\nAccess token saved to {ENV_PATH}")
                print(f"Token prefix: {token[:20]}...")
                return
        print(f"\nToken generation failed: {result}")
    except Exception as e:
        print(f"\nError: {e}")
        print("\nAlternatively, get your access token from https://api.dhan.co")
        print("and paste it directly into jack/config/.env as DHAN_ACCESS_TOKEN")


def _update_env(token: str):
    """Update the access token in .env file."""
    if not os.path.exists(ENV_PATH):
        return

    lines = []
    with open(ENV_PATH, "r") as f:
        for line in f:
            if line.strip().startswith("DHAN_ACCESS_TOKEN="):
                lines.append(f"DHAN_ACCESS_TOKEN={token}\n")
            else:
                lines.append(line)

    with open(ENV_PATH, "w") as f:
        f.writelines(lines)


if __name__ == "__main__":
    generate_token()
