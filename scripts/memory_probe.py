"""Diagnostic: peak memory of a sandbox-equivalent oscillator job on Linux.

Runs the worker in a child interpreter exactly as the sandbox does (``python -I``,
scrubbed environment, single-threaded BLAS) under several ``RLIMIT_AS`` caps and
prints whether it succeeded plus the child's VmPeak (virtual) and VmHWM
(resident) as reported in result.json. Linux only; prints a notice elsewhere.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

JOB = {
    "engine": "scipy",
    "task": "damped_harmonic_oscillator",
    "parameters": {
        "mass": 0.25,
        "stiffness": 40.0,
        "damping": 0.316227766,
        "initial_displacement": 0.05,
        "initial_velocity": 0.0,
        "duration": 5.0,
    },
    "options": {"method": "DOP853", "rtol": 1e-10, "atol": 1e-12, "n_samples": 2001},
    "seed": 0,
}


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("memory probe: Linux only; skipped")
        return 0
    from kobald.research.spec import ResourceBudget
    from kobald.runtime.sandbox import SubprocessSandbox

    for memory_mb in (256, 384, 512, 768, 1024):
        with tempfile.TemporaryDirectory() as tmp:
            budget = ResourceBudget(wall_time_s=60, memory_mb=memory_mb, max_output_bytes=10**7)
            outcome = SubprocessSandbox().execute(JOB, Path(tmp) / "run", budget)
            usage = (outcome.result or {}).get("resource_usage", {})
            tail = outcome.stderr_tail.strip().splitlines()[-1:] if outcome.stderr_tail else []
            print(
                json.dumps(
                    {
                        "rlimit_as_mb": memory_mb,
                        "status": outcome.status.value,
                        "usage": usage,
                        "stderr_last_line": tail,
                        "cpu_count": os.cpu_count(),
                    }
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
