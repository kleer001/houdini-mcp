"""Tests for the machine-wide GPU render lock.

Cross-process contention is tested with a real subprocess holder so the test is
valid on every platform the lock supports (POSIX fcntl and Windows msvcrt behave
differently for same-process locks).
"""
import importlib.util
import os
import subprocess
import sys
import time

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOCK_PY = os.path.join(_ROOT, "src", "houdinimcp", "render_lock.py")


def _load():
    """Load render_lock.py directly (pure stdlib) without the hou-importing package."""
    spec = importlib.util.spec_from_file_location("_render_lock", _LOCK_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


render_lock = _load()
GPUBusyError = render_lock.GPUBusyError
gpu_render_lock = render_lock.gpu_render_lock


# Subprocess that acquires the lock, signals readiness, and holds until a stop file appears.
_HOLDER = """
import importlib.util, os, sys, time
spec = importlib.util.spec_from_file_location("_rl", sys.argv[1])
rl = importlib.util.module_from_spec(spec); spec.loader.exec_module(rl)
ready, stop = sys.argv[2], sys.argv[3]
with rl.gpu_render_lock():
    open(ready, "w").close()
    while not os.path.exists(stop):
        time.sleep(0.02)
"""


def test_lock_acquires_and_releases_when_free():
    with gpu_render_lock():
        pass
    with gpu_render_lock():
        pass


def test_lock_reusable_in_sequence():
    for _ in range(3):
        with gpu_render_lock():
            pass


def test_busy_raises_then_frees(tmp_path, monkeypatch):
    monkeypatch.setattr(render_lock, "ACQUIRE_TIMEOUT", 0.4)
    ready = tmp_path / "ready"
    stop = tmp_path / "stop"
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, _LOCK_PY, str(ready), str(stop)]
    )
    try:
        for _ in range(200):  # wait up to ~4 s for the holder to grab the lock
            if ready.exists():
                break
            time.sleep(0.02)
        assert ready.exists(), "holder subprocess never acquired the lock"

        with pytest.raises(GPUBusyError):
            with gpu_render_lock():
                pass
    finally:
        stop.write_text("")  # release the holder
        holder.wait(timeout=5)

    # Lock is free again.
    with gpu_render_lock():
        pass


def test_disabled_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(render_lock, "LOCK_DISABLED", True)
    ready = tmp_path / "ready"
    stop = tmp_path / "stop"
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, _LOCK_PY, str(ready), str(stop)]
    )
    try:
        for _ in range(200):
            if ready.exists():
                break
            time.sleep(0.02)
        assert ready.exists()
        # Disabled: acquires immediately despite the holder.
        with gpu_render_lock():
            pass
    finally:
        stop.write_text("")
        holder.wait(timeout=5)
