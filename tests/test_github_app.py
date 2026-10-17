from datetime import datetime, timezone
import io
import json
from urllib.error import HTTPError, URLError

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from foxforge import github_app
from foxforge.github_app import AppConfig, GitHubApp, GitHubAppError


@pytest.fixture(scope="session")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def app_config(tmp_path, monkeypatch, signing_key):
    path = tmp_path / "app.pem"
    path.write_bytes(signing_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    monkeypatch.setenv("FOXFORGE_GITHUB_APP_ID", "123")
    monkeypatch.setenv("FOXFORGE_GITHUB_INSTALLATION_ID", "456")
    monkeypatch.setenv("FOXFORGE_GITHUB_PRIVATE_KEY", str(path))
    return AppConfig.from_env()


def installation():
    return {"id": 456, "app_id": 123, "account": {"login": "owner"}, "suspended_at": None}


def token_response(expires=4600, write=False):
    return {"token": "installation-secret-for-tests-only", "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat(),
            "permissions": {"contents": "write" if write else "read", "pull_requests": "write" if write else "read"},
            "repositories": [{"full_name": "owner/project"}]}


def test_rs256_jwt_claims_and_no_output(app_config, signing_key, monkeypatch, capsys):
    monkeypatch.setattr(github_app.time, "time", lambda: 1000)
    app = GitHubApp(app_config, "owner/project")
    value = app.create_jwt()
    claims = jwt.decode(value, signing_key.public_key(), algorithms=["RS256"], options={"verify_exp": False})
    assert claims == {"iat": 940, "exp": 1540, "iss": "123"}
    assert capsys.readouterr().out == ""
    assert str(app_config.private_key) not in repr(app_config)
    assert value not in repr(app)


def test_exchange_scopes_repository_and_caches_then_refreshes(app_config, monkeypatch):
    clock = [1000]
    monkeypatch.setattr(github_app.time, "time", lambda: clock[0])
    calls = []
    def http(method, path, credential, body=None):
        calls.append((method, path, body))
        return installation() if method == "GET" else token_response(expires=clock[0] + 3600, write=True)
    monkeypatch.setattr(github_app, "_http_json", http)
    app = GitHubApp(app_config, "owner/project", publishing=True)
    assert app.installation_token() == "installation-secret-for-tests-only"
    assert app.installation_token() == "installation-secret-for-tests-only"
    assert len(calls) == 2
    assert calls[-1][2] == {"repositories": ["project"], "permissions": {"contents": "write", "pull_requests": "write"}}
    clock[0] = 4541  # Refresh with less than a minute remaining.
    app.installation_token()
    assert len(calls) == 3
    assert "installation-secret" not in app.token_expiry


def test_failed_refresh_discards_expired_token(app_config, monkeypatch):
    monkeypatch.setattr(github_app.time, "time", lambda: 1000)
    app = GitHubApp(app_config, "owner/project")
    app._token, app._expires_at = "expired-installation-secret", 999
    def fail(*a, **k): raise GitHubAppError("GitHub API failed (HTTP 401)", 401)
    monkeypatch.setattr(github_app, "_http_json", fail)
    with pytest.raises(GitHubAppError):
        app.installation_token()
    assert app._token is None and app.token_expiry is None


@pytest.mark.parametrize("variable", ["FOXFORGE_GITHUB_APP_ID", "FOXFORGE_GITHUB_INSTALLATION_ID", "FOXFORGE_GITHUB_PRIVATE_KEY"])
def test_missing_configuration_fails_closed(app_config, monkeypatch, variable):
    monkeypatch.delenv(variable)
    with pytest.raises(GitHubAppError, match="configuration"):
        AppConfig.from_env()


def test_invalid_key_does_not_echo_private_material(app_config):
    app_config.private_key.write_text("private-material-do-not-echo")
    with pytest.raises(GitHubAppError) as caught:
        GitHubApp(app_config, "owner/project").create_jwt()
    assert "private-material" not in str(caught.value)
    assert str(app_config.private_key) not in str(caught.value)


@pytest.mark.parametrize("change", ["expired", "wrong-scope", "wrong-owner", "bad-permissions"])
def test_bad_token_or_installation_is_rejected(app_config, monkeypatch, change):
    monkeypatch.setattr(github_app.time, "time", lambda: 1000)
    response = token_response()
    install = installation()
    if change == "expired":
        response = token_response(999)
    elif change == "wrong-scope":
        response["repositories"] = [{"full_name": "owner/other"}]
    elif change == "wrong-owner":
        install["account"]["login"] = "other"
    else:
        response["permissions"]["contents"] = "write"
    monkeypatch.setattr(github_app, "_http_json", lambda method, *a, **k: install if method == "GET" else response)
    app = GitHubApp(app_config, "owner/project")
    with pytest.raises(GitHubAppError):
        app.installation_token()
    assert app._token is None


def test_check_repository_and_bot_metadata_are_safe(app_config, monkeypatch):
    monkeypatch.setattr(github_app.time, "time", lambda: 1000)
    def http(method, path, credential, body=None):
        if path == "/app":
            return {"id": 123, "slug": "foxforge"}
        if path.startswith("/users/"):
            return {"id": 987, "login": "foxforge[bot]", "type": "Bot"}
        if path == "/repos/owner/project":
            return {"id": 42, "full_name": "owner/project", "token": "must-not-escape-safe-metadata"}
        return installation() if method == "GET" else token_response()
    monkeypatch.setattr(github_app, "_http_json", http)
    app = GitHubApp(app_config, "owner/project")
    assert app.check_repository() == {"id": 42, "full_name": "owner/project"}
    bot = app.bot_identity()
    assert bot.email == "987+foxforge[bot]@users.noreply.github.com"


def test_read_only_cli_prints_only_safe_metadata(app_config, monkeypatch, capsys):
    monkeypatch.setattr(github_app.time, "time", lambda: 1000)
    def http(method, path, credential, body=None):
        if path == "/repos/owner/project":
            return {"id": 42, "full_name": "owner/project"}
        return installation() if method == "GET" else token_response()
    monkeypatch.setattr(github_app, "_http_json", http)
    assert github_app.main(["--check", "--repository", "owner/project"]) == 0
    output = capsys.readouterr().out
    assert "owner/project" in output and "456" in output and "Token expiry:" in output
    assert "installation-secret" not in output and "PRIVATE KEY" not in output and str(app_config.private_key) not in output


@pytest.mark.parametrize("failure", [HTTPError("https://api.github.com", 401, "secret-in-reason", {}, io.BytesIO(b"secret-in-body")), URLError("secret-in-reason")])
def test_http_errors_never_echo_auth_bodies_or_credentials(monkeypatch, failure):
    class Opener:
        def open(self, *args, **kwargs):
            raise failure
    monkeypatch.setattr(github_app.request, "build_opener", lambda *a: Opener())
    with pytest.raises(GitHubAppError) as caught:
        github_app._http_json("GET", "/app", "test-jwt-secret")
    assert "secret" not in str(caught.value)


def test_transport_uses_header_and_refuses_redirects(monkeypatch):
    seen = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args): return b'{"id": 1}'
    class Opener:
        def open(self, req, **kwargs):
            seen.append(req)
            return Response()
    monkeypatch.setattr(github_app.request, "build_opener", lambda handler: Opener())
    assert github_app._http_json("GET", "/app", "test-jwt-secret") == {"id": 1}
    assert seen[0].get_header("Authorization") == "Bearer test-jwt-secret"
    assert "test-jwt-secret" not in seen[0].full_url
    assert github_app._NoRedirect().redirect_request(None, None, 302, "moved", {}, "https://other.invalid") is None


@pytest.mark.parametrize("write", [False, True])
def test_issue_client_requests_only_explicit_issue_permissions(app_config, monkeypatch, write):
    monkeypatch.setattr(github_app.time, "time", lambda: 1000)
    requested = []
    def http(method, path, credential, body=None):
        if method == "GET":
            return installation()
        requested.append(body)
        response = token_response(write=write)
        response["permissions"]["issues"] = "write" if write else "read"
        return response
    monkeypatch.setattr(github_app, "_http_json", http)
    GitHubApp(app_config, "owner/project", publishing=write, issues=True).installation_token()
    assert requested[0]["permissions"]["issues"] == ("write" if write else "read")
    assert "administration" not in requested[0]["permissions"]


def test_issue_client_rejects_missing_issue_grant(app_config, monkeypatch):
    monkeypatch.setattr(github_app.time, "time", lambda: 1000)
    monkeypatch.setattr(github_app, "_http_json", lambda method, *a, **k: installation() if method == "GET" else token_response(write=True))
    with pytest.raises(GitHubAppError):
        GitHubApp(app_config, "owner/project", publishing=True, issues=True).installation_token()
