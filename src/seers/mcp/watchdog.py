"""Stop the stdio MCP server once the client that started it is gone.

Every MCP client (each agent session) starts its own stdio server, so several
can run at once. None of them may outlive its client. A server normally stops
when stdin reaches EOF, but EOF never arrives while some other process still
holds an inherited copy of the pipe's write end. As a backstop, wait on the
client process itself:

- Windows: the process that created the stdin pipe. That is the MCP client,
  however many launchers (uv, console-script shims, the venv redirector) sit
  between it and this process.
- Elsewhere: the parent process, polled once a second.

The exit is immediate (``os._exit``): the client is gone, so there is nobody
left to answer, and a thread blocked reading the orphaned pipe would otherwise
stall interpreter shutdown.
"""

from __future__ import annotations

from collections.abc import Callable
import os
import sys
import threading
import time


def _windows_client_exit() -> Callable[[], None] | None:
    """A function that blocks until the stdin pipe's creator exits, or None if stdin is no pipe."""
    import ctypes
    from ctypes import wintypes

    std_input_handle = -10 & 0xFFFFFFFF  # (DWORD)-10
    synchronize_and_query = 0x00100000 | 0x1000  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
    error_access_denied = 5
    infinite = 0xFFFFFFFF

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(ctypes.c_uint64)] * 4]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

    client_pid = wintypes.ULONG()
    stdin = kernel32.GetStdHandle(std_input_handle)
    if not kernel32.GetNamedPipeServerProcessId(stdin, ctypes.byref(client_pid)):
        return None  # a console or a file: nobody to outlive
    if client_pid.value == os.getpid():
        return None

    client = kernel32.OpenProcess(synchronize_and_query, False, client_pid.value)
    if not client:
        if ctypes.get_last_error() == error_access_denied:
            return None  # an elevated client; stdin EOF still applies
        return lambda: None  # the client already exited

    def created(process: int) -> int:
        start, unused = ctypes.c_uint64(), ctypes.c_uint64()
        kernel32.GetProcessTimes(process, start, unused, unused, unused)
        return start.value

    # The pipe was created before this process started. A younger process means
    # the client exited and Windows handed its PID to something else.
    if created(client) > created(kernel32.GetCurrentProcess()):
        return lambda: None
    return lambda: kernel32.WaitForSingleObject(client, infinite)


def _posix_parent_exit() -> Callable[[], None] | None:
    """A function that blocks until the parent exits, or None if already orphaned."""
    parent = os.getppid()
    if parent <= 1:
        return None

    def wait() -> None:
        while os.getppid() == parent:
            time.sleep(1.0)

    return wait


def watch_client() -> None:
    """Exit this process when the MCP client that launched it exits.

    Call it before the stdio transport starts, which points fd 0 at the null device.
    """
    wait = _windows_client_exit() if sys.platform == "win32" else _posix_parent_exit()
    if wait is None:
        return

    def exit_after_client() -> None:
        wait()
        os._exit(0)

    threading.Thread(target=exit_after_client, name="seers-client-watch", daemon=True).start()
