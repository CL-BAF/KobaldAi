"""Opt-in engine smoke test used to build docs/SCIENCE_ENGINES.md.

Each engine is imported in its own isolated subprocess (``python -I``) with a
timeout and must complete one trivial real call. A pass means "importable and
callable on this machine" — it is NOT an adapter, and NOT scientific validation.

Usage: python scripts/engine_smoke.py [--json]
CPU only; nothing here requests a GPU.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

SMOKES: dict[str, str] = {
    "numpy": "import numpy as n; assert abs(n.linalg.det(n.eye(3)*2)-8)<1e-12",
    "scipy": "from scipy.integrate import quad; import math; "
    "assert abs(quad(math.sin,0,math.pi)[0]-2)<1e-12",
    "sympy": "import sympy as s; x=s.symbols('x'); assert s.integrate(x**2,(x,0,3))==9",
    "pint": "import pint; u=pint.UnitRegistry(); assert (1*u.km).to('m').magnitude==1000",
    "mujoco": "import mujoco; m=mujoco.MjModel.from_xml_string("
    "'<mujoco><worldbody><body><freejoint/><geom size=\".1\"/></body></worldbody></mujoco>'); "
    "d=mujoco.MjData(m); mujoco.mj_step(m,d); assert d.time>0",
    "qutip": "import qutip as q; assert abs(q.expect(q.sigmaz(), q.basis(2,0))-1)<1e-12",
    "fenicsx": "import dolfinx",
    "openmm": "import openmm; p=openmm.Platform.getPlatformByName('Reference'); "
    "assert p.getName()=='Reference'",
    "rdkit": "from rdkit import Chem; from rdkit.Chem import Descriptors; "
    "assert abs(Descriptors.MolWt(Chem.MolFromSmiles('CCO'))-46.069)<0.01",
    "pyscf": "from pyscf import gto, scf; "
    "assert scf.RHF(gto.M(atom='H 0 0 0; H 0 0 0.74', basis='sto-3g')).kernel()<0",
    "cantera": "import cantera as ct; g=ct.Solution('h2o2.yaml'); "
    "g.TPX=300,ct.one_atm,'H2:1'; assert g.density>0",
    "ase": "from ase.build import molecule; assert len(molecule('H2O'))==3",
    "pybamm": "import pybamm; m=pybamm.lithium_ion.SPM(); assert m.name",
    "biopython": "from Bio.Seq import Seq; assert str(Seq('ATGC').reverse_complement())=='GCAT'",
    "cobra": "import cobra; m=cobra.Model('t'); r=cobra.Reaction('R'); "
    "m.add_reactions([r]); assert len(m.reactions)==1",
    "astropy": "from astropy import units as u, constants as c; "
    "assert abs(c.c.to(u.km/u.s).value-299792.458)<1e-6",
}


def run_one(code: str, timeout: float = 120.0) -> dict[str, object]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"passed": False, "seconds": timeout, "error": "timeout"}
    error = proc.stderr.strip().splitlines()[-1] if proc.returncode else ""
    return {
        "passed": proc.returncode == 0,
        "seconds": round(time.perf_counter() - started, 2),
        "error": error[:200],
    }


def main() -> int:
    results = {name: run_one(code) for name, code in SMOKES.items()}
    if "--json" in sys.argv:
        print(json.dumps(results, indent=2))
    else:
        for name, result in results.items():
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{name:<10} {status}  {result['seconds']:>6}s  {result['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
