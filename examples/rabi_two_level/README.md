# Example: Rabi oscillation of a two-level system (QuTiP vs closed form)

**Question.** Does QuTiP's `sesolve` (DOP853) reproduce the closed-form Rabi
oscillation of a detuned two-level system over 3 µs? The required accuracy is
1e-8 in every population and Bloch component. The run must also conserve
probability, be deterministic, and converge when solver tolerances are tightened.

**Model.** Rotating frame, rotating-wave approximation, ħ = 1:
`H = (Δ/2)σz + (Ω/2)σx`, with Ω = 2π × 1 MHz, Δ = 2π × 0.25 MHz. The system starts
in `|0⟩ = qutip.basis(2, 0)`, the +1 eigenstate of σz. The reference is
`P1(t) = (Ω²/W²) sin²(Wt/2)` with `W = √(Ω² + Δ²)`, plus the matching Bloch
components (see `kobald/supervisor/rabi.py`).

**Units.** Frequencies must be given with an explicit angle unit (`rad/s`,
`Mrad/s`, `turn/s`). `Hz` and `1/s` are **rejected**, because Pint treats the
radian as dimensionless and would silently convert 1 MHz to 1e6 rad/s, a 2π error.

```powershell
python -m pip install -e ".[dev,science-core,engine-qutip]"
kobald-science run examples/rabi_two_level/spec.json
kobald-science verify-record runs/<record-id>
```

## Observed result (2026-11-23, Windows 11, Python 3.13.17, QuTiP 5.3.1)

| Check | Measured | Threshold |
|---|---|---|
| P1 vs closed form | 1.33e-15 | 2e-09 |
| P0 vs closed form | 1.44e-15 | 2e-09 |
| ⟨σx⟩ vs closed form | 7.77e-16 | 2e-09 |
| ⟨σy⟩ vs closed form | 2.86e-15 | 2e-09 |
| probability conservation, max abs(P0 + P1 − 1) | 4.44e-16 | 2e-09 |
| Bloch vector length, max abs(abs(r) − 1) | 4.44e-16 | 2e-09 |
| P1 error after tightening rtol/atol by 100× | 1.33e-15 | ≤ 2.2e-13 (roundoff floor) |
| bitwise reproducibility of an identical re-run | identical | identical |

As an independent cross-check, a matrix exponential `expm(−iHt)|0⟩` of the 2×2
Hamiltonian, computed outside Kobald, agrees with the saved P1 table to 1.9e-15.
The three executions took 0.85, 0.83 and 0.83 s, with about 100 MB peak committed
memory each.

**Limits of the evidence.**
- At these tolerances the primary run is already at roundoff, so the convergence
  check only confirms that tightening did not make things worse.
- The model is a coherent, closed two-level system. It has no decoherence or
  time-dependent drive, and this example validates nothing beyond that case.
- Bitwise reproducibility is claimed for the same machine and library versions only.
- The example's automated tests pass in CI on Ubuntu (Python 3.11 and 3.13) and Windows
  (Python 3.13). The accuracy figures above come from the Windows run only.
