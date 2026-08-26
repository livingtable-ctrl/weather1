"""Audit artefacts: reports, evidence, and one-off reproduction scripts.

This file exists only so ``audit.reproductions`` is importable as a package,
which is what lets a reproduction script do

    from audit.reproductions._isolate import isolate

as its first statement. Nothing here is imported by production code.

``audit/`` is NOT collected by pytest -- pyproject.toml pins
``testpaths = ["tests"]`` -- so the ``test_``-prefixed script that lives under
``reproductions/`` stays out of the suite, exactly as it did before this file
existed.
"""
