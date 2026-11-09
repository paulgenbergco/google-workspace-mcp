"""
Remote (HTTP) mode: serve the same MCP server over Streamable HTTP, behind OAuth.

    python server.py --http

This is what lets claude.ai (chat, Cowork, and cloud Claude Code sessions) use
the server as a custom connector. claude.ai is the OAuth client; this module is
the authorization server. It does not keep passwords. Signing in is delegated
to Google ("Sign in with Google"), and only the addresses listed in
config.json -> remote.allowed_emails get a token.

Flow, end to end:

    claude.ai --/register-->  here    (dynamic client registration)
    claude.ai --/authorize--> here --302--> accounts.google.com
    Google    --/oauth/google/callback--> here  (checks email allowlist)
    here      --302 code--> claude.ai --/token--> here  (access + refresh token)
    claude.ai --/mcp, Bearer <token>--> here

The Google sign-in here is identity only (scope "openid email"). It is a
separate OAuth client from credentials/client_secret.json, and it never touches
the per-account Gmail/Drive tokens in credentials/tokens/.

State that must survive a restart (registered clients, refresh tokens, access
tokens) lives in credentials/remote_state.json, mode 0600. Tokens are stored
as SHA-256 hashes, never in the clear.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    ProviderTokenVerifier,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    create_auth_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

MCP_PATH = "/mcp"
GOOGLE_CALLBACK_PATH = "/oauth/google/callback"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

ACCESS_TOKEN_TTL = 60 * 60            # 1 hour; claude.ai refreshes on its own
REFRESH_TOKEN_TTL = 60 * 60 * 24 * 30  # 30 days, rotated on every use
AUTH_CODE_TTL = 5 * 60
PENDING_LOGIN_TTL = 10 * 60
MAX_CLIENTS = 50

# Where claude.ai sends the user back after sign-in. Registration is open
# (that is how claude.ai connects), so without this list anyone could register
# a client pointing at their own site, send you a crafted /authorize link, and
# collect a token for all your inboxes the moment your browser's Google session
# auto-completes the login. Loopback is allowed for Claude Code's local OAuth
# callback, which only the machine running it can receive.
DEFAULT_ALLOWED_REDIRECTS = [
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
]
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


def _log(msg: str) -> None:
    print(f"[remote] {msg}", file=sys.stderr, flush=True)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass
class RemoteSettings:
    public_url: str
    allowed_emails: set[str]
    google_client_id: str
    google_client_secret: str
    state_path: Path
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_redirect_uris: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_REDIRECTS))

    @property
    def google_redirect_uri(self) -> str:
        return self.public_url + GOOGLE_CALLBACK_PATH

    @property
    def mcp_url(self) -> str:
        return self.public_url + MCP_PATH


def load_settings(config: dict[str, Any], credentials_dir: Path) -> RemoteSettings:
    """Read config.json's "remote" block and the Google sign-in client file.

    Raises ValueError with a fix-it message for anything missing, so a bad
    setup fails at startup rather than at the first sign-in.
    """
    remote = config.get("remote")
    if not isinstance(remote, dict):
        raise ValueError(
            'config.json has no "remote" block. Add one, e.g.\n'
            '  "remote": {"public_url": "https://<host>", "allowed_emails": ["you@example.com"]}'
        )

    public_url = str(remote.get("public_url", "")).rstrip("/")
    parsed = urlparse(public_url)
    if parsed.scheme != "https" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError(f"remote.public_url must be an https:// URL (got {public_url!r}).")
    if parsed.path not in ("", "/"):
        raise ValueError("remote.public_url must be the bare origin, e.g. https://host (no path).")

    emails = {str(e).strip().lower() for e in remote.get("allowed_emails", []) if str(e).strip()}
    if not emails:
        raise ValueError("remote.allowed_emails is empty, so nobody could sign in. Add your address.")

    client_file = credentials_dir / remote.get("google_client_file", "remote_client_secret.json")
    if not client_file.exists():
        raise ValueError(
            f"Google sign-in client not found at {client_file}.\n"
            "Create a 'Web application' OAuth client in Google Cloud Console with redirect URI\n"
            f"  {public_url}{GOOGLE_CALLBACK_PATH}\n"
            "and save its JSON there."
        )
    data = json.loads(client_file.read_text())
    web = data.get("web")
    if not web:
        kind = next(iter(data), "unknown")
        raise ValueError(
            f"{client_file.name} is a '{kind}' OAuth client. It must be a 'Web application' "
            "client: desktop clients cannot redirect to a public https URL."
        )
    if f"{public_url}{GOOGLE_CALLBACK_PATH}" not in web.get("redirect_uris", []):
        _log(
            f"WARNING: {client_file.name} does not list {public_url}{GOOGLE_CALLBACK_PATH} as a "
            "redirect URI; Google will refuse the sign-in until it does."
        )

    redirects = remote.get("allowed_redirect_uris") or list(DEFAULT_ALLOWED_REDIRECTS)

    return RemoteSettings(
        public_url=public_url,
        allowed_emails=emails,
        google_client_id=web["client_id"],
        google_client_secret=web["client_secret"],
        state_path=credentials_dir / "remote_state.json",
        host=str(remote.get("host", "127.0.0.1")),
        port=int(remote.get("port", 8765)),
        allowed_redirect_uris=[str(u) for u in redirects],
    )


def redirect_allowed(uri: str, allowed: list[str]) -> bool:
    """Exact match against the allowlist, or any port on a loopback http URL."""
    if uri in allowed:
        return True
    p = urlparse(uri)
    return p.scheme == "http" and p.hostname in _LOOPBACK_HOSTS


# ---------------------------------------------------------------------------
# Persistent state
# ---------------------------------------------------------------------------


class StateStore:
    """Tiny JSON-file store. One process, low volume: a lock and an atomic rename suffice."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, dict[str, Any]] = {"clients": {}, "access": {}, "refresh": {}}
        if path.exists():
            loaded = json.loads(path.read_text())
            for key in self.data:
                self.data[key] = loaded.get(key, {})
        self.prune()

    def prune(self) -> None:
        now = time.time()
        with self._lock:
            for kind in ("access", "refresh"):
                self.data[kind] = {
                    k: v for k, v in self.data[kind].items() if v.get("expires_at", 0) > now
                }
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(self.data, fh, indent=1)
        os.replace(tmp, self.path)

    def put(self, kind: str, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self.data[kind][key] = value
            if kind == "clients" and len(self.data["clients"]) > MAX_CLIENTS:
                oldest = sorted(self.data["clients"].items(), key=lambda kv: kv[1].get("client_id_issued_at") or 0)
                for cid, _ in oldest[: len(self.data["clients"]) - MAX_CLIENTS]:
                    del self.data["clients"][cid]
            self._save()

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self.data[kind].get(key)

    def pop(self, kind: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            value = self.data[kind].pop(key, None)
            if value is not None:
                self._save()
            return value

    def drop_where(self, kind: str, pred) -> None:
        with self._lock:
            self.data[kind] = {k: v for k, v in self.data[kind].items() if not pred(v)}
            self._save()


# ---------------------------------------------------------------------------
# OAuth authorization server, with Google as the identity provider
# ---------------------------------------------------------------------------


@dataclass
class _PendingLogin:
    client_id: str
    params: AuthorizationParams
    created: float


class GoogleLoginProvider:
    """Implements mcp's OAuthAuthorizationServerProvider protocol."""

    def __init__(self, settings: RemoteSettings):
        self.s = settings
        self.store = StateStore(settings.state_path)
        self._pending: dict[str, _PendingLogin] = {}
        self._codes: dict[str, AuthorizationCode] = {}

    # ---- clients ----------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        raw = self.store.get("clients", client_id)
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        bad = [str(u) for u in client_info.redirect_uris or [] if not redirect_allowed(str(u), self.s.allowed_redirect_uris)]
        if bad:
            _log(f"refused client registration with redirect_uris {bad}")
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description=f"redirect_uri not allowed by this server: {', '.join(bad)}",
            )
        self.store.put("clients", client_info.client_id, client_info.model_dump(mode="json"))
        _log(f"registered client {client_info.client_id} ({client_info.client_name or 'unnamed'})")

    # ---- authorize: hand off to Google -------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not redirect_allowed(str(params.redirect_uri), self.s.allowed_redirect_uris):
            raise AuthorizeError(error="invalid_request", error_description="redirect_uri not allowed")
        self._sweep()
        txn = secrets.token_urlsafe(32)
        self._pending[txn] = _PendingLogin(client.client_id, params, time.time())
        return GOOGLE_AUTH_URL + "?" + urlencode({
            "client_id": self.s.google_client_id,
            "redirect_uri": self.s.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email",
            "state": txn,
            # Always show the account chooser, so a token is never minted
            # silently off a browser session that happens to be signed in.
            "prompt": "select_account",
            "access_type": "online",
        })

    async def google_callback(self, request: Request) -> Response:
        txn = request.query_params.get("state", "")
        pending = self._pending.pop(txn, None)
        if pending is None or time.time() - pending.created > PENDING_LOGIN_TTL:
            return _page("Sign-in expired", "Start the connection again from Claude.", 400)

        params = pending.params
        if err := request.query_params.get("error"):
            return RedirectResponse(construct_redirect_uri(
                str(params.redirect_uri), error="access_denied", error_description=f"Google: {err}", state=params.state,
            ), status_code=302)

        try:
            email = await self._google_identity(request.query_params.get("code", ""))
        except Exception as exc:  # network, bad code, bad id_token
            _log(f"Google sign-in failed: {exc!r}")
            return _page("Google sign-in failed", "Could not verify your Google identity. Try again.", 502)

        if email not in self.s.allowed_emails:
            _log(f"refused sign-in from {email} (not in remote.allowed_emails)")
            return RedirectResponse(construct_redirect_uri(
                str(params.redirect_uri), error="access_denied",
                error_description=f"{email} is not allowed on this server", state=params.state,
            ), status_code=302)

        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or ["mcp"],
            expires_at=time.time() + AUTH_CODE_TTL,
            client_id=pending.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject=email,
        )
        _log(f"signed in {email} for client {pending.client_id}")
        return RedirectResponse(
            construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state), status_code=302
        )

    async def _google_identity(self, code: str) -> str:
        """Exchange Google's code and return the verified, lower-cased email."""
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": self.s.google_client_id,
                "client_secret": self.s.google_client_secret,
                "redirect_uri": self.s.google_redirect_uri,
                "grant_type": "authorization_code",
            })
        resp.raise_for_status()
        raw_id_token = resp.json()["id_token"]

        def verify() -> dict[str, Any]:
            from google.auth.transport.requests import Request as GoogleRequest
            from google.oauth2 import id_token

            return id_token.verify_oauth2_token(raw_id_token, GoogleRequest(), audience=self.s.google_client_id)

        claims = await asyncio.to_thread(verify)  # checks signature, aud, iss, exp
        if not claims.get("email_verified"):
            raise ValueError("Google reports this email as unverified")
        return str(claims["email"]).lower()

    # ---- codes and tokens -------------------------------------------------

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        code = self._codes.get(authorization_code)
        if code and code.client_id == client.client_id and code.expires_at > time.time():
            return code
        return None

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        if self._codes.pop(authorization_code.code, None) is None:
            raise TokenError(error="invalid_grant", error_description="authorization code already used")
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.subject, authorization_code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        rec = self.store.get("refresh", _hash(refresh_token))
        if not rec or rec["client_id"] != client.client_id or rec["expires_at"] < time.time():
            return None
        if rec.get("subject") not in self.s.allowed_emails:
            return None
        return RefreshToken(token=refresh_token, client_id=rec["client_id"], scopes=rec["scopes"],
                            expires_at=int(rec["expires_at"]), subject=rec.get("subject"), resource=rec.get("resource"))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        if self.store.pop("refresh", _hash(refresh_token.token)) is None:
            raise TokenError(error="invalid_grant", error_description="refresh token already used")
        return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.subject, refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        rec = self.store.get("access", _hash(token))
        if not rec or rec["expires_at"] < time.time():
            return None
        # Re-checked on every request, so removing an address from
        # allowed_emails (and restarting) cuts off its existing tokens.
        if rec.get("subject") not in self.s.allowed_emails:
            return None
        return AccessToken(token=token, client_id=rec["client_id"], scopes=rec["scopes"],
                           expires_at=int(rec["expires_at"]), subject=rec.get("subject"), resource=rec.get("resource"))

    async def revoke_token(self, token) -> None:
        h = _hash(token.token)
        self.store.pop("access", h)
        self.store.pop("refresh", h)

    def _issue(self, client_id: str, scopes: list[str], subject: str | None, resource: str | None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        now = time.time()
        base = {"client_id": client_id, "scopes": scopes, "subject": subject, "resource": resource}
        self.store.put("access", _hash(access), {**base, "expires_at": now + ACCESS_TOKEN_TTL})
        self.store.put("refresh", _hash(refresh), {**base, "expires_at": now + REFRESH_TOKEN_TTL})
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TOKEN_TTL,
                          refresh_token=refresh, scope=" ".join(scopes))

    def _sweep(self) -> None:
        now = time.time()
        self._pending = {k: v for k, v in self._pending.items() if now - v.created < PENDING_LOGIN_TTL}
        self._codes = {k: v for k, v in self._codes.items() if v.expires_at > now}


