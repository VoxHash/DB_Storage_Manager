"""OAuth / “grant permissions” platform connect — design notes + helpers.

Fully automating Supabase / Vercel / Railway / Neon “Connect with OAuth”
requires a registered OAuth client, a local callback listener, and durable
user tokens. This module documents that flow and exposes detection helpers
so the UI can explain what is missing — it does **not** invent fake tokens
or call platform APIs without credentials the user supplies.

What *is* automated today
-------------------------
- Import connection profiles from a project ``.env`` (``DATABASE_URL``,
  ``DIRECT_URL``, discrete ``DB_*`` / ``POSTGRES_*`` / ``MYSQL_*``).
- Import SSH bastion key folders (private key path + ``VPS.txt`` / ``DB.txt``).

What needs a user token / browser grant
---------------------------------------
1. Register an OAuth application with the platform (redirect URI e.g.
   ``http://127.0.0.1:<port>/oauth/callback``).
2. Open the authorization URL in the user's browser; they approve scopes
   (project read, database credentials).
3. Exchange the authorization code for access + refresh tokens.
4. Call the platform Management API to list projects / connection strings.
5. Store tokens encrypted in SecureStore (never git); refresh as needed.
6. Map returned connection strings through :func:`env_file.parse_database_url`.

Until steps 1–3 are configured for a given platform, prefer exporting a
``.env`` from the dashboard (Supabase → Project Settings → Database) or
using SSH key import for bastion-hosted MySQL/MariaDB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PlatformOAuthGuide:
    """Static guide for a platform that supports (or may support) OAuth connect."""

    id: str
    name: str
    env_keys: tuple[str, ...]
    oauth_automatable: bool
    notes: str
    docs_url: str = ""
    required_user_secrets: tuple[str, ...] = field(default_factory=tuple)


PLATFORM_GUIDES: List[PlatformOAuthGuide] = [
    PlatformOAuthGuide(
        id="supabase",
        name="Supabase",
        env_keys=(
            "DATABASE_URL",
            "DIRECT_URL",
            "DATABASE_URL_UNPOOLED",
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
        ),
        oauth_automatable=False,
        required_user_secrets=("access_token", "project_ref"),
        docs_url="https://supabase.com/docs/guides/database/connecting-to-postgres",
        notes=(
            "Import DATABASE_URL / DIRECT_URL from the project .env today. "
            "Management API listing needs a personal access token or OAuth app "
            "the user registers; service_role JWT is not used as a DB password."
        ),
    ),
    PlatformOAuthGuide(
        id="vercel",
        name="Vercel / Neon / Prisma",
        env_keys=("DATABASE_URL", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING"),
        oauth_automatable=False,
        required_user_secrets=("vercel_token",),
        docs_url="https://vercel.com/docs/storage",
        notes=(
            "Pull env via `vercel env pull` then Import from .env. "
            "Account OAuth would need a Vercel integration + user consent."
        ),
    ),
    PlatformOAuthGuide(
        id="laravel_forge",
        name="Laravel / cPanel / VPS",
        env_keys=("DB_HOST", "DB_DATABASE", "DB_USERNAME", "DB_PASSWORD"),
        oauth_automatable=False,
        notes=(
            "Use Import from .env for Laravel .env, or Import SSH key… when "
            "the database is only reachable through a bastion (KEY + DB.txt)."
        ),
    ),
    PlatformOAuthGuide(
        id="aws_rds",
        name="AWS RDS / GCP Cloud SQL / Azure SQL",
        env_keys=(),
        oauth_automatable=False,
        notes=(
            "Use Discover Cloud… (IAM / Entra) instead of .env import. "
            "See db_storage_manager.cloud."
        ),
        docs_url="",
    ),
]


def list_platform_guides() -> List[Dict[str, Any]]:
    """JSON-serializable guides for UI / API (no secrets)."""
    return [
        {
            "id": g.id,
            "name": g.name,
            "env_keys": list(g.env_keys),
            "oauth_automatable": g.oauth_automatable,
            "required_user_secrets": list(g.required_user_secrets),
            "docs_url": g.docs_url,
            "notes": g.notes,
            "status": (
                "oauth_requires_user_token"
                if not g.oauth_automatable
                else "oauth_ready"
            ),
        }
        for g in PLATFORM_GUIDES
    ]


def detect_platform_from_env_keys(keys: List[str] | set[str]) -> Optional[str]:
    """Return a platform id when env keys strongly match a known stack."""
    keyset = {k.upper() for k in keys}
    if "SUPABASE_URL" in keyset or any("SUPABASE" in k for k in keyset):
        return "supabase"
    if "POSTGRES_URL" in keyset or "POSTGRES_PRISMA_URL" in keyset:
        return "vercel"
    if "DB_CONNECTION" in keyset or (
        "DB_HOST" in keyset and "DB_DATABASE" in keyset
    ):
        return "laravel_forge"
    return None
