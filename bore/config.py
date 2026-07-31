# borecli/bore/config.py
import json
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".bore"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Local session lifetime (1 hour)
DEFAULT_TOKEN_LIFETIME = 3600  # 1 hour


def save_credentials(email, token, lifetime=DEFAULT_TOKEN_LIFETIME):
    """
    Save user credentials locally.

    lifetime is in seconds.
    """

    CONFIG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = time.time()

    with open(
        CONFIG_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            {
                "email": email,
                "token": token,
                "saved_at": now,
                "expires_at": now + lifetime,
            },
            file,
            indent=4,
        )


def load_credentials():
    """
    Load credentials if they have not expired.
    """

    if not CONFIG_FILE.exists():
        return None

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        expires_at = data.get("expires_at")

        # Backward compatibility
        if expires_at is None:
            saved_at = data.get("saved_at", 0)
            expires_at = saved_at + DEFAULT_TOKEN_LIFETIME

        if time.time() >= expires_at:
            clear_credentials()
            return None

        return data

    except Exception:
        return None


def clear_credentials():
    """
    Remove stored credentials.
    """

    try:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()

    except Exception:
        pass


def get_token():
    """
    Return saved token.
    """

    credentials = load_credentials()

    if not credentials:
        return None

    return credentials.get("token")


def get_email():
    """
    Return saved email.
    """

    credentials = load_credentials()

    if not credentials:
        return None

    return credentials.get("email")


def is_authenticated():
    """
    Check whether a valid session exists.
    """

    return load_credentials() is not None


def get_remaining_session_time():
    """
        Return remaining session lifetime in seconds.
        Returns 0 if expired.
    """
    credentials = load_credentials()

    if not credentials:
        return 0

    expires_at = credentials["expires_at"]

    return max(0, int(expires_at - time.time()))