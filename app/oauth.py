import base64
import hashlib
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class OAuthError(Exception):
    pass


class OAuthEmailConflict(OAuthError):
    pass


PROVIDERS = {
    "google": {
        "client_id": "GOOGLE_CLIENT_ID",
        "client_secret": "GOOGLE_CLIENT_SECRET",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
    },
    "github": {
        "client_id": "GITHUB_CLIENT_ID",
        "client_secret": "GITHUB_CLIENT_SECRET",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
    },
}


def _request_json(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any] | list[Any]:
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OAuthError("OAuth provider request failed") from error
    if not isinstance(payload, (dict, list)):
        raise OAuthError("OAuth provider returned an invalid response")
    return payload


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def create_authorization_url(
    provider: str,
    config: dict[str, Any],
    redirect_uri: str,
    state: str,
    verifier: str,
) -> str:
    details = PROVIDERS[provider]
    client_id = config.get(details["client_id"])
    if not isinstance(client_id, str) or not client_id.strip():
        raise OAuthError(f"{provider.title()} sign-in is not configured")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile" if provider == "google" else "read:user user:email",
        "state": state,
        "code_challenge": _encoded(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
    }
    if provider == "google":
        params["prompt"] = "select_account"
    return f"{details['authorize_url']}?{urllib.parse.urlencode(params)}"


def _exchange_token(
    provider: str,
    config: dict[str, Any],
    code: str,
    redirect_uri: str,
    verifier: str,
) -> str:
    details = PROVIDERS[provider]
    client_id = config.get(details["client_id"])
    client_secret = config.get(details["client_secret"])
    if not isinstance(client_id, str) or not client_id.strip():
        raise OAuthError(f"{provider.title()} sign-in is not configured")
    if not isinstance(client_secret, str) or not client_secret:
        raise OAuthError(f"{provider.title()} sign-in is not configured")

    payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
        }
    ).encode("ascii")
    response = _request_json(
        details["token_url"],
        method="POST",
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "MiniLMS",
        },
    )
    access_token = response.get("access_token") if isinstance(response, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise OAuthError("OAuth provider did not return an access token")
    return access_token


def fetch_profile(
    provider: str,
    config: dict[str, Any],
    code: str,
    redirect_uri: str,
    verifier: str,
) -> dict[str, str]:
    if provider not in PROVIDERS:
        raise OAuthError("Unknown OAuth provider")
    access_token = _exchange_token(provider, config, code, redirect_uri, verifier)
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer " + access_token,
        "User-Agent": "MiniLMS",
    }

    if provider == "google":
        profile = _request_json(
            "https://openidconnect.googleapis.com/v1/userinfo", headers=headers
        )
        if not isinstance(profile, dict):
            raise OAuthError("Google returned an invalid profile")
        subject = profile.get("sub")
        email = profile.get("email")
        verified = profile.get("email_verified") is True
        name = profile.get("name")
    else:
        profile = _request_json("https://api.github.com/user", headers=headers)
        emails = _request_json("https://api.github.com/user/emails", headers=headers)
        if not isinstance(profile, dict) or not isinstance(emails, list):
            raise OAuthError("GitHub returned an invalid profile")
        subject = profile.get("id")
        primary = next(
            (
                item
                for item in emails
                if isinstance(item, dict)
                and item.get("primary") is True
                and item.get("verified") is True
                and isinstance(item.get("email"), str)
            ),
            None,
        )
        email = primary["email"] if primary else None
        verified = primary is not None
        name = profile.get("name") or profile.get("login")

    if not isinstance(subject, (str, int)) or not isinstance(email, str) or not verified:
        raise OAuthError("A verified email address is required")
    normalized_email = email.strip().lower()
    if (
        len(normalized_email) > 254
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email)
    ):
        raise OAuthError("Provider returned an invalid email")
    display_name = name.strip() if isinstance(name, str) else ""
    return {
        "subject": str(subject),
        "email": normalized_email,
        "name": display_name[:100] or normalized_email.split("@", maxsplit=1)[0],
    }


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_verifier() -> str:
    return secrets.token_urlsafe(48)
