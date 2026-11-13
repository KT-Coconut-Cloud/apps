import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, HTTPException, Request

from app.config import Settings, get_settings

ROLES = {"policy": "정책기획팀", "security": "정보보호팀"}
HOME = {"policy": "/policy/analyses", "security": "/security/runs"}


@dataclass
class User:
    username: str
    name: str
    role: str

    @property
    def team(self) -> str:
        return ROLES[self.role]


def hash_password(password: str, iterations: int = 600_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(check, digest)


def load_accounts(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {a["username"]: a for a in data["accounts"] if a.get("role") in ROLES}


class LoginGuard:
    """Counts failures per username. In memory, so it assumes a single replica."""

    def __init__(self, max_failures: int, lockout_seconds: int):
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def locked_for(self, username: str) -> int:
        remaining = self._locked_until.get(username, 0) - time.time()
        return max(0, int(remaining))

    def fail(self, username: str) -> int:
        count = self._failures.get(username, 0) + 1
        self._failures[username] = count
        if count >= self.max_failures:
            self._locked_until[username] = time.time() + self.lockout_seconds
            self._failures[username] = 0
        return count

    def reset(self, username: str) -> None:
        self._failures.pop(username, None)
        self._locked_until.pop(username, None)


class LoginRequired(Exception):
    pass


def current_user(request: Request, settings: Settings = Depends(get_settings)) -> User:
    data = request.session.get("user")
    last_seen = request.session.get("last_seen", 0)
    if not data:
        raise LoginRequired()
    if time.time() - last_seen > settings.session_idle_minutes * 60:
        request.session.clear()
        raise LoginRequired()
    request.session["last_seen"] = int(time.time())
    return User(**data)


def require_role(role: str):
    def check(user: User = Depends(current_user)) -> User:
        if user.role != role:
            raise HTTPException(status_code=403)
        return user

    return check
