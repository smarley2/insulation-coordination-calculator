"""No module of the importer package may depend on being imported second.

``extract`` finishes loading by importing ``clauses`` and ``curves`` to resolve
``ImportedRuleDraft``'s forward references, so a module those two reach must not import
``extract`` back at module scope: it would then load only when something imported ``extract``
first. The package ``__init__`` happens to do that today, which hides the break completely --
the failure appears the moment a caller reaches a module directly, or that unremarkable
``__init__`` line is reordered or removed.

Each module is imported in its own interpreter, with the package ``__init__`` registered but
never executed. Nothing else reliably observes import order: within one interpreter the first
import has already populated ``sys.modules``, and no amount of unloading restores the state a
fresh process starts from.
"""

from __future__ import annotations

import importlib.util
import pkgutil
import subprocess
import sys

import pytest

PACKAGE = "insulation_coordination.rules.importer"
# ``find_spec`` locates the package without executing its ``__init__``, which is the very
# thing under test here.
_SPEC = importlib.util.find_spec(PACKAGE)
assert _SPEC is not None and _SPEC.submodule_search_locations is not None
MODULES = tuple(
    info.name for info in pkgutil.iter_modules(_SPEC.submodule_search_locations) if not info.ispkg
)
_PROGRAM = f"""
import importlib.util
import sys

spec = importlib.util.find_spec({PACKAGE!r})
sys.modules[{PACKAGE!r}] = importlib.util.module_from_spec(spec)
__import__({PACKAGE!r} + "." + sys.argv[1])
"""


@pytest.mark.parametrize("module", MODULES)
def test_an_importer_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROGRAM, module],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_the_discovered_module_set_is_not_empty() -> None:
    """A broken discovery would silently reduce the check above to nothing."""

    assert {"clauses", "curves", "extract"} <= set(MODULES)
