# Scientific engine compatibility matrix

Evidence captured on 2026-11-23 on the development workstation (Windows 11 Pro
10.0.26200, CPython 3.13.17, x86-64, no WSL2 installed). Re-check any machine with:

```powershell
kobald-science engines            # side-effect-free detection (no engine is imported)
python scripts/engine_smoke.py    # imports each engine in an isolated subprocess, one trivial call
```

## Column meanings

| Column | Meaning |
|---|---|
| Installed | Distribution metadata found **and** the module is locatable (`kobald-science engines`). |
| Smoke | `scripts/engine_smoke.py`: imported in `python -I` and one trivial real call succeeded. Not scientific validation. |
| Adapter | A Kobald adapter exposes typed tasks for this engine. |
| Verified | An adapter task has an independent reference verifier whose checks passed in a real run. |

## Matrix

| Engine | Domain | Version found | Installed | Smoke | Adapter | Verified | Status |
|---|---|---|---|---|---|---|---|
| SciPy | mathematics | 1.18.1 | yes | pass | `damped_harmonic_oscillator` | yes (closed form) | **Operational** |
| NumPy | mathematics | 2.5.5 | yes | pass | used by verifier and figures | — | **Operational as support library** |
| Pint | mathematics | 0.26.2 | yes | pass | used for unit validation | — | **Operational as support library** |
| SymPy | mathematics | 1.14.0 | yes | pass | no (used in tests to cross-check the reference) | — | Partially integrated |
| MuJoCo | physics | 4.0.1 | yes | pass | no | no | Detected only |
| QuTiP | physics | 5.3.1 | yes | pass | no | no | Detected only |
| OpenMM | physics | 8.6.1 | yes | pass (Reference platform) | no | no | Detected only |
| RDKit | chemistry | 2026.9.2 | yes | pass (first import ~15 s) | no | no | Detected only |
| Cantera | chemistry | 3.2.0 | yes | pass | no | no | Detected only |
| ASE | materials | **3.30.0b1 (beta)** | yes | pass | no | no | Detected only; beta release |
| PyBaMM | engineering | 26.10.1.1 | yes | pass | no | no | Detected only |
| Biopython | biology | 1.88 | yes | pass | no | no | Detected only |
| COBRApy | biology | 0.32.1 | yes | pass | no | no | Detected only |
| Astropy | astronomy | 8.0.3 | yes | pass | no | no | Detected only |
| FEniCSx (DOLFINx) | physics | — | **no** | fail (`No module named 'dolfinx'`) | no | no | Unsupported here: needs Linux/WSL2 + conda-forge |
| PySCF | chemistry | — | **no** | fail (`No module named 'pyscf'`) | no | no | Unsupported here: needs Linux/WSL2 |
| OpenFOAM | engineering | — | **no** | not run | no (catalogue entry only) | no | Not installed |
| GROMACS | chemistry | — | **no** | not run | no (catalogue entry only) | no | Not installed |

Notes on files present in the parent workspace (outside the repository):

- `pyscf-2.15.1.zip`, `rdkit-master.zip`, `PyBaMM-pybammsolvers-v0.12.0.zip` and
  `mujoco-4.0.1-windows-x86_64.zip` are source or binary downloads. They are not what
  Kobald detects; detection reflects what is installed in the Python environment.
- The file named `-` is an OpenFOAM `ThirdParty-14` **source** tarball. OpenFOAM itself is
  not built or installed.

## Installation

Engines are optional extras, so users install only what they need:

```powershell
python -m pip install -e ".[dev,science-core]"        # framework + SciPy demo
python -m pip install -e ".[engine-rdkit,engine-cantera]"   # add individual engines
```

`science-core` = NumPy, SciPy, Pint and Matplotlib. There is one `engine-<id>` extra per
PyPI-installable engine.

### Linux-only engines (FEniCSx, PySCF, OpenFOAM, GROMACS)

These have no supported native Windows build. The intended route is an **isolated Linux
execution backend**, not Windows workarounds:

1. Install WSL2 (`wsl --install`, then reboot). WSL2 is **not installed** on the current
   workstation.
2. Inside WSL2, create a dedicated environment, e.g.
   `conda create -n kobald-linux -c conda-forge fenics-dolfinx pyscf`, or install
   OpenFOAM/GROMACS from their distribution packages.
3. Implement the isolated Linux worker backend designed in [SANDBOX.md](SANDBOX.md) behind the existing
   `kobald.runtime.sandbox.ExecutionBackend` protocol so jobs and results cross the
   boundary as `job.json` / `result.json` exactly as with the local subprocess backend.

Step 3 is not implemented yet.

## Python version note

NumPy ≥ 2.5, SciPy ≥ 1.18 and Pint ≥ 0.26 require Python ≥ 3.12. The project still
targets Python 3.11+, so pip resolves older releases on 3.11. To keep mypy checking at
the 3.11 floor, `pyproject.toml` treats NumPy and Pint as untyped
(`follow_imports = "skip"`).
