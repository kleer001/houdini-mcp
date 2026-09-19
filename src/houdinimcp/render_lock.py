"""Machine-wide GPU render lock (cross-platform).

One machine typically has one GPU. When several Houdini instances share it (each
driven by its own LLM on its own port), two simultaneous renders can exhaust VRAM
and crash the card. This module serializes renders across all instances with a
single OS file lock. The kernel releases the lock when the holder exits, so a
crashed render never deadlocks the machine.

The lock uses `fcntl` on POSIX and `msvcrt` on Windows — no third-party deps.

Environment overrides:
  HOUDINIMCP_RENDER_LOCK=0        disable the lock (e.g. multi-GPU hosts that
                                  manage device assignment themselves).
  HOUDINIMCP_RENDER_LOCK_TIMEOUT  seconds to wait for the GPU before giving up
                                  (default 25, kept under the bridge's 30 s
                                  socket timeout).
"""
import contextlib
import os
import sys
import tempfile
import time

LOCK_PATH = os.path.join(tempfile.gettempdir(), "houdinimcp_render.lock")
ACQUIRE_TIMEOUT = float(os.environ.get("HOUDINIMCP_RENDER_LOCK_TIMEOUT", "25"))
LOCK_DISABLED = os.environ.get("HOUDINIMCP_RENDER_LOCK", "1").strip().lower() not in ("1", "true", "yes")
_POLL_INTERVAL = 0.25


class GPUBusyError(RuntimeError):
    """Raised when the GPU render lock cannot be acquired in time."""


if sys.platform == "win32":
    import msvcrt

    def _try_lock(f):
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(f):
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(f):
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)


@contextlib.contextmanager
def gpu_render_lock():
    """Hold the machine-wide GPU render lock for the duration of the block.

    Raises GPUBusyError if another instance holds the lock past ACQUIRE_TIMEOUT.
    Yields immediately if the lock is disabled via HOUDINIMCP_RENDER_LOCK=0.
    """
    if LOCK_DISABLED:
        yield
        return
    f = open(LOCK_PATH, "a+")
    try:
        deadline = time.time() + ACQUIRE_TIMEOUT
        while not _try_lock(f):
            if time.time() >= deadline:
                raise GPUBusyError(
                    "GPU busy: another Houdini instance is rendering. Retry shortly."
                )
            time.sleep(_POLL_INTERVAL)
        try:
            yield
        finally:
            _unlock(f)
    finally:
        f.close()
