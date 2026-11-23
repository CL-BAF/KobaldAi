"""Minimal Windows Job Object wrapper (ctypes) for sandbox process-tree control.

What a Job Object gives the sandbox:
  * every process the worker spawns is in the job, so TerminateJobObject and
    KILL_ON_JOB_CLOSE kill the whole tree (no orphaned grandchildren);
  * a cap on total *committed* memory of the job (JOB_OBJECT_LIMIT_JOB_MEMORY);
  * the peak committed memory, for the execution record.

What it does NOT give: network isolation, filesystem confinement, or a reduced
security token. The child still runs with the user's full privileges.

Known window: ``subprocess.Popen`` cannot start a process suspended, so the
worker is assigned to the job a few milliseconds after it starts. A process
spawned by the worker inside that window would not be in the job. The worker
is Kobald's own code and spawns nothing during interpreter start-up, so this is
documented rather than mitigated.

The platform guard keeps mypy and coverage on other platforms from analysing
Windows-only APIs; this module is exercised by tests on Windows CI.
"""

from __future__ import annotations

import sys

__all__ = ["JobObjectError"]


class JobObjectError(OSError):
    """Raised when a Job Object cannot be created, configured or assigned."""


if sys.platform == "win32":  # pragma: windows-only
    import ctypes
    from ctypes import wintypes

    __all__ += ["WindowsJob"]

    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
    ]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    def _fail(what: str) -> JobObjectError:
        code = ctypes.get_last_error()
        return JobObjectError(code, f"{what} failed: {ctypes.FormatError(code)}")

    class WindowsJob:
        """A kill-on-close Job Object with a committed-memory cap."""

        def __init__(self, memory_limit_bytes: int) -> None:
            handle = _kernel32.CreateJobObjectW(None, None)
            if not handle:
                raise _fail("CreateJobObjectW")
            self._handle: int | None = handle
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = (
                _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | _JOB_OBJECT_LIMIT_JOB_MEMORY
                | _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
            )
            info.JobMemoryLimit = memory_limit_bytes
            if not _kernel32.SetInformationJobObject(
                handle, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
            ):
                error = _fail("SetInformationJobObject")
                self.close()
                raise error

        def assign(self, process_handle: int) -> None:
            if not _kernel32.AssignProcessToJobObject(self._handle, process_handle):
                raise _fail("AssignProcessToJobObject")

        def terminate(self) -> None:
            if self._handle is not None:
                _kernel32.TerminateJobObject(self._handle, 1)

        def peak_memory_bytes(self) -> int | None:
            if self._handle is None:
                return None
            info = _ExtendedLimits()
            ok = _kernel32.QueryInformationJobObject(
                self._handle,
                _JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
                None,
            )
            return int(info.PeakJobMemoryUsed) if ok else None

        def close(self) -> None:
            # KILL_ON_JOB_CLOSE: closing the last handle kills any survivors.
            if self._handle is not None:
                _kernel32.CloseHandle(self._handle)
                self._handle = None
