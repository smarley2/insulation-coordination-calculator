from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Base for every domain model: no undeclared fields, no mutation after construction.

    Lives in its own module (not in ``project.py`` or ``topology.py``) because both of those
    modules need it and each needs a type the other defines - ``Project`` holds
    ``GalvanicDomain``/``GalvanicBarrier`` collections, and the topology helpers take a
    ``Project``. A shared, dependency-free base avoids the import cycle that would otherwise
    result. ``project.py`` still exposes ``FrozenModel`` under its own name for the existing
    importers that use it as a re-export.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
