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


def test_watchdog_silence_alone_does_not_stall_when_process_actively_computing(tmp_path: Path):
    watchdog = ProgressWatchdog(
        worktree_path=tmp_path,
        inactivity_threshold_seconds=0.1,
        stall_timeout_seconds=0.2,
        check_interval_seconds=0.05,
        min_deadlock_confirmation_probes=3,
    )
    # Process tree activity is positive (e.g. streaming LLM socket or active CPU compute)
    watchdog.check_process_tree_activity = lambda pid: True

    # Sleep longer than stall_timeout_seconds
    time.sleep(0.25)

    # Inactivity in stdout/stderr > stall_timeout, but active compute prevents STALLED
    state = watchdog.evaluate_tick(pid=12345)
    assert state == WatchdogState.RUNNING
    assert watchdog.state == WatchdogState.RUNNING
    assert watchdog._deadlock_confirmation_count == 0


@pytest.mark.asyncio
async def test_watchdog_preserves_alive_silent_zero_cpu_process_without_termination(tmp_path: Path):
    """Verify that a living process with zero stdout/stderr and zero CPU is preserved under uncertainty."""
    watchdog = ProgressWatchdog(
        worktree_path=tmp_path,
        inactivity_threshold_seconds=0.05,
        stall_timeout_seconds=0.1,
        check_interval_seconds=0.02,
    )
    # Start a real process that sleeps silently without CPU consumption or IO
    proc = await asyncio.create_subprocess_exec(
        "python3",
        "-c",
        "import time\ntime.sleep(2.0)\n",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        # Sleep beyond the stall timeout
        await asyncio.sleep(0.15)

        # Evaluate watchdog across multiple consecutive ticks
        for _ in range(5):
            state = watchdog.evaluate_tick(proc.pid)
            # Must remain in SUSPECTED_STALL, NOT transition to STALLED
            assert state == WatchdogState.SUSPECTED_STALL
            # Inactivity diagnostic must be recorded
            assert watchdog.diagnostic_reason is not None
            assert "INACTIVITY_STALL_DIAGNOSED" in watchdog.diagnostic_reason
            # The process must NOT have been terminated
            assert proc.returncode is None

        # Process is alive and intact throughout
        assert proc.returncode is None
    finally:
        try:
            proc.terminate()
            await proc.wait()
        except OSError:
            pass


def test_watchdog_terminates_only_on_positive_verifiable_deadlock(tmp_path: Path):
    """Verify that STALLED is authorized only upon positive verifiable deadlock evidence."""
    watchdog = ProgressWatchdog(
        worktree_path=tmp_path,
        inactivity_threshold_seconds=0.05,
        stall_timeout_seconds=0.1,
        check_interval_seconds=0.02,
    )
    time.sleep(0.12)

    # Alive process without positive deadlock is NOT marked STALLED under silence
    watchdog.detect_positive_deadlock = lambda pid: (False, "normal sleep")
    state = watchdog.evaluate_tick(pid=12345)
    assert state == WatchdogState.SUSPECTED_STALL
    assert "INACTIVITY_STALL_DIAGNOSED" in (watchdog.diagnostic_reason or "")

    # When positive deadlock evidence is verified (e.g. defunct/zombie in tree)
    watchdog.detect_positive_deadlock = lambda pid: (True, "zombie/defunct process detected in tree (count=1)")
    state_deadlock = watchdog.evaluate_tick(pid=12345)
    assert state_deadlock == WatchdogState.STALLED
    assert "POSITIVE_DEADLOCK_CONFIRMED" in (watchdog.diagnostic_reason or "")


