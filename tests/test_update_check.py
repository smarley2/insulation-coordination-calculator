from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import IO

import pytest

from insulation_coordination.update_check import (
    RELEASES_URL,
    UpdateCheckError,
    check_for_update,
)


def _opener(payload: object) -> Callable[[urllib.request.Request], IO[bytes]]:
    def open_request(request: urllib.request.Request) -> IO[bytes]:
        assert request.full_url.startswith("https://api.github.com/")
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    return open_request


def _raising(error: Exception) -> Callable[[urllib.request.Request], IO[bytes]]:
    def open_request(request: urllib.request.Request) -> IO[bytes]:
        raise error

    return open_request


def test_newer_published_tag_is_an_update() -> None:
    status = check_for_update(
        "0.1.0",
        opener=_opener(
            {"tag_name": "v0.2.0", "html_url": "https://github.com/x/y/releases/tag/v0.2.0"}
        ),
    )
    assert status.update_available is True
    assert status.latest_version == "0.2.0"
    assert status.release_url.endswith("v0.2.0")


def test_same_version_is_not_an_update() -> None:
    status = check_for_update("0.1.0", opener=_opener({"tag_name": "v0.1.0"}))
    assert status.update_available is False
    assert status.release_url == RELEASES_URL


def test_older_published_tag_is_not_an_update() -> None:
    status = check_for_update("1.2.0", opener=_opener({"tag_name": "v1.1.9"}))
    assert status.update_available is False


def test_shorter_tag_compares_by_numeric_parts() -> None:
    assert check_for_update("0.1.0", opener=_opener({"tag_name": "v1"})).update_available is True
    assert check_for_update("1.0.0", opener=_opener({"tag_name": "v1"})).update_available is False


def test_non_github_release_url_falls_back_to_the_releases_page() -> None:
    status = check_for_update(
        "0.1.0", opener=_opener({"tag_name": "v0.2.0", "html_url": "https://evil.example/x"})
    )
    assert status.release_url == RELEASES_URL


def test_missing_release_is_explained() -> None:
    error = urllib.error.HTTPError(RELEASES_URL, 404, "Not Found", {}, None)  # type: ignore[arg-type]
    with pytest.raises(UpdateCheckError, match="No release has been published"):
        check_for_update("0.1.0", opener=_raising(error))


def test_network_failure_is_explained() -> None:
    with pytest.raises(UpdateCheckError, match="Could not reach GitHub"):
        check_for_update("0.1.0", opener=_raising(OSError("no route to host")))


def test_release_without_a_tag_is_rejected() -> None:
    with pytest.raises(UpdateCheckError, match="no version tag"):
        check_for_update("0.1.0", opener=_opener({"tag_name": ""}))
