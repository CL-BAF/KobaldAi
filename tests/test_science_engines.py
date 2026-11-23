"""Engine catalogue probing, registry resolution and the SciPy ODE adapter."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest

from kobald.integrations.science import (
    AdapterError,
    AdapterResult,
    IntegrationLevel,
    OutputColumn,
    ScienceEngineRegistry,
    TaskDefinition,
    UnknownEngineTaskError,
    default_registry,
)
from kobald.integrations.science.adapters.scipy_ode import DAMPED_OSCILLATOR, ScipyOdeAdapter
from kobald.integrations.science.catalog import (
    ENGINE_CATALOG,
    EngineDescriptor,
    EngineKind,
    probe_engine,
)
from kobald.research.spec import OptionValue

REQUIRED_ENGINES = {
    "numpy", "scipy", "sympy", "pint", "mujoco", "qutip", "fenicsx", "openmm", "rdkit",
    "pyscf", "cantera", "ase", "pybamm", "biopython", "cobra", "astropy", "openfoam", "gromacs",
}  # fmt: skip


def test_catalogue_covers_every_requested_engine_once() -> None:
    ids = [d.engine_id for d in ENGINE_CATALOG]
    assert set(ids) == REQUIRED_ENGINES
    assert len(ids) == len(set(ids))
    for descriptor in ENGINE_CATALOG:
        if descriptor.kind is EngineKind.PYTHON:
            assert descriptor.import_name and descriptor.distributions
            assert descriptor.install_extra == f"engine-{descriptor.engine_id}"
        else:
            assert descriptor.executables and descriptor.needs_isolated_linux_env


def test_probe_python_engine_present() -> None:
    probe = probe_engine(next(d for d in ENGINE_CATALOG if d.engine_id == "scipy"))
    assert probe.installed and probe.version and probe.location
    assert probe.to_dict()["engine_id"] == "scipy"


def _python_descriptor(distributions: tuple[str, ...], import_name: str) -> EngineDescriptor:
    return EngineDescriptor(
        engine_id="numpy",
        display_name="Test",
        domain="test",
        kind=EngineKind.PYTHON,
        distributions=distributions,
        import_name=import_name,
    )


def test_probe_uses_fallback_distribution_names() -> None:
    probe = probe_engine(_python_descriptor(("kobald-no-such-dist", "numpy"), "numpy"))
    assert probe.installed and probe.version is not None


@pytest.mark.parametrize("import_name", ["kobald_no_such_module", "kobald_missing.parent"])
def test_probe_python_engine_absent(import_name: str) -> None:
    probe = probe_engine(_python_descriptor(("kobald-no-such-dist",), import_name))
    assert not probe.installed
    assert probe.version is None and probe.location is None


def test_probe_reports_namespace_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.machinery.ModuleSpec("nsmod", None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: spec)
    probe = probe_engine(_python_descriptor(("numpy",), "nsmod"))
    assert probe.location == "namespace package"


def test_probe_executables_never_runs_them() -> None:
    gromacs = next(d for d in ENGINE_CATALOG if d.engine_id == "gromacs")
    seen: list[str] = []

    def fake_which(name: str) -> str | None:
        seen.append(name)
        return "/opt/gromacs/bin/gmx_mpi" if name == "gmx_mpi" else None

    probe = probe_engine(gromacs, fake_which)
    assert probe.installed and probe.location == "/opt/gromacs/bin/gmx_mpi"
    assert probe.version is None
    assert seen == ["gmx", "gmx_mpi"]
    assert not probe_engine(gromacs, lambda name: None).installed


class FakeAdapter:
    def __init__(self, engine_id: str) -> None:
        self._engine_id = engine_id

    @property
    def engine_id(self) -> str:
        return self._engine_id

    def tasks(self) -> Mapping[str, TaskDefinition]:
        return {"noop": TaskDefinition("noop", "does nothing", {}, {}, {})}

    def run(
        self,
        task: str,
        parameters: Mapping[str, float],
        options: Mapping[str, OptionValue],
        seed: int | None,
    ) -> AdapterResult:
        return AdapterResult("0", {})


def test_registry_levels_and_resolution() -> None:
    registry = ScienceEngineRegistry(adapters=[ScipyOdeAdapter(), FakeAdapter("fenicsx")])
    statuses = {s.descriptor.engine_id: s for s in registry.discover(which=lambda n: None)}
    assert statuses["scipy"].level is IntegrationLevel.ADAPTER_READY
    assert statuses["numpy"].level is IntegrationLevel.DETECTED_NO_ADAPTER
    assert statuses["openfoam"].level is IntegrationLevel.NOT_INSTALLED
    assert statuses["fenicsx"].level is IntegrationLevel.ADAPTER_ENGINE_MISSING
    assert statuses["scipy"].to_dict()["tasks"] == ["damped_harmonic_oscillator"]
    adapter, definition = registry.resolve("scipy", "damped_harmonic_oscillator")
    assert definition is DAMPED_OSCILLATOR and adapter.engine_id == "scipy"
    assert set(registry.tasks()) == {("scipy", "damped_harmonic_oscillator"), ("fenicsx", "noop")}


@pytest.mark.parametrize(
    ("engine", "task", "message"),
    [
        ("nonexistent", "x", "unknown engine"),
        ("rdkit", "x", "no adapter"),
        ("scipy", "x", "no task"),
    ],
)
def test_registry_rejects_unresolvable_tasks(engine: str, task: str, message: str) -> None:
    with pytest.raises(UnknownEngineTaskError, match=message):
        default_registry().resolve(engine, task)


def test_registry_rejects_bad_registrations() -> None:
    registry = ScienceEngineRegistry(adapters=[ScipyOdeAdapter()])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(ScipyOdeAdapter())
    with pytest.raises(ValueError, match="not in the catalogue"):
        registry.register(FakeAdapter("homemade"))


def test_task_definition_serialises() -> None:
    data = DAMPED_OSCILLATOR.to_dict()
    assert data["parameters"]["damping"]["dimension"] == "[mass] / [time]"
    assert data["options"]["method"]["choices"] == ["DOP853", "RK45", "Radau", "LSODA"]
    assert data["outputs"] == {"time": "s", "displacement": "m", "velocity": "m/s"}


def test_result_types_validate_content() -> None:
    with pytest.raises(AdapterError, match="non-finite"):
        OutputColumn("m", (1.0, float("nan")))
    with pytest.raises(AdapterError, match="different lengths"):
        AdapterResult("1", {"a": OutputColumn("m", (1.0,)), "b": OutputColumn("m", ())})


SI = {
    "mass": 1.0,
    "stiffness": 4.0,
    "damping": 0.0,
    "initial_displacement": 1.0,
    "initial_velocity": 0.0,
    "duration": 1.0,
}
OPTIONS: dict[str, OptionValue] = {"method": "DOP853", "rtol": 1e-10, "atol": 1e-12, "n_samples": 5}


def test_scipy_adapter_runs_real_integration() -> None:
    result = ScipyOdeAdapter().run("damped_harmonic_oscillator", SI, OPTIONS, seed=1)
    assert result.columns["time"].values == (0.0, 0.25, 0.5, 0.75, 1.0)
    # Undamped, w0 = 2 rad/s: x(t) = cos(2t). Coarse sanity only; full checks are in supervisor.
    assert result.columns["displacement"].values[-1] == pytest.approx(-0.4161468365, abs=1e-8)
    assert result.diagnostics["method"] == "DOP853"
    assert int(result.diagnostics["nfev"]) > 0


def test_scipy_adapter_rejects_unknown_task() -> None:
    with pytest.raises(AdapterError, match="unsupported task"):
        ScipyOdeAdapter().run("pendulum", SI, OPTIONS, None)


def test_scipy_adapter_reports_solver_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import scipy.integrate

    def failing(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(success=False, message="step size too small")

    monkeypatch.setattr(scipy.integrate, "solve_ivp", failing)
    with pytest.raises(AdapterError, match="step size too small"):
        ScipyOdeAdapter().run("damped_harmonic_oscillator", SI, OPTIONS, None)
