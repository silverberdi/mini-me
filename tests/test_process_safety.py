# Focused Task Group 7 tests: deterministic process-safety proving for CLI runners.

import asyncio
import os
import sys

import pytest

from minime.services.implementer_runner import CliImplementerRunner
from minime.services.reviewer_runner import CliReviewerRunner

SLEEPER = """import time
time.sleep(60)"""


SIGTERM_GRACEFUL = """import os, signal, sys
marker = sys.argv[1]
def handler(signum, frame):
    with open(marker, "w") as f:
        f.write("sigterm")
    sys.exit(0)
signal.signal(signal.SIGTERM, handler)
import time
time.sleep(60)"""


SIGTERM_IGNORE = """import os, signal, sys
marker = sys.argv[1]
def handler(signum, frame):
    with open(marker, "w") as f:
        f.write("sigterm")
signal.signal(signal.SIGTERM, handler)
import time
time.sleep(60)"""


SPAWN_CHILD = """import os, subprocess, sys, time
pidfile = sys.argv[1]
if len(sys.argv) > 2:
    time.sleep(60)
else:
    child = subprocess.Popen([sys.executable, sys.argv[0], pidfile, "x"])
    with open(pidfile, "w") as f:
        f.write(str(child.pid) + " " + str(os.getpgrp()))
    time.sleep(60)"""


FLOOD = """import sys
for i in range(5000):
    print("token=secret123 line", i)"""


EXIT3 = """import sys
sys.exit(3)"""


def _write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body)
    return path


def _is_dead(pid):
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return True
    return False


async def _wait_dead(pid):
    for _ in range(50):
        if _is_dead(pid):
            return True
        await asyncio.sleep(0.1)
    return _is_dead(pid)


async def test_implementer_timeout_returns_timeout_result(tmp_path):
    script = _write(tmp_path, "sleeper.py", SLEEPER)
    runner = CliImplementerRunner([sys.executable, str(script)])
    result = await runner.run(tmp_path, "", timeout_seconds=1)
    assert result.timed_out is True
    assert result.exit_code != 0


async def test_reviewer_timeout_returns_timeout_result(tmp_path):
    script = _write(tmp_path, "sleeper.py", SLEEPER)
    runner = CliReviewerRunner([sys.executable, str(script)])
    result = await runner.run(tmp_path, "", timeout_seconds=1)
    assert result.timed_out is True
    assert result.exit_code != 0


async def test_timeout_sends_sigterm_and_process_exits_gracefully(tmp_path):
    marker = tmp_path / "marker.txt"
    script = _write(tmp_path, "graceful.py", SIGTERM_GRACEFUL)
    runner = CliImplementerRunner([sys.executable, str(script), str(marker)])
    result = await runner.run(tmp_path, "", timeout_seconds=1)
    assert result.timed_out is True
    assert marker.exists()
    assert marker.read_text() == "sigterm"


async def test_process_ignoring_sigterm_is_sigkilled(tmp_path):
    marker = tmp_path / "marker.txt"
    script = _write(tmp_path, "ignore.py", SIGTERM_IGNORE)
    runner = CliImplementerRunner([sys.executable, str(script), str(marker)])
    result = await runner.run(tmp_path, "", timeout_seconds=1)
    assert result.timed_out is True
    assert marker.exists()
    assert marker.read_text() == "sigterm"


async def test_timeout_terminates_process_group_and_child(tmp_path):
    pidfile = tmp_path / "pids.txt"
    script = _write(tmp_path, "spawn_child.py", SPAWN_CHILD)
    runner = CliImplementerRunner([sys.executable, str(script), str(pidfile)])
    await runner.run(tmp_path, "", timeout_seconds=1)
    parent_pgid, child_pid = [int(x) for x in pidfile.read_text().split()]
    assert await _wait_dead(child_pid)
    assert await _wait_dead(parent_pgid)


async def test_cancellation_cleans_up_process_group(tmp_path):
    pidfile = tmp_path / "pids.txt"
    script = _write(tmp_path, "spawn_child.py", SPAWN_CHILD)
    runner = CliImplementerRunner([sys.executable, str(script), str(pidfile)])
    task = asyncio.create_task(runner.run(tmp_path, "", timeout_seconds=60))
    for _ in range(100):
        if pidfile.exists():
            break
        await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    parent_pgid, child_pid = [int(x) for x in pidfile.read_text().split()]
    assert await _wait_dead(child_pid)
    assert await _wait_dead(parent_pgid)


async def test_cancellation_cleanup_complete_before_cancelled_error_propagates(tmp_path):
    """Leaf G: process-group cleanup must be complete at the instant CancelledError
    propagates, not merely eventually after polling."""
    pidfile = tmp_path / "pids.txt"
    script = _write(tmp_path, "spawn_child.py", SPAWN_CHILD)
    runner = CliImplementerRunner([sys.executable, str(script), str(pidfile)])
    task = asyncio.create_task(runner.run(tmp_path, "", timeout_seconds=60))
    for _ in range(100):
        if pidfile.exists():
            break
        await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    parent_pgid, _child_pid = [int(x) for x in pidfile.read_text().split()]
    # No polling: the spawned process group leader must already be reaped.
    assert _is_dead(parent_pgid)


async def test_reviewer_cancellation_cleanup_complete_before_cancelled_error_propagates(
    tmp_path,
):
    """Leaf G (reviewer): same deterministic cleanup guarantee for the reviewer runner."""
    pidfile = tmp_path / "pids.txt"
    script = _write(tmp_path, "spawn_child.py", SPAWN_CHILD)
    runner = CliReviewerRunner([sys.executable, str(script), str(pidfile)])
    task = asyncio.create_task(runner.run(tmp_path, "", timeout_seconds=60))
    for _ in range(100):
        if pidfile.exists():
            break
        await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    parent_pgid, _child_pid = [int(x) for x in pidfile.read_text().split()]
    assert _is_dead(parent_pgid)


async def test_output_bounded_and_redacted(tmp_path):
    script = _write(tmp_path, "flood.py", FLOOD)
    runner = CliImplementerRunner([sys.executable, str(script)])
    result = await runner.run(tmp_path, "", timeout_seconds=30)
    assert result.timed_out is False
    assert len(result.stdout) <= CliImplementerRunner.MAX_OUTPUT_LINES
    assert not any("secret123" in line for line in result.stdout)
    assert any("[REDACTED]" in line for line in result.stdout)


async def test_process_failure_returns_truthful_exit_code(tmp_path):
    script = _write(tmp_path, "exit3.py", EXIT3)
    runner = CliImplementerRunner([sys.executable, str(script)])
    result = await runner.run(tmp_path, "", timeout_seconds=10)
    assert result.timed_out is False
    assert result.exit_code == 3
