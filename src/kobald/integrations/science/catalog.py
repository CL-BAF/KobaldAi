"""Catalogue of scientific engines Kobald knows about, and side-effect-free probing.

Probing never imports an engine module: Python engines are located with
``importlib.util.find_spec`` and versioned with ``importlib.metadata``;
external executables are located with ``shutil.which``. Detection says that
software is *present*, not that Kobald can drive it correctly.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = [
    "ENGINE_CATALOG",
    "EngineDescriptor",
    "EngineKind",
    "EngineProbe",
    "probe_engine",
]


class EngineKind(Enum):
    PYTHON = "python"
    EXECUTABLE = "executable"


@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    engine_id: str
    display_name: str
    domain: str
    kind: EngineKind
    distributions: tuple[str, ...] = ()
    import_name: str | None = None
    executables: tuple[str, ...] = ()
    install_extra: str | None = None
    needs_isolated_linux_env: bool = False
    notes: str = ""


@dataclass(frozen=True, slots=True)
class EngineProbe:
    engine_id: str
    installed: bool
    version: str | None
    location: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "installed": self.installed,
            "version": self.version,
            "location": self.location,
        }


def _py(
    engine_id: str,
    name: str,
    domain: str,
    distributions: tuple[str, ...],
    import_name: str,
    *,
    linux: bool = False,
    notes: str = "",
) -> EngineDescriptor:
    return EngineDescriptor(
        engine_id=engine_id,
        display_name=name,
        domain=domain,
        kind=EngineKind.PYTHON,
        distributions=distributions,
        import_name=import_name,
        install_extra=f"engine-{engine_id}",
        needs_isolated_linux_env=linux,
        notes=notes,
    )


ENGINE_CATALOG: tuple[EngineDescriptor, ...] = (
    _py("numpy", "NumPy", "mathematics", ("numpy",), "numpy"),
    _py("scipy", "SciPy", "mathematics", ("scipy",), "scipy"),
    _py("sympy", "SymPy", "mathematics", ("sympy",), "sympy"),
    _py("pint", "Pint", "mathematics", ("pint", "Pint"), "pint"),
    _py("mujoco", "MuJoCo", "physics", ("mujoco",), "mujoco"),
    _py("qutip", "QuTiP", "physics", ("qutip",), "qutip"),
    _py(
        "fenicsx",
        "FEniCSx (DOLFINx)",
        "physics",
        ("fenics-dolfinx",),
        "dolfinx",
        linux=True,
        notes="No native Windows build; install via conda-forge in WSL2/Linux.",
    ),
    _py("openmm", "OpenMM", "physics", ("openmm",), "openmm"),
    _py("rdkit", "RDKit", "chemistry", ("rdkit", "rdkit-pypi"), "rdkit"),
    _py(
        "pyscf",
        "PySCF",
        "chemistry",
        ("pyscf",),
        "pyscf",
        linux=True,
        notes="No official Windows wheels; install in WSL2/Linux.",
    ),
    _py("cantera", "Cantera", "chemistry", ("cantera",), "cantera"),
    _py("ase", "ASE", "materials", ("ase",), "ase"),
    _py("pybamm", "PyBaMM", "engineering", ("pybamm",), "pybamm"),
    _py("biopython", "Biopython", "biology", ("biopython",), "Bio"),
    _py("cobra", "COBRApy", "biology", ("cobra",), "cobra"),
    _py("astropy", "Astropy", "astronomy", ("astropy",), "astropy"),
    EngineDescriptor(
        engine_id="openfoam",
        display_name="OpenFOAM",
        domain="engineering",
        kind=EngineKind.EXECUTABLE,
        executables=("blockMesh", "simpleFoam"),
        needs_isolated_linux_env=True,
        notes="External executable; intended to run inside WSL2/Linux or a container.",
    ),
    EngineDescriptor(
        engine_id="gromacs",
        display_name="GROMACS",
        domain="chemistry",
        kind=EngineKind.EXECUTABLE,
        executables=("gmx", "gmx_mpi"),
        needs_isolated_linux_env=True,
        notes="External executable; intended to run inside WSL2/Linux or a container.",
    ),
)


def _distribution_version(names: tuple[str, ...]) -> str | None:
    for name in names:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


def _module_location(import_name: str) -> str | None:
    try:
        spec = importlib.util.find_spec(import_name)
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None
    return spec.origin or "namespace package"


def probe_engine(
    descriptor: EngineDescriptor,
    which: Callable[[str], str | None] = shutil.which,
) -> EngineProbe:
    """Detect an engine without importing or executing it."""
    if descriptor.kind is EngineKind.EXECUTABLE:
        for executable in descriptor.executables:
            path = which(executable)
            if path is not None:
                # Version requires running the binary; deferred to an adapter smoke test.
                return EngineProbe(descriptor.engine_id, True, None, path)
        return EngineProbe(descriptor.engine_id, False, None, None)

    assert descriptor.import_name is not None
    location = _module_location(descriptor.import_name)
    version = _distribution_version(descriptor.distributions)
    return EngineProbe(
        engine_id=descriptor.engine_id,
        installed=location is not None and version is not None,
        version=version,
        location=location,
    )
