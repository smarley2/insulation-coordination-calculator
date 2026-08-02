# Start With a New Project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fresh application window start with the same editable Untitled project created by File > New.

**Architecture:** Reuse the existing `MainWindow._on_new()` initialization path after UI construction. Add one Qt regression test covering startup state and immediate net-class creation.

**Tech Stack:** Python 3.12, PySide6, pytest-qt, uv.

## Global Constraints

- Do not add dependencies or change the project domain schema.
- Keep File > New and File > Open behavior unchanged.
- Preserve existing dirty-state and save behavior for newly created projects.

---

### Task 1: Initialize a project at startup

**Files:**
- Modify: `tests/ui/test_project_pages.py`
- Modify: `src/insulation_coordination/ui/main_window.py`

**Interfaces:**
- Consumes: `MainWindow._on_new()` and `ProjectPage.add_net_class(name: str)`.
- Produces: A fresh `MainWindow.project` containing an Untitled `Project`.

- [ ] **Step 1: Write the failing startup regression test**

```python
def test_main_window_starts_with_new_project(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.project is not None
    assert window.project.metadata.title == "Untitled"
    window._project_page.add_net_class("HV")
    assert window.project.net_class_names == ("HV",)
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_project_pages.py::test_main_window_starts_with_new_project`

Expected: FAIL because `window.project` is currently `None`.

- [ ] **Step 3: Reuse the existing New-project path at startup**

At the end of `MainWindow.__init__()`, after `_update_actions()`, add:

```python
self._on_new()
```

- [ ] **Step 4: Run focused and full verification**

Run:

```text
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_project_pages.py::test_main_window_starts_with_new_project
QT_QPA_PLATFORM=offscreen uv run pytest -q
uv run ruff check .
uv run mypy src
```

Expected: all commands exit successfully.