def _page(title: str, body: str, status: int) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><title>{title}</title>"
        f"<body style='font-family:system-ui;max-width:32rem;margin:4rem auto'>"
        f"<h1>{title}</h1><p>{body}</p></body>",
        status_code=status,
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class _MCPEndpoint:
    """ASGI endpoint that hands requests to the streamable HTTP session manager."""

    def __init__(self, manager: StreamableHTTPSessionManager):
        self.manager = manager

    async def __call__(self, scope, receive, send) -> None:
        await self.manager.handle_request(scope, receive, send)


def build_app(mcp_server, settings: RemoteSettings) -> Starlette:
    provider = GoogleLoginProvider(settings)
    issuer = AnyHttpUrl(settings.public_url)
    resource = AnyHttpUrl(settings.mcp_url)
    manager = StreamableHTTPSessionManager(app=mcp_server)

    routes = [
        *create_auth_routes(
            provider=provider,
            issuer_url=issuer,
            client_registration_options=ClientRegistrationOptions(enabled=True, default_scopes=["mcp"]),
            revocation_options=RevocationOptions(enabled=True),
        ),
        *create_protected_resource_routes(
            resource_url=resource,
            authorization_servers=[issuer],
            resource_name="Google Workspace (multi-account)",
        ),
        Route(GOOGLE_CALLBACK_PATH, endpoint=provider.google_callback, methods=["GET"]),
        Route("/healthz", endpoint=lambda _r: JSONResponse({"ok": True}), methods=["GET"]),
        Route(
            MCP_PATH,
            endpoint=RequireAuthMiddleware(_MCPEndpoint(manager), [], build_resource_metadata_url(resource)),
        ),
    ]

    return Starlette(
        routes=routes,
        middleware=[
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(ProviderTokenVerifier(provider))),
            Middleware(AuthContextMiddleware),
        ],
        lifespan=lambda _app: manager.run(),
    )


def serve(mcp_server, config: dict[str, Any], credentials_dir: Path) -> None:
    import uvicorn

    try:
        settings = load_settings(config, credentials_dir)
    except ValueError as exc:
        print(f"STARTUP ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    _log(f"connector URL: {settings.mcp_url}")
    _log(f"allowed sign-ins: {', '.join(sorted(settings.allowed_emails))}")
    _log(f"listening on http://{settings.host}:{settings.port} (put a TLS tunnel in front of it)")
    uvicorn.run(
        build_app(mcp_server, settings),
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        log_level="info",
    )
