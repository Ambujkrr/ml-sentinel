"""Deletion-only administrator sessions. Secrets never enter response bodies."""
from collections import OrderedDict, deque
from hashlib import sha256
import hmac
import secrets
from threading import RLock
from time import monotonic
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from app.core.config import get_settings

SESSION_SECONDS = 900
COOKIE_NAME = "ml_sentinel_delete_admin"
ACTION_HEADER = "dataset-delete"


def admin_enabled() -> bool:
    settings = get_settings()
    username = settings.ADMIN_USERNAME.get_secret_value()
    password = settings.ADMIN_PASSWORD.get_secret_value()
    origin = settings.ADMIN_ALLOWED_ORIGIN
    try:
        parsed = urlsplit(origin)
        _ = parsed.port
        valid_origin = (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                        and parsed.username is None and parsed.password is None
                        and not parsed.path and not parsed.query and not parsed.fragment
                        and origin == f"{parsed.scheme}://{parsed.netloc}")
        if parsed.scheme == "http":
            valid_origin = (valid_origin and settings.APP_ENV.lower() != "production"
                            and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
    except ValueError:
        valid_origin = False
    return (settings.DATASET_DELETION_ENABLED and 1 <= len(username) <= 80
            and username == username.strip() and 32 <= len(password) <= 256
            and not any(character.isspace() for character in password) and valid_origin)


def require_enabled() -> None:
    if not admin_enabled():
        raise HTTPException(404, "Administrator dataset deletion is disabled")


def credential_fingerprint() -> bytes:
    settings = get_settings()
    return hmac.digest(settings.ADMIN_PASSWORD.get_secret_value().encode(),
                       settings.ADMIN_USERNAME.get_secret_value().encode(), "sha256")


class AdminSessions:
    """Bounded memory, revocable sessions, and a small process-wide login budget.

    The existing deployment runs one Uvicorn worker. A restart revokes all
    sessions; multiple workers require a shared session/rate-limit store first.
    """
    def __init__(self):
        self.lock = RLock()
        self.sessions = OrderedDict()
        self.attempts = deque()

    def reset(self):
        with self.lock:
            self.sessions.clear()
            self.attempts.clear()

    def allow_login(self):
        with self.lock:
            now = monotonic()
            while self.attempts and self.attempts[0] <= now - 60:
                self.attempts.popleft()
            if len(self.attempts) >= 5:
                raise HTTPException(429, "Too many sign-in attempts; wait one minute",
                                    headers={"Retry-After": "60"})
            self.attempts.append(now)

    def create(self) -> str:
        with self.lock:
            self._expire()
            while len(self.sessions) >= 8:
                self.sessions.popitem(last=False)
            token = secrets.token_urlsafe(32)
            self.sessions[sha256(token.encode()).digest()] = (
                monotonic() + SESSION_SECONDS, credential_fingerprint())
            return token

    def _expire(self):
        now = monotonic()
        fingerprint = credential_fingerprint()
        for digest, (expires, configured) in list(self.sessions.items()):
            if expires <= now or not hmac.compare_digest(configured, fingerprint):
                del self.sessions[digest]

    def valid(self, token: str) -> bool:
        if not token or len(token) > 128 or not admin_enabled():
            return False
        with self.lock:
            self._expire()
            return sha256(token.encode()).digest() in self.sessions

    def revoke(self, token: str):
        with self.lock:
            self.sessions.pop(sha256(token.encode()).digest(), None)


admin_sessions = AdminSessions()


def require_origin(request: Request):
    require_enabled()
    if request.headers.get("origin") != get_settings().ADMIN_ALLOWED_ORIGIN:
        raise HTTPException(403, "Administrator requests must use the configured application origin")


def require_admin(request: Request):
    require_enabled()
    if not admin_sessions.valid(request.cookies.get(COOKIE_NAME, "")):
        raise HTTPException(401, "Administrator sign-in is required")


def require_admin_action(request: Request):
    require_admin(request)
    require_origin(request)
    if request.headers.get("x-admin-action") != ACTION_HEADER:
        raise HTTPException(403, "Administrator action header is required")
