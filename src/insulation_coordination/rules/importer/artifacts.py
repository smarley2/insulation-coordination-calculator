"""What every extracted artifact shares: how extraction fails, and how a model is hashed.

Deliberately a leaf: it imports nothing from the importer package. ``extract`` resolves the
forward references of ``ImportedRuleDraft`` by importing ``clauses`` and ``curves`` while it is
still loading, so any module those two reach must not import ``extract`` back. Both names stay
re-exported from ``extract`` for its callers.
"""

from __future__ import annotations

import hashlib

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.rules.archive import _canonical_json


class ExtractionError(ValueError):
    """Recognized input could not be extracted without guessing."""


def canonical_model_sha256(value: FrozenModel) -> str:
    """Hash one typed model through the rule archive's canonical JSON encoding."""
    return hashlib.sha256(
        _canonical_json(value.model_dump(mode="json", warnings=False))
    ).hexdigest()


__all__ = ["ExtractionError", "canonical_model_sha256"]
