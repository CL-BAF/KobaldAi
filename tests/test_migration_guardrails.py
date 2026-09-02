"""Guardrails that stop legacy naming and layout debt entering the new package."""

from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src"
FORBIDDEN_LEGACY_TERMS = ("jarvis-core", "jarvis_core")


def test_source_does_not_restore_legacy_package_names() -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SOURCE_ROOT.rglob("*.py")
        if path.is_file()
    ).lower()

    for forbidden_term in FORBIDDEN_LEGACY_TERMS:
        assert forbidden_term not in source_text
