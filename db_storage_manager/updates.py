"""Release / changelog lookup against the project's real GitHub Releases.

No private update server: the only endpoints are the public GitHub REST API
and ``raw.githubusercontent.com`` for ``CHANGELOG.md``. Nothing is downloaded
or installed automatically - the UI points the user at the release page (or a
``pip`` command pinned to the release tag) and checks run only on demand.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import APP_NAME, APP_VERSION

GITHUB_REPO = "VoxHash/DB_Storage_Manager"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
CHANGELOG_RAW_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/CHANGELOG.md"
)
_ALLOWED_URL_PREFIX = f"https://github.com/{GITHUB_REPO}/"

CHANNEL_STABLE = "stable"
CHANNEL_EXPERIMENTAL = "experimental"
CHANNELS = (CHANNEL_STABLE, CHANNEL_EXPERIMENTAL)

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.]?([0-9A-Za-z.-]+))?$")

Fetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version: Tuple[int, int, int]
    prerelease: bool
    html_url: str
    body: str
    published_at: str

    @property
    def label(self) -> str:
        return self.tag.lstrip("v")

    @property
    def pip_command(self) -> str:
        """Install pinned to the release tag (the package is not on PyPI)."""
        return (
            'pip install --upgrade "db-storage-manager @ '
            f'git+https://github.com/{GITHUB_REPO}.git@{self.tag}"'
        )


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    """Parse ``v1.2.3`` / ``1.2.3-rc1`` into a comparable (major, minor, patch)."""
    match = _VERSION_RE.match((text or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_trusted_release_url(url: str) -> bool:
    """Only open links that point at this project's GitHub repository."""
    return isinstance(url, str) and url.startswith(_ALLOWED_URL_PREFIX)


def _default_fetch(url: str, timeout: float = 10.0) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("Only https:// update endpoints are allowed")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{APP_NAME.replace(' ', '-')}/{APP_VERSION}",
            "Accept": "application/vnd.github+json, text/plain",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def parse_releases(payload: Any) -> List[ReleaseInfo]:
    """Convert a GitHub ``/releases`` JSON payload into ``ReleaseInfo`` rows."""
    releases: List[ReleaseInfo] = []
    if not isinstance(payload, list):
        return releases
    for item in payload:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag = str(item.get("tag_name") or "")
        version = parse_version(tag)
        url = str(item.get("html_url") or "")
        if version is None or not is_trusted_release_url(url):
            continue
        releases.append(
            ReleaseInfo(
                tag=tag,
                version=version,
                prerelease=bool(item.get("prerelease")),
                html_url=url,
                body=str(item.get("body") or ""),
                published_at=str(item.get("published_at") or ""),
            )
        )
    releases.sort(key=lambda r: r.version, reverse=True)
    return releases


def fetch_releases(fetch: Optional[Fetcher] = None) -> List[ReleaseInfo]:
    """Fetch the most recent releases from the public GitHub API."""
    fetch = fetch or _default_fetch
    raw = fetch(f"{RELEASES_API}?per_page=15")
    return parse_releases(json.loads(raw.decode("utf-8")))


def select_update(
    current: str,
    releases: List[ReleaseInfo],
    channel: str = CHANNEL_STABLE,
) -> Optional[ReleaseInfo]:
    """Newest release strictly newer than ``current`` for the chosen channel.

    ``stable`` ignores GitHub pre-releases; ``experimental`` includes them.
    """
    current_version = parse_version(current)
    if current_version is None:
        return None
    for release in releases:  # sorted newest first
        if release.prerelease and channel != CHANNEL_EXPERIMENTAL:
            continue
        if release.version > current_version:
            return release
        break
    return None


def check_for_update(
    channel: str = CHANNEL_STABLE,
    *,
    current: str = APP_VERSION,
    fetch: Optional[Fetcher] = None,
) -> Dict[str, Any]:
    """Return ``{current, channel, update: ReleaseInfo|None, latest: ...}``."""
    releases = fetch_releases(fetch)
    eligible = [
        r for r in releases if channel == CHANNEL_EXPERIMENTAL or not r.prerelease
    ]
    return {
        "current": current,
        "channel": channel,
        "update": select_update(current, releases, channel),
        "latest": eligible[0] if eligible else None,
    }


def local_changelog_path() -> Optional[Path]:
    """CHANGELOG.md next to the package when running from a source checkout."""
    candidate = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    return candidate if candidate.is_file() else None


def load_changelog(fetch: Optional[Fetcher] = None) -> Tuple[str, str]:
    """Return ``(markdown, source)`` where source is ``local`` or ``remote``.

    A source checkout reads its own ``CHANGELOG.md``; a pip-installed copy
    (which does not ship the file) downloads it from the repository.
    """
    path = local_changelog_path()
    if path is not None:
        return path.read_text(encoding="utf-8"), "local"
    fetch = fetch or _default_fetch
    return fetch(CHANGELOG_RAW_URL).decode("utf-8"), "remote"
