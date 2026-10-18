"""Tests for intelligent progress watchdog, activity tracking, and loop detection."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from minime.services.progress_watchdog import (
    ProgressWatchdog,
    WatchdogSignal,
    WatchdogState,
    detect_repetitive_loop,
    detect_zero_diff_stagnation,
)


def test_watchdog_state_progression_and_activity_reset(tmp_path: Path):
    watchdog = ProgressWatchdog(
        worktree_path=tmp_path,
        inactivity_threshold_seconds=0.1,
        stall_timeout_seconds=0.3,
        check_interval_seconds=0.05,
    )
    assert watchdog.state == WatchdogState.RUNNING

    # After short delay exceeding inactivity_threshold, transitions to SUSPECTED_STALL
    time.sleep(0.12)
    state = watchdog.evaluate_tick()
    assert state == WatchdogState.SUSPECTED_STALL

    # An activity signal (e.g. stdout) resets back to RUNNING
    watchdog.record_activity(WatchdogSignal.STDOUT_EMISSION, "test stdout line")
    assert watchdog.state == WatchdogState.RUNNING

    # When inactivity exceeds stall_timeout, transitions to STALLED
    time.sleep(0.35)
    state = watchdog.evaluate_tick()
    assert state == WatchdogState.STALLED
    assert watchdog.diagnostic_reason == "WATCHDOG_HANG_TERMINATED"


def test_watchdog_detects_filesystem_mutations(tmp_path: Path):
    watchdog = ProgressWatchdog(
        worktree_path=tmp_path,
        inactivity_threshold_seconds=0.1,
        stall_timeout_seconds=0.3,
        check_interval_seconds=0.05,
    )
    time.sleep(0.12)
    assert watchdog.evaluate_tick() == WatchdogState.SUSPECTED_STALL

    # Writing a file into the worktree triggers filesystem activity detection
    test_file = tmp_path / "mutation.py"
    test_file.write_text("x = 1\n", encoding="utf-8")
    assert watchdog.check_filesystem_activity() is True
    assert watchdog.state == WatchdogState.RUNNING


def test_loop_and_stagnation_detection():
    # Streak of 3 identical blocker fingerprints detects loop
    fps = ["fp_err_1", "fp_err_1", "fp_err_1"]
    assert detect_repetitive_loop(fps, max_identical_streak=3) is True

    # Streak of 2 does not trigger threshold of 3
    assert detect_repetitive_loop(["fp_err_1", "fp_err_1"], max_identical_streak=3) is False

    # Changing fingerprint breaks streak
    assert detect_repetitive_loop(["fp_err_1", "fp_err_1", "fp_err_2"], max_identical_streak=3) is False

    # Zero diff stagnation
    assert detect_zero_diff_stagnation(["", ""], max_zero_diff_streak=2) is True
    assert detect_zero_diff_stagnation(["diff1", ""], max_zero_diff_streak=2) is False


@pytest.mark.asyncio
async def test_watchdog_protects_active_long_running_subprocess(tmp_path: Path):
    # A subprocess that runs for a while but continuously emits stdout
    watchdog = ProgressWatchdog(
        worktree_path=tmp_path,
        inactivity_threshold_seconds=0.2,
        stall_timeout_seconds=0.5,
        check_interval_seconds=0.05,
    )
    proc = await asyncio.create_subprocess_exec(
        "python3",
        "-c",
        "import time, sys\nfor i in range(4):\n    sys.stdout.write(f'{i}\\n')\n    sys.stdout.flush()\n    time.sleep(0.1)\n",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    chunks = []
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        chunks.append(line)
        watchdog.record_activity(WatchdogSignal.STDOUT_EMISSION)
        state = watchdog.evaluate_tick(proc.pid)
        assert state in {WatchdogState.RUNNING, WatchdogState.SUSPECTED_STALL}

    await proc.wait()
    assert proc.returncode == 0
    assert len(chunks) == 4
    # The process was never marked STALLED because it produced active progress
    assert watchdog.state == WatchdogState.RUNNING
