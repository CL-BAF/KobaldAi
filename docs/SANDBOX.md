# Scientific sandbox: audit results and backend design

## Scope

The sandbox runs **only Kobald's own engine adapters** on validated, SI-normalised
parameters. It is not designed to run untrusted code, and Kobald exposes no path
that executes arbitrary commands. Model-initiated experiments are denied by
policy (`allow_model_requests=False`). Both stay disabled until the confinement
gaps below are closed and WARDEN/AUDITOR are migrated.

## Current backend: `local-subprocess`

| Property | Windows (Job Object) | Linux/macOS (process group + rlimits) |
|---|---|---|
| Separate interpreter, `python -I`, dedicated cwd/TEMP/HOME | enforced | enforced |
| Environment scrubbed (no API keys or user variables) | **enforced, tested** | enforced (CI pending) |
| Wall clock from spawn to tree reaped, total across experiment | **enforced, tested** | enforced (CI pending) |
| Process-tree kill on timeout | **enforced, tested** (grandchild killed) | `killpg`; descendant calling `setsid` escapes |
| Process-tree kill after normal exit | **enforced, tested** | `killpg` on group |
| Memory limit | committed memory of whole job (`JOB_OBJECT_LIMIT_JOB_MEMORY`); **tested**: 600 MB allocation under a 256 MB cap → `MemoryError` | `RLIMIT_AS` per process (virtual address space, not resident memory) |
| Peak memory recorded | job peak committed bytes | worker reports `VmPeak`/`VmHWM` |
| Output size cap | enforced after exit | enforced after exit |
| Network isolation | **NOT enforced**: a child connected to a localhost listener (test `..._gap`) | **NOT enforced** |
| Filesystem confinement | **NOT enforced**: a child read and wrote files outside its workdir (test `..._gap`) | **NOT enforced** |
| Reduced privileges | **NOT enforced**: the child runs with the user's full token and can read anything the user can, including credentials and SSH keys | **NOT enforced** |

Windows results come from `tests/test_science_sandbox.py` on Windows 11 /
CPython 3.13.17 (2026-11-23). Linux results are **not yet observed**: they need
the Ubuntu CI jobs to run.

### Known windows and limits

- `subprocess.Popen` cannot start a process suspended, so the worker joins the Job
  Object a few milliseconds after it starts. A process spawned in that window
  would not be in the job. The worker is Kobald code and spawns nothing during
  start-up.
- If the Job Object cannot be created or assigned, the execution fails closed
  with status `setup_error`; the child is killed.
- `RLIMIT_AS` limits virtual address space. BLAS libraries reserve large virtual
  regions, so an `RLIMIT_AS` cap can fail a job whose resident memory is small.
  `scripts/memory_probe.py` ran the oscillator demo in Ubuntu CI (Python 3.11)
  under these `RLIMIT_AS` caps:

  | Cap | Result |
  |---|---|
  | 256 MB | failed: OpenBLAS could not allocate its buffers |
  | 384 MB | passed |
  | 512 MB | passed |
  | 768 MB | passed |
  | 1024 MB | passed |

  This shows only that this one small SciPy job fits in 512 MB on that runner.
  It is not evidence that other engines or larger workloads do. The default
  stays at `memory_mb=1024`.
- Memory is a per-process limit; it is not summed across the three executions.
  Wall time and output bytes are experiment totals.

## Planned backend: isolated Linux worker (WSL2 or container)

Purpose: stronger confinement and access to Linux-only engines (FEniCSx, PySCF,
OpenFOAM, GROMACS). It implements the existing `ExecutionBackend` protocol, so the
runner, records and verification do not change.

```text
host (Windows)                          isolated Linux worker
--------------                          ---------------------
ExperimentRunner
  -> LinuxWorkerBackend.execute(job)
       create per-execution dir   --->  bind-mounted read-write at /work (only mount)
       write job.json                   image: pinned engine env (conda lockfile)
       start worker with limits   --->  python -I -m kobald.runtime.science_worker /work
       wait (wall clock)                --network=none, read-only rootfs, non-root uid,
       kill on timeout                  no capabilities, seccomp default, pids limit,
       read result.json + table   <---  memory/cpu cgroup limits
       destroy worker
```

Requirements before it may be marked enforced:

1. **Network:** `--network=none` (container) or an unshared network namespace;
   verified by a test that a connection to a host listener fails.
2. **Filesystem:** only the execution directory mounted read-write; image
   read-only; verified by tests that a host path is not visible.
3. **Privileges:** non-root user, all capabilities dropped, `no-new-privileges`.
4. **Resources:** cgroup memory (resident, not address space), CPU and pid limits;
   peak memory read from the cgroup.
5. **Reproducibility:** image digest and engine lockfile hash in every record.
6. **Fail closed:** if the runtime (Docker/Podman/WSL) is unavailable, the
   execution fails with `setup_error`; it never falls back to the local backend
   for a task that requires isolation.

WSL2 on its own is **not** a sandbox: by default it mounts Windows drives
(`/mnt/c`) and shares the user's network. A WSL2-based backend must run a
container inside WSL2, or disable automount and use a network namespace.

Prerequisites on the development workstation: WSL2 is not installed and no
container runtime was found (2026-11-23).
