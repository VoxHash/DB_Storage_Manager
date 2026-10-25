"""
Multi-user authentication and RBAC for shared workstation deployments.

Users and password hashes are persisted via SecureStore (``users.enc``).
When no users exist, the app runs in single-user open mode (all permissions
allowed). Once at least one user is bootstrapped, login is required and
permissions are enforced on sensitive actions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

# PBKDF2 parameters (OWASP-class baseline for interactive logins).
# Tests may lower via DSM_PBKDF2_ITERATIONS for speed; production default stays high.
_DEFAULT_PBKDF2_ITERATIONS = 390_000
_SALT_BYTES = 16
_HASH_BYTES = 32
_HASH_PREFIX = "pbkdf2_sha256"


def _pbkdf2_iterations() -> int:
    raw = os.environ.get("DSM_PBKDF2_ITERATIONS", "").strip()
    if raw:
        try:
            value = int(raw)
            if value >= 1:
                return value
        except ValueError:
            pass
    return _DEFAULT_PBKDF2_ITERATIONS


class PermissionDenied(PermissionError):
    """Raised when the current principal lacks a required permission."""

    def __init__(self, permission: str, message: Optional[str] = None):
        self.permission = permission
        super().__init__(
            message
            or f"Permission denied: '{permission}' is required for this action"
        )


class UserRole(Enum):
    """Built-in roles for shared workstation RBAC."""

    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"
    GUEST = "guest"


# Canonical permission strings used by GUI and API enforcement
PERM_CONNECTIONS_READ = "connections:read"
PERM_CONNECTIONS_WRITE = "connections:write"
PERM_CONNECTIONS_DELETE = "connections:delete"
PERM_BACKUPS_READ = "backups:read"
PERM_BACKUPS_CREATE = "backups:create"
PERM_BACKUPS_RESTORE = "backups:restore"
PERM_SETTINGS_READ = "settings:read"
PERM_SETTINGS_WRITE = "settings:write"
PERM_PLUGINS_READ = "plugins:read"
PERM_PLUGINS_MANAGE = "plugins:manage"
PERM_USERS_MANAGE = "users:manage"
PERM_QUERY_EXECUTE = "query:execute"
PERM_MONITORING_READ = "monitoring:read"
PERM_MONITORING_WRITE = "monitoring:write"
PERM_API_READ = "api:read"
PERM_API_WRITE = "api:write"
PERM_DASHBOARD_READ = "dashboard:read"

ALL_PERMISSIONS: Set[str] = {
    PERM_CONNECTIONS_READ,
    PERM_CONNECTIONS_WRITE,
    PERM_CONNECTIONS_DELETE,
    PERM_BACKUPS_READ,
    PERM_BACKUPS_CREATE,
    PERM_BACKUPS_RESTORE,
    PERM_SETTINGS_READ,
    PERM_SETTINGS_WRITE,
    PERM_PLUGINS_READ,
    PERM_PLUGINS_MANAGE,
    PERM_USERS_MANAGE,
    PERM_QUERY_EXECUTE,
    PERM_MONITORING_READ,
    PERM_MONITORING_WRITE,
    PERM_API_READ,
    PERM_API_WRITE,
    PERM_DASHBOARD_READ,
}

ROLE_PERMISSIONS: Dict[UserRole, Set[str]] = {
    UserRole.ADMIN: {"*"},
    UserRole.USER: {
        PERM_CONNECTIONS_READ,
        PERM_CONNECTIONS_WRITE,
        PERM_CONNECTIONS_DELETE,
        PERM_BACKUPS_READ,
        PERM_BACKUPS_CREATE,
        PERM_BACKUPS_RESTORE,
        PERM_SETTINGS_READ,
        PERM_PLUGINS_READ,
        PERM_QUERY_EXECUTE,
        PERM_MONITORING_READ,
        PERM_MONITORING_WRITE,
        PERM_API_READ,
        PERM_API_WRITE,
        PERM_DASHBOARD_READ,
    },
    UserRole.VIEWER: {
        PERM_CONNECTIONS_READ,
        PERM_BACKUPS_READ,
        PERM_SETTINGS_READ,
        PERM_PLUGINS_READ,
        PERM_QUERY_EXECUTE,
        PERM_MONITORING_READ,
        PERM_API_READ,
        PERM_DASHBOARD_READ,
    },
    UserRole.GUEST: {
        PERM_DASHBOARD_READ,
        PERM_CONNECTIONS_READ,
        PERM_API_READ,
    },
}


def hash_password(
    password: str, *, iterations: Optional[int] = None
) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256; returns a storable string."""
    if not password:
        raise ValueError("Password must not be empty")
    if iterations is None:
        iterations = _pbkdf2_iterations()
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=_HASH_BYTES,
    )
    return (
        f"{_HASH_PREFIX}${iterations}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify of a password against a stored hash string."""
    try:
        algo, iter_s, salt_b64, hash_b64 = stored.split("$", 3)
    except ValueError:
        return False
    if algo != _HASH_PREFIX:
        return False
    try:
        iterations = int(iter_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return hmac.compare_digest(digest, expected)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class User:
    """Local workstation user account."""

    username: str
    email: str
    role: UserRole = UserRole.USER
    password_hash: str = ""
    mfa_secret: Optional[str] = None
    mfa_enabled: bool = False
    enabled: bool = True
    created_at: str = field(default_factory=_utc_now_iso)
    last_login: Optional[str] = None

    def to_record(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "email": self.email,
            "role": self.role.value,
            "password_hash": self.password_hash,
            "mfa_secret": self.mfa_secret,
            "mfa_enabled": bool(self.mfa_enabled),
            "enabled": bool(self.enabled),
            "created_at": self.created_at,
            "last_login": self.last_login,
        }

    def public_dict(self) -> Dict[str, Any]:
        """Safe view without password hash or MFA secret."""
        return {
            "username": self.username,
            "email": self.email,
            "role": self.role.value,
            "mfa_enabled": bool(self.mfa_enabled),
            "enabled": bool(self.enabled),
            "created_at": self.created_at,
            "last_login": self.last_login,
        }

    @classmethod
    def from_record(cls, data: Dict[str, Any]) -> "User":
        role_raw = data.get("role") or UserRole.USER.value
        try:
            role = UserRole(str(role_raw).lower())
        except ValueError:
            role = UserRole.USER
        return cls(
            username=str(data["username"]),
            email=str(data.get("email") or ""),
            role=role,
            password_hash=str(data.get("password_hash") or ""),
            mfa_secret=data.get("mfa_secret"),
            mfa_enabled=bool(data.get("mfa_enabled", False)),
            enabled=bool(data.get("enabled", True)),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            last_login=data.get("last_login"),
        )


class RBACManager:
    """Role → permission map and checks."""

    def __init__(
        self, permissions: Optional[Dict[UserRole, Set[str]]] = None
    ):
        self.permissions: Dict[UserRole, Set[str]] = {
            role: set(perms)
            for role, perms in (permissions or ROLE_PERMISSIONS).items()
        }

    def permissions_for(self, role: UserRole) -> Set[str]:
        return set(self.permissions.get(role, set()))

    def has_permission(self, user: User, permission: str) -> bool:
        if not user.enabled:
            return False
        perms = self.permissions.get(user.role, set())
        if "*" in perms:
            return True
        return permission in perms


class MFAProvider:
    """TOTP MFA helpers (optional second factor after password)."""

    @staticmethod
    def generate_secret() -> str:
        import pyotp

        return pyotp.random_base32()

    @staticmethod
    def verify_token(secret: str, token: str) -> bool:
        import pyotp

        if not token or not secret:
            return False
        totp = pyotp.TOTP(secret)
        return bool(totp.verify(str(token).strip(), valid_window=1))

    @staticmethod
    def provisioning_uri(
        secret: str,
        username: str,
        issuer: str = "DB Storage Manager",
    ) -> str:
        import pyotp

        return pyotp.TOTP(secret).provisioning_uri(
            name=username, issuer_name=issuer
        )


class AuthenticationManager:
    """Password auth + RBAC with SecureStore-backed persistence."""

    def __init__(self, store: Any = None):
        self._store = store
        self.rbac = RBACManager()
        self.mfa = MFAProvider()
        self.users: Dict[str, User] = {}
        self.current_user: Optional[User] = None
        self._system_admin = False  # API Bearer machine token
        self.reload()

    def _get_store(self):
        if self._store is not None:
            return self._store
        from .store import SecureStore

        return SecureStore()

    def reload(self) -> None:
        """Load users from SecureStore (or empty if none)."""
        store = self._get_store()
        payload = store.get_users()
        users_list = payload.get("users") if isinstance(payload, dict) else []
        self.users = {}
        if isinstance(users_list, list):
            for raw in users_list:
                if not isinstance(raw, dict) or "username" not in raw:
                    continue
                user = User.from_record(raw)
                self.users[user.username.lower()] = user

    def _persist(self) -> None:
        store = self._get_store()
        records = [u.to_record() for u in sorted(
            self.users.values(), key=lambda u: u.username.lower()
        )]
        store.save_users({"version": 1, "users": records})

    def is_rbac_active(self) -> bool:
        """True when at least one local user account exists."""
        return len(self.users) > 0

    def list_users(self) -> List[User]:
        return sorted(self.users.values(), key=lambda u: u.username.lower())

    def get_user(self, username: str) -> Optional[User]:
        return self.users.get(username.lower())

    def bootstrap_admin(
        self,
        username: str,
        password: str,
        email: str = "",
        *,
        force: bool = False,
    ) -> User:
        """
        Create the first admin (local workstation bootstrap).

        Fails if users already exist unless ``force`` and caller is admin.
        """
        username = (username or "").strip()
        if not username:
            raise ValueError("Username is required")
        if len(password or "") < 8:
            raise ValueError("Password must be at least 8 characters")
        if self.is_rbac_active() and not force:
            raise RuntimeError(
                "RBAC already initialized; use create_user as an admin "
                "or pass force=True after authenticating as admin"
            )
        if force and self.is_rbac_active():
            self.require(PERM_USERS_MANAGE)
        key = username.lower()
        if key in self.users:
            raise ValueError(f"User '{username}' already exists")
        user = User(
            username=username,
            email=email or f"{username}@localhost",
            role=UserRole.ADMIN,
            password_hash=hash_password(password),
        )
        self.users[key] = user
        self._persist()
        return user

    def create_user(
        self,
        username: str,
        password: str,
        email: str = "",
        role: UserRole = UserRole.USER,
    ) -> User:
        """Create a user (requires ``users:manage`` when RBAC is active)."""
        if self.is_rbac_active():
            self.require(PERM_USERS_MANAGE)
        username = (username or "").strip()
        if not username:
            raise ValueError("Username is required")
        if len(password or "") < 8:
            raise ValueError("Password must be at least 8 characters")
        if not isinstance(role, UserRole):
            role = UserRole(str(role).lower())
        key = username.lower()
        if key in self.users:
            raise ValueError(f"User '{username}' already exists")
        # Refuse creating a second bootstrap path that skips admin
        if not self.is_rbac_active() and role != UserRole.ADMIN:
            raise ValueError(
                "First user must be an admin; use bootstrap_admin()"
            )
        user = User(
            username=username,
            email=email or f"{username}@localhost",
            role=role,
            password_hash=hash_password(password),
        )
        self.users[key] = user
        self._persist()
        return user

    def set_user_role(self, username: str, role: UserRole) -> User:
        self.require(PERM_USERS_MANAGE)
        user = self.get_user(username)
        if not user:
            raise ValueError("User not found")
        if not isinstance(role, UserRole):
            role = UserRole(str(role).lower())
        # Prevent removing the last admin
        if user.role == UserRole.ADMIN and role != UserRole.ADMIN:
            admins = [
                u for u in self.users.values() if u.role == UserRole.ADMIN
            ]
            if len(admins) <= 1:
                raise ValueError("Cannot demote the last admin")
        user.role = role
        self._persist()
        return user

    def set_user_enabled(self, username: str, enabled: bool) -> User:
        self.require(PERM_USERS_MANAGE)
        user = self.get_user(username)
        if not user:
            raise ValueError("User not found")
        if (
            not enabled
            and user.role == UserRole.ADMIN
            and self.current_user
            and self.current_user.username.lower() == user.username.lower()
        ):
            raise ValueError("Cannot disable your own admin account")
        if not enabled and user.role == UserRole.ADMIN:
            admins = [
                u
                for u in self.users.values()
                if u.role == UserRole.ADMIN and u.enabled
            ]
            if len(admins) <= 1:
                raise ValueError("Cannot disable the last enabled admin")
        user.enabled = bool(enabled)
        self._persist()
        return user

    def set_password(self, username: str, new_password: str) -> None:
        """Admin reset or self-service change (self needs auth)."""
        user = self.get_user(username)
        if not user:
            raise ValueError("User not found")
        is_self = (
            self.current_user is not None
            and self.current_user.username.lower() == user.username.lower()
        )
        if not is_self:
            self.require(PERM_USERS_MANAGE)
        if len(new_password or "") < 8:
            raise ValueError("Password must be at least 8 characters")
        user.password_hash = hash_password(new_password)
        self._persist()

    def delete_user(self, username: str) -> None:
        self.require(PERM_USERS_MANAGE)
        user = self.get_user(username)
        if not user:
            raise ValueError("User not found")
        if user.role == UserRole.ADMIN:
            admins = [
                u for u in self.users.values() if u.role == UserRole.ADMIN
            ]
            if len(admins) <= 1:
                raise ValueError("Cannot delete the last admin")
        del self.users[username.lower()]
        if (
            self.current_user
            and self.current_user.username.lower() == username.lower()
        ):
            self.current_user = None
        self._persist()

    def authenticate(
        self,
        username: str,
        password: str,
        mfa_token: Optional[str] = None,
    ) -> Optional[User]:
        """Verify password (+ optional MFA) and set ``current_user``."""
        user = self.get_user(username)
        if not user or not user.enabled:
            return None
        if not user.password_hash or not verify_password(
            password, user.password_hash
        ):
            return None
        if user.mfa_enabled and user.mfa_secret:
            if not self.mfa.verify_token(user.mfa_secret, mfa_token or ""):
                return None
        user.last_login = _utc_now_iso()
        self._persist()
        self.current_user = user
        self._system_admin = False
        return user

    def logout(self) -> None:
        self.current_user = None
        self._system_admin = False

    def set_system_admin(self, enabled: bool = True) -> None:
        """Mark the process principal as machine/API admin (Bearer token)."""
        self._system_admin = bool(enabled)
        if enabled:
            self.current_user = None

    def enable_mfa(self, username: str) -> str:
        """Enable MFA for a user; returns the new TOTP secret."""
        is_self = (
            self.current_user is not None
            and self.current_user.username.lower() == username.lower()
        )
        if not is_self:
            self.require(PERM_USERS_MANAGE)
        user = self.get_user(username)
        if not user:
            raise ValueError("User not found")
        secret = self.mfa.generate_secret()
        user.mfa_secret = secret
        user.mfa_enabled = True
        self._persist()
        return secret

    def disable_mfa(self, username: str) -> None:
        is_self = (
            self.current_user is not None
            and self.current_user.username.lower() == username.lower()
        )
        if not is_self:
            self.require(PERM_USERS_MANAGE)
        user = self.get_user(username)
        if not user:
            raise ValueError("User not found")
        user.mfa_secret = None
        user.mfa_enabled = False
        self._persist()

    def has_permission(self, permission: str) -> bool:
        """
        Check the current principal.

        Open mode (no users): allow all.
        System admin Bearer: allow all.
        Otherwise: require authenticated user with the permission.
        """
        if not self.is_rbac_active():
            return True
        if self._system_admin:
            return True
        if self.current_user is None:
            return False
        return self.rbac.has_permission(self.current_user, permission)

    def require(self, permission: str) -> None:
        if not self.has_permission(permission):
            raise PermissionDenied(permission)


_auth_manager: Optional[AuthenticationManager] = None


def get_auth_manager() -> AuthenticationManager:
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthenticationManager()
    return _auth_manager


def reset_auth_manager() -> None:
    """Clear the process singleton (tests)."""
    global _auth_manager
    _auth_manager = None
