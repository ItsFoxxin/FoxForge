"""GitHub App authentication and API operations. Credentials stay in memory."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib import error, parse, request

from .security import register_secret
from . import __version__


API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")


class GitHubAppError(RuntimeError):
    """Intentionally contains no HTTP bodies, headers, key paths, or credentials."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def repository_name(value: str) -> str:
    if not _REPOSITORY.fullmatch(value) or value.split("/")[1] in {".", ".."}:
        raise GitHubAppError("Repository must be a GitHub owner/name")
    return value


@dataclass(frozen=True)
class AppConfig:
    app_id: int
    installation_id: int
    private_key: Path = field(repr=False)

    @classmethod
    def from_env(cls) -> "AppConfig":
        try:
            app = os.environ["FOXFORGE_GITHUB_APP_ID"]
            installation = os.environ["FOXFORGE_GITHUB_INSTALLATION_ID"]
            key = os.environ["FOXFORGE_GITHUB_PRIVATE_KEY"]
            if not app.isascii() or not app.isdecimal() or int(app) <= 0:
                raise ValueError
            if not installation.isascii() or not installation.isdecimal() or int(installation) <= 0:
                raise ValueError
            path = Path(key).expanduser().resolve()
            if not path.is_file() or path.stat().st_size > 128 * 1024:
                raise ValueError
            return cls(int(app), int(installation), path)
        except (KeyError, ValueError, OSError):
            raise GitHubAppError("Missing or invalid GitHub App environment configuration") from None


@dataclass(frozen=True)
class BotIdentity:
    login: str
    user_id: int

    @property
    def email(self) -> str:
        return f"{self.user_id}+{self.login}@users.noreply.github.com"


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_json(method: str, path: str, credential: str, body=None):
    if not path.startswith("/") or path.startswith("//") or any(ch in path for ch in "\r\n"):
        raise GitHubAppError("Invalid GitHub API path")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(API_ROOT + path, data=data, method=method, headers={
        "Accept": "application/vnd.github+json", "Authorization": "Bearer " + credential,
        "X-GitHub-Api-Version": API_VERSION, "User-Agent": f"FoxForge/{__version__}",
        "Content-Type": "application/json",
    })
    try:
        # Redirects are rejected so Authorization never follows a different URL.
        with request.build_opener(_NoRedirect()).open(req, timeout=20) as response:
            if not 200 <= response.status < 300:
                raise GitHubAppError(f"GitHub API failed (HTTP {response.status})", response.status)
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise GitHubAppError("GitHub API response exceeded its size limit")
            return None if response.status == 204 and not raw else json.loads(raw.decode("utf-8"))
    except error.HTTPError as exc:
        # Never include the body/reason: servers and proxies can echo secrets.
        raise GitHubAppError(f"GitHub API failed (HTTP {exc.code})", exc.code) from None
    except (error.URLError, OSError, ValueError):
        raise GitHubAppError("GitHub API transport or response validation failed") from None


def _positive_id(value) -> bool:
    return type(value) is int and value > 0


