import requests

from .config import (
    DEFAULT_TOKEN_LIFETIME,
    clear_credentials,
    save_credentials,
)


API_URL = "https://api.borehook.com"


class BoreAuthError(Exception):
    """Raised when BoreHook authentication fails."""


def _get_error_message(response):
    """
    Extract a safe, user-facing error message from an API response.

    This deliberately does not include the API URL or raw HTTP exception.
    """

    try:
        data = response.json()
    except ValueError:
        data = {}

    if isinstance(data, dict):
        message = (
            data.get("message")
            or data.get("detail")
            or data.get("error")
        )

        if isinstance(message, str) and message.strip():
            return message.strip()

    if response.status_code in {401, 403}:
        return (
            "Login failed. Your email/password may be incorrect, "
            "or your account may be suspended or unverified."
        )

    if response.status_code == 429:
        return "Too many login attempts. Please try again later."

    if response.status_code >= 500:
        return (
            "BoreHook is temporarily unavailable. "
            "Please try again later."
        )

    return "Login failed. Please check your details and try again."


def login(
    email,
    password,
    lifetime=DEFAULT_TOKEN_LIFETIME,
):
    """
    Authenticate a user and save the session locally.

    Raises:
        BoreAuthError: If authentication fails.
    """

    try:
        response = requests.post(
            f"{API_URL}/api/accounts/login/",
            json={
                "email": email,
                "password": password,
            },
            timeout=30,
        )

    except requests.Timeout as exc:
        raise BoreAuthError(
            "Unable to reach BoreHook. The request timed out. "
            "Please try again."
        ) from exc

    except requests.ConnectionError as exc:
        raise BoreAuthError(
            "Unable to connect to BoreHook. "
            "Please check your internet connection and try again."
        ) from exc

    except requests.RequestException as exc:
        raise BoreAuthError(
            "An unexpected network error occurred while logging in."
        ) from exc

    if not response.ok:
        raise BoreAuthError(_get_error_message(response))

    try:
        data = response.json()
    except ValueError as exc:
        raise BoreAuthError(
            "BoreHook returned an invalid login response."
        ) from exc

    token = data.get("token")

    if not token:
        raise BoreAuthError(
            "Login succeeded but no authentication token was returned."
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
        True if the token is valid.
        False otherwise.
    """

    try:
        response = requests.get(
            f"{API_URL}/api/accounts/me/",
            headers={
                "Authorization": f"Token {token}",
            },
            timeout=30,
        )

        return response.status_code == 200

    except requests.RequestException:
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
