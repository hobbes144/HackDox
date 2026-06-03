"""Core engine — UI-agnostic.

Rule: `core/` MUST NOT import from `gameengine.ui`. The Textual TUI and the
future Flask renderer both depend on `core/`, never the other way around.
"""
