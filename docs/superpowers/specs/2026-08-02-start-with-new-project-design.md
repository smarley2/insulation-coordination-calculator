# Start With a New Project Design

## Goal

Ensure every newly launched main window begins with an editable Untitled project,
matching the state produced by File > New instead of showing a blank project page.

## Design

Reuse `MainWindow._on_new()` after the window, pages, menus, and actions are fully
constructed. This keeps startup and File > New on the same project-creation path and
avoids a second project factory or changes to the domain model.

File > New and File > Open keep their current behavior. The startup project is dirty,
just like a project explicitly created through File > New, so Save and Close continue
to use the existing unsaved-project handling.

## Verification

Add a Qt regression test asserting that a fresh `MainWindow` owns an Untitled project
and that its Project page can add a net class immediately. Run the focused UI test,
the full test suite, lint, type checks, and a UI smoke test.
