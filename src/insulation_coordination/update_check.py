"""Read the newest published release from GitHub and compare it to this build."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO

from insulation_coordination import __version__

REPOSITORY_URL = "https://github.com/smarley2/insulation-coordination-calculator"
LATEST_RELEASE_API = (
    "https://api.github.com/repos/smarley2/insulation-coordination-calculator/releases/latest"
)
RELEASES_URL = f"{REPOSITORY_URL}/releases"
NEW_ISSUE_URL = f"{REPOSITORY_URL}/issues/new/choose"

_MAX_RESPONSE_BYTES = 1_000_000
_NUMBERS = re.compile(r"\d+")

type Opener = Callable[[urllib.request.Request], IO[bytes]]


class UpdateCheckError(RuntimeError):
    """The published release list could not be read."""


@dataclass(frozen=True)
class UpdateStatus:
    """Outcome of one update check."""

    current_version: str
    latest_version: str
    release_url: str
    update_available: bool


def check_for_update(
    current_version: str = __version__,
    *,
    timeout: float = 5.0,
    opener: Opener | None = None,
) -> UpdateStatus:
    """Ask GitHub for the newest release and say whether it is newer than this build."""
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"insulation-coordination-calculator/{current_version}",
        },
    )
    try:
        if opener is not None:
            with opener(request) as response:
                payload = response.read(_MAX_RESPONSE_BYTES)
        else:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(_MAX_RESPONSE_BYTES)
        release = json.loads(payload)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise UpdateCheckError(
                "No release has been published yet, so there is nothing to compare against."
            ) from error
        raise UpdateCheckError(f"GitHub replied {error.code} {error.reason}.") from error
    except (OSError, ValueError) as error:
        raise UpdateCheckError(f"Could not reach GitHub: {error}") from error
    if not isinstance(release, dict):
        raise UpdateCheckError("GitHub returned an unexpected release document.")
    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        raise UpdateCheckError("The newest release has no version tag.")
    url = str(release.get("html_url") or RELEASES_URL)
    if not url.startswith("https://github.com/"):
        url = RELEASES_URL
    latest = tag.lstrip("vV")
    return UpdateStatus(
        current_version=current_version,
        latest_version=latest,
        release_url=url,
        update_available=_version_key(latest) > _version_key(current_version),
    )


def _version_key(version: str) -> tuple[int, ...]:
    """Compare versions on their numeric parts only; suffixes are ignored."""
    return tuple(int(part) for part in _NUMBERS.findall(version)) or (0,)