class GitHubApp:
    def __init__(self, config: AppConfig, repository: str, *, publishing: bool = False, issues: bool = False):
        self.config = config
        self.repository = repository_name(repository)
        self.publishing = publishing
        self.issues = issues
        self._token: str | None = None
        self._expires_at = 0.0
        self._installation = None

    def create_jwt(self) -> str:
        try:
            import jwt
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
            pem = self.config.private_key.read_bytes()
            key = load_pem_private_key(pem, password=None)
            if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
                raise ValueError
            register_secret(pem.decode("ascii"))
            now = int(time.time())
            value = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": str(self.config.app_id)}, key, algorithm="RS256")
        except (ImportError, OSError, ValueError, TypeError):
            raise GitHubAppError("GitHub App RS256 signing failed; check the private key and PyJWT[crypto] installation") from None
        except Exception:
            # Signing-library errors must not expose key/parser exception data.
            raise GitHubAppError("GitHub App RS256 signing failed") from None
        register_secret(value)
        return value

    def installation(self) -> dict:
        if self._installation is None:
            data = _http_json("GET", f"/app/installations/{self.config.installation_id}", self.create_jwt())
            if not isinstance(data, dict) or not _positive_id(data.get("id")) or not _positive_id(data.get("app_id")) or data.get("id") != self.config.installation_id or data.get("app_id") != self.config.app_id:
                raise GitHubAppError("GitHub installation identity did not match configuration")
            account = data.get("account")
            if not isinstance(account, dict) or str(account.get("login", "")).casefold() != self.repository.split("/")[0].casefold() or data.get("suspended_at"):
                raise GitHubAppError("GitHub installation does not own the expected repository account or is suspended")
            self._installation = data
        return self._installation

    @property
    def token_expiry(self) -> str | None:
        return datetime.fromtimestamp(self._expires_at, timezone.utc).isoformat() if self._token else None

    def installation_token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        self._token, self._expires_at = None, 0.0
        self.installation()
        permissions = {"contents": "write" if self.publishing else "read", "pull_requests": "write" if self.publishing else "read"}
        if self.issues:
            permissions["issues"] = "write" if self.publishing else "read"
        data = _http_json("POST", f"/app/installations/{self.config.installation_id}/access_tokens", self.create_jwt(),
                          {"repositories": [self.repository.split("/")[1]], "permissions": permissions})
        try:
            token = data["token"]
            expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
            granted = data["permissions"]
            if not isinstance(token, str) or not token or len(token) > 4096 or any(ch.isspace() for ch in token):
                raise ValueError
            register_secret(token)
            if expires.tzinfo is None or not time.time() + 60 < expires.timestamp() <= time.time() + 7200:
                raise ValueError
            if not isinstance(granted, dict) or any(granted.get(key) != value for key, value in permissions.items()):
                raise ValueError
            repositories = data.get("repositories")
            if repositories is not None and (not isinstance(repositories, list) or len(repositories) != 1 or str(repositories[0].get("full_name", "")).casefold() != self.repository.casefold()):
                raise ValueError
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise GitHubAppError("GitHub returned an invalid, expired, or incorrectly scoped installation token") from None
        self._token, self._expires_at = token, expires.timestamp()
        return token

    def api(self, method: str, path: str, body=None):
        return _http_json(method, path, self.installation_token(), body)

    def check_repository(self) -> dict:
        self.installation()
        data = self.api("GET", f"/repos/{self.repository}")
        if not isinstance(data, dict) or str(data.get("full_name", "")).casefold() != self.repository.casefold() or not _positive_id(data.get("id")):
            raise GitHubAppError("GitHub did not return the expected accessible repository")
        return {"full_name": data["full_name"], "id": data["id"]}

    def bot_identity(self) -> BotIdentity:
        app = _http_json("GET", "/app", self.create_jwt())
        if not isinstance(app, dict) or not _positive_id(app.get("id")) or app.get("id") != self.config.app_id or not re.fullmatch(r"[A-Za-z0-9-]+", str(app.get("slug", ""))):
            raise GitHubAppError("GitHub returned invalid App identity metadata")
        login = app["slug"] + "[bot]"
        user = self.api("GET", "/users/" + parse.quote(login, safe=""))
        if not isinstance(user, dict) or user.get("login") != login or user.get("type") != "Bot" or not _positive_id(user.get("id")):
            raise GitHubAppError("GitHub returned invalid bot user metadata")
        return BotIdentity(login, user["id"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only GitHub App installation/repository check")
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--repository", required=True, help="Expected owner/name")
    parser.add_argument("--issues", action="store_true", help="Also verify a read-only Issues permission grant")
    args = parser.parse_args(argv)
    try:
        app = GitHubApp(AppConfig.from_env(), args.repository, issues=args.issues)
        metadata = app.check_repository()
        print(f"Repository: {metadata['full_name']}")
        print(f"Installation ID: {app.config.installation_id}")
        print(f"Token expiry: {app.token_expiry}")
        return 0
    except GitHubAppError as exc:
        print(f"GitHub App check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
