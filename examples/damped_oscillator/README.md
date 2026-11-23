# Example: damped harmonic oscillator (SciPy vs closed form)

**Question.** Does SciPy's adaptive DOP853 integrator reproduce the closed-form motion
of an under-damped mass–spring–damper (ζ ≈ 0.05) over about ten natural periods, to
within a relative tolerance of 1e-7? Are the results deterministic, and does the
error shrink when the integrator tolerances are tightened?

**Model.** `m x'' + c x' + k x = 0`, with m = 250 g, k = 40 N/m, c = 0.316227766 kg/s,
x(0) = 5 cm, x'(0) = 0 and t ∈ [0, 5] s. This gives ω₀ = √(k/m) ≈ 12.65 rad/s,
ζ = c / (2√(km)) = 0.05, and a period of ≈ 0.497 s. The parameters are deliberately
given in mixed units (g, cm, kg/s); Kobald converts them to SI and records both.

**Run it.**

```powershell
python -m pip install -e ".[dev,science-core]"
kobald-science run examples/damped_oscillator/spec.json
```

Output goes to `runs/<record-id>/`, which is gitignored and contains `record.json`,
`record.sha256`, `report.md`, `figure.png` and `exec-{primary,replicate,refined}/`.

## Observed result (2026-11-23, Windows 11, Python 3.13.17, SciPy 1.18.1, NumPy 2.5.5)

| Check | Measured | Threshold | Result |
|---|---|---|---|
| units (declared outputs; dimension of √(k/m)) | s, m, m/s; 1/[time] | s, m, m/s | pass |
| time grid | ends at 5.0 s | 5.0 s | pass |
| max displacement error vs closed form | 7.25e-12 m | 5.1e-09 m | pass |
| max velocity error vs closed form | 9.01e-11 m/s | 5.87e-08 m/s | pass |
| largest step-to-step energy rise | 0.0 J | 5.1e-09 J | pass |
| error after tightening rtol/atol by 100× | 8.26e-14 m | ≤ 7.25e-12 m | pass |
| bitwise reproducibility of an identical re-run | identical SHA-256 | identical | pass |

The primary and replicate runs each used 2861 RHS evaluations; the refined run used 5120.

**What this does and does not show.** It shows that this engine, adapter and pipeline
give a correct answer on a problem with a known exact solution, are deterministic on
this machine, and converge under refinement. It does not validate SciPy for problems
without a reference. Bitwise reproducibility is only claimed for the same
machine and library versions. With c > 0 the energy check is a weak test, since
the true energy decreases monotonically; it is stronger in the undamped case (c = 0).
