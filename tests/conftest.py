"""Shared pytest setup for the nano-dsl test suite.

nano_logic.engine resolves its state directory (rules.json, logs/,
nano-dsl.log) once at import time via nano_logic.paths.get_state_dir().
Setting $NANO_DSL_STATE_DIR here, at conftest module scope, runs before
pytest imports any test module — and therefore before nano_logic.engine
is imported — so the whole suite is redirected to a throwaway directory
instead of touching a developer's real ~/.local/state/nano-dsl.
"""
import os
import tempfile

os.environ.setdefault("NANO_DSL_STATE_DIR", tempfile.mkdtemp(prefix="nano-dsl-test-"))
