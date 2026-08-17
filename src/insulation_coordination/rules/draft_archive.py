"""A review draft on disk, so closing the Rules Manager costs no review work.

A draft cannot be approved until every required source item is extracted, and approval was the
only route by which review work became a file. So a draft has to survive across sessions, and
this is where it does: one member per model field, written through
:func:`insulation_coordination.rules.archive.sealed_archive` so a draft file carries the same
member allowlist, size ceilings, compression-ratio ceiling, canonical JSON, fixed timestamps and
per-member checksums an approved package does.

A draft file is a private artifact: it holds extracted licensed content and must never be
committed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

from insulation_coordination.domain.rules import RULE_SCHEMA_VERSION, RulePackageError
from insulation_coordination.rules.archive import (
    _canonical_json,
    _decode_json,
    _read_members,
    sealed_archive,
    verified_checksums,
)
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    draft_content_digest,
)
from insulation_coordination.rules.importer.review import draft_review_digest

DRAFT_SUFFIX = ".icdraft"
#: Every persisted field of the model, so a field added to ``ImportedRuleDraft`` is saved without
#: anyone remembering to list it here. A hand-written member list is a review-work leak waiting to
#: happen: the field would round-trip as its default and the resumed draft would look less
#: reviewed than it was.
DRAFT_FIELDS = tuple(
    sorted(name for name, field in ImportedRuleDraft.model_fields.items() if not field.exclude)
)
#: One member per field, prefixed: the model has a ``checksums`` field of its own, and a member
#: named for it would collide with the archive's own checksum member.
DRAFT_MEMBERS = (*(f"draft-{name}.json" for name in DRAFT_FIELDS), "digests.json", "sources.json")
ARCHIVE_MEMBERS = (*DRAFT_MEMBERS, "checksums.json")
#: A draft carries every extracted raw cell of every source table, so its largest member holds far
#: more nodes than an approved package's does. ``MAX_MEMBER_BYTES`` remains the real bound; this
#: keeps a ceiling on parse cost without refusing a complete extraction.
MAX_DRAFT_JSON_NODES = 2_000_000


class ResumedDraft(NamedTuple):
    """A draft read back from disk, with the source PDFs its evidence still binds to."""

    draft: ImportedRuleDraft
    pdf_paths: dict[str, Path]


def write_rule_draft(
    path: Path,
    draft: ImportedRuleDraft,
    *,
    pdf_paths: Mapping[str, Path],
) -> str:
    """Write one draft under review, and return the archive digest.

    The source PDFs are recorded by path, never by content: a draft file must not become a second
    copy of a licensed document. Their digests already live in the draft's own source identities,
    which is what resuming checks them against.
    """

    draft = _revalidated(draft)
    dump = draft.model_dump(mode="json")
    if set(dump) != set(DRAFT_FIELDS):
        raise RulePackageError("rules draft archive members do not cover the draft model")
    payloads = {f"draft-{name}.json": _canonical_json(dump[name]) for name in DRAFT_FIELDS}
    payloads["digests.json"] = _canonical_json(_digests(draft))
    payloads["sources.json"] = _canonical_json(_recorded_sources(draft, pdf_paths))
    content, _ = sealed_archive(payloads, DRAFT_MEMBERS)
    # Replaced rather than overwritten in place: autosave runs after every recorded correction,
    # and a write interrupted halfway must not destroy the last good save.
    path = Path(path)
    temporary = path.with_name(f"{path.name}.partial")
    temporary.write_bytes(content)
    temporary.replace(path)
    return hashlib.sha256(content).hexdigest()


def load_rule_draft(path: Path) -> ResumedDraft:
    """Read one draft back with every audit trail intact, or refuse it.

    Refused rather than silently loaded: a resumed draft drives review decisions, so a member
    that no longer matches its checksum, a review state that no longer matches its recorded
    digest, or a source document that no longer matches the local PDF all stop the resume.
    """

    path = Path(path)
    members, _content = _read_members(path, ARCHIVE_MEMBERS)
    verified_checksums(members, DRAFT_MEMBERS)
    manifest = _member(members, "draft-manifest.json")
    if not isinstance(manifest, dict):
        raise RulePackageError("draft-manifest.json root must be an object")
    schema = manifest.get("schema_version")
    if schema != RULE_SCHEMA_VERSION:
        raise RulePackageError(
            f"unsupported schema {schema}; re-extract the draft from the licensed IEC PDFs"
        )
    try:
        draft = ImportedRuleDraft.model_validate(
            {name: _member(members, f"draft-{name}.json") for name in DRAFT_FIELDS}
        )
    except RulePackageError:
        raise
    except (AttributeError, RecursionError, TypeError, ValueError) as error:
        raise RulePackageError(f"invalid rule draft: {error}") from error
    if _member(members, "digests.json") != _digests(draft):
        raise RulePackageError(
            "rules draft does not match its recorded review digest; "
            "re-extract the draft from the licensed IEC PDFs"
        )
    return ResumedDraft(draft=draft, pdf_paths=_verified_sources(draft, members))


def _member(members: dict[str, bytes], name: str) -> Any:
    return _decode_json(members[name], name, max_nodes=MAX_DRAFT_JSON_NODES)


def _revalidated(draft: ImportedRuleDraft) -> ImportedRuleDraft:
    """Validate at the file boundary, because ``model_copy`` does not.

    Every review action reaches a draft through ``model_copy``, so the object handed here can
    hold content no validator has seen. The same guard ``write_rule_package`` applies.
    """

    try:
        return ImportedRuleDraft.model_validate(draft.model_dump(mode="python"))
    except RulePackageError:
        raise
    except (AttributeError, RecursionError, TypeError, ValueError) as error:
        raise RulePackageError(f"invalid rule draft: {error}") from error


def _digests(draft: ImportedRuleDraft) -> dict[str, str]:
    """The two digests a resumed draft has to reproduce.

    ``review`` is the reviewed-baseline digest, and ``content`` is the link
    ``_require_logged_content`` re-derives from a draft's own correction chain. Recording both
    means a draft saved by one version of the model and read back by another is refused instead
    of resumed with a review state neither version agrees on.
    """

    return {"content": draft_content_digest(draft), "review": draft_review_digest(draft)}


def _recorded_sources(
    draft: ImportedRuleDraft,
    pdf_paths: Mapping[str, Path],
) -> dict[str, str]:
    missing = tuple(
        identity for identity in draft.source_identities if identity.standard not in pdf_paths
    )
    if missing:
        named = ", ".join(f"{item.standard} {item.edition}" for item in missing)
        raise RulePackageError(f"draft cannot be saved without its local source document: {named}")
    return {
        identity.standard: str(Path(pdf_paths[identity.standard]))
        for identity in draft.source_identities
    }


def _verified_sources(
    draft: ImportedRuleDraft,
    members: dict[str, bytes],
) -> dict[str, Path]:
    """Refuse a draft whose source documents are not the PDFs still on disk.

    Every grid, fragment and figure in the draft is evidence about one exact document, and a
    review resolution binds to that evidence. A document that has moved on cannot be reviewed
    against, so the resume stops here rather than showing a maintainer pages from one file
    beside decisions taken about another.
    """

    documents = {item.standard: item.sha256 for item in draft.manifest.source_documents}
    stale = tuple(
        identity
        for identity in draft.source_identities
        if documents.get(identity.standard) != identity.sha256
    )
    if stale:
        raise RulePackageError("rules draft source identities disagree with its manifest")
    recorded = _member(members, "sources.json")
    expected = {identity.standard for identity in draft.source_identities}
    if not isinstance(recorded, dict) or set(recorded) != expected:
        raise RulePackageError(
            "rules draft must record exactly one local source document per recognized standard"
        )
    paths: dict[str, Path] = {}
    for identity in draft.source_identities:
        value = recorded[identity.standard]
        if not isinstance(value, str) or not value.strip():
            raise RulePackageError(f"invalid source document path for {identity.standard}")
        candidate = Path(value)
        if _file_sha256(candidate) != identity.sha256:
            raise RulePackageError(
                f"the source document this draft was extracted from is missing or changed: "
                f"{identity.standard} {identity.edition} ({candidate})"
            )
        paths[identity.standard] = candidate
    return paths


def _file_sha256(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return None
