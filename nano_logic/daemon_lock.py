"""Single-instance locking for the background monitoring daemon.

Uses an flock()'d PID file so at most one daemon process can ever hold
the lock, even if multiple dashboard instances race to spawn one.
Process-list scanning (checking "is daemon.py already running?" before
spawning) is inherently check-then-act and can't be made atomic; an
flock() on a shared file is a kernel-arbitrated mutex and is.
"""
from __future__ import annotations
import fcntl
import os
from contextlib import contextmanager
from typing import Iterator

from nano_logic.paths import get_state_dir


def _pid_file_path():
    return get_state_dir() / "daemon.pid"


@contextmanager
def acquire_daemon_lock() -> Iterator[bool]:
    """Try to become the sole daemon instance.

    Yields True if the lock was acquired (the caller should run as the
    daemon) or False if another daemon already holds it. The lock is
    released automatically when the context exits, or by the kernel if
    the process dies — no stale-lock cleanup is needed.
    """
    fd = os.open(_pid_file_path(), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return

        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
