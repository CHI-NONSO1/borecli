#borecli/bore/auth.py
import requests

from .config import (DEFAULT_TOKEN_LIFETIME, clear_credentials, save_credentials,)

API_URL = "https://api.borehook.com"



def login(
    email,
    password,
    lifetime=DEFAULT_TOKEN_LIFETIME,
):
    """
    Authenticate a user and save the session locally.
    """

    response = requests.post(
        f"{API_URL}/api/accounts/login/",
        json={
            "email": email,
            "password": password,
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    token = data.get("token")

    if not token:
        raise Exception(
            "Login succeeded but no token was returned."
        )

    save_credentials(
        email=email,
        token=token,
        lifetime=lifetime,
    )

    return {
        "email": email,
        "token": token,
        "lifetime": lifetime,
    }


def verify_token(token):
    """
    Verify token validity against the API.

    Returns:
        True if valid.
        False if invalid.
    """

    try:
        response = requests.get(
            f"{API_URL}/api/accounts/me/",
            headers={
                "Authorization": (
                    f"Token {token}"
                )
            },
            timeout=30,
        )

        return response.status_code == 200

    except Exception:
        return False


def logout():
    """
    Remove locally stored credentials.
    """

    clear_credentials()


def refresh_session(email, token):
    """
    Refresh the saved session timestamp.
    """

    save_credentials(
        email=email,
        token=token,
    )


def get_authenticated_headers(token):
    """
    Return authorization headers for API requests.
    """

    return {
        "Authorization": f"Token {token}",
    }