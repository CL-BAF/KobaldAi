"""Foundation tests for the canonical package."""

import importlib

import kobald
from kobald import PROJECT, ProjectInfo


def test_project_identity_is_canonical() -> None:
    assert ProjectInfo(
        name="KobaldAi",
        repository="https://github.com/CL-BAF/KobaldAi",
        canonical=True,
    ) == PROJECT


def test_package_has_development_version() -> None:
    assert kobald.__version__ == "0.1.0.dev0"


def test_architecture_packages_are_importable() -> None:
    domains = (
        "agents",
        "api",
        "audit",
        "config",
        "core",
        "integrations",
        "knowledge",
        "policy",
        "providers",
        "research",
        "runtime",
        "supervisor",
        "training",
    )

    for domain in domains:
        assert importlib.import_module(f"kobald.{domain}") is not None
