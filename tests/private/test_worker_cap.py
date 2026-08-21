"""The cap that makes any result from this directory believable."""

from __future__ import annotations

import pytest


def test_this_directory_only_ran_within_its_worker_cap(request: pytest.FixtureRequest) -> None:
    """If this fails, nothing else in this directory means anything.

    Past the cap the suite invents a different handful of failures every run, which has twice
    been read as a code regression and once as evidence the repository's timeout was too low.
    Asserting it from inside the directory turns a silently removed guard into one loud failure
    that names the cause, instead of a scattering of failures that do not.

    The cap is spelled out rather than imported from ``conftest``: importing a conftest as a
    module hands xdist a second copy of it, which is its own way of fabricating failures.
    """

    workers = getattr(request.config, "workerinput", {}).get("workercount", 1)
    assert workers <= 4, (
        f"this directory ran on {workers} workers; its guard is gone or was bypassed, so treat "
        "every other result in this run as unproven. See issue #146."
    )
