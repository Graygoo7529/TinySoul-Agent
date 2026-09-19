"""Windows process containment; no Action or business Job state lives here.

A suspended child joins an OS Job Object before its initial thread runs.
Descendants inherit membership even if their parent exits immediately.
"""

from __future__ import annotations

from collections.abc import Callable
import ctypes
from ctypes import wintypes
import os
from time import monotonic, sleep


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
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class WindowsProcessJob:
    """One native handle owns an entire invocation, including orphaned children."""

    _api: ctypes.CDLL
    CREATE_SUSPENDED = 0x00000004

    def __init__(self) -> None:
        # Bind lazily: importing TinySoul does not load DLLs or create OS state.
        if os.name != "nt":
            raise OSError("Windows process containment is unavailable on this host")
        self._error: Callable[[], OSError] = lambda: ctypes.WinError(
            ctypes.get_last_error()
        )
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        api.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPDWORD,
        ]
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        api.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
        api.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
        api.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenThread.restype = wintypes.HANDLE
        api.ResumeThread.argtypes = [wintypes.HANDLE]
        api.ResumeThread.restype = wintypes.DWORD
        self._api = api
        handle = api.CreateJobObjectW(None, None)
        if not handle:
            raise self._error()
        self._handle: int | None = handle
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = self._error()
            self.close()
            raise error

    def attach(self, pid: int) -> None:
        """Admit a suspended root, then resume its initial thread."""
        process = self._api.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise self._error()
        try:
            if not self._api.AssignProcessToJobObject(self._handle, process):
                raise self._error()
            self._resume(pid)
        finally:
            self._api.CloseHandle(process)

    def _resume(self, pid: int) -> None:
        # Popen owns the process handle but closes the initial thread handle.
        # The root is still suspended, so its initial thread is stable here.
        snapshot = self._api.CreateToolhelp32Snapshot(0x00000004, 0)  # SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise self._error()
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = self._api.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == pid:
                    thread = self._api.OpenThread(0x0002, False, entry.th32ThreadID)
                    if not thread:
                        raise self._error()
                    try:
                        if self._api.ResumeThread(thread) == 0xFFFFFFFF:
                            raise self._error()
                        return
                    finally:
                        self._api.CloseHandle(thread)
                found = self._api.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("Suspended process initial thread is unavailable")
        finally:
            self._api.CloseHandle(snapshot)

    def terminate(self, timeout_seconds: float) -> None:
        if not self._api.TerminateJobObject(self._handle, 1):
            raise self._error()
        deadline = monotonic() + timeout_seconds
        info = _Accounting()
        while True:
            if not self._api.QueryInformationJobObject(
                self._handle, 1, ctypes.byref(info), ctypes.sizeof(info), None
            ):
                raise self._error()
            if info.ActiveProcesses == 0:
                return
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Controlled process collection has not stopped")
            sleep(min(0.01, remaining))

    def close(self) -> None:
        if self._handle is not None:
            if not self._api.CloseHandle(self._handle):
                raise self._error()
            self._handle = None
