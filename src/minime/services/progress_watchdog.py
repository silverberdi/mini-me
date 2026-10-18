"""Multi-signal intelligent progress, activity, and loop watchdog."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WatchdogState(str, Enum):
    RUNNING = "RUNNING"
    SUSPECTED_STALL = "SUSPECTED_STALL"
    STALLED = "STALLED"
    RECOVERY = "RECOVERY"


class WatchdogSignal(str, Enum):
    STDOUT_EMISSION = "STDOUT_EMISSION"
    STDERR_EMISSION = "STDERR_EMISSION"
    FILESYSTEM_MUTATION = "FILESYSTEM_MUTATION"
    TOOL_CALL = "TOOL_CALL"
    PROCESS_CPU_ACTIVITY = "PROCESS_CPU_ACTIVITY"


class ProgressWatchdog:
    """Intelligent multi-signal activity and progress monitor."""

    def __init__(
        self,
        worktree_path: Path | str,
        *,
        inactivity_threshold_seconds: float | None = None,
        stall_timeout_seconds: float | None = None,
        check_interval_seconds: float | None = None,
    ):
        self.worktree_path = Path(worktree_path)
        # Allow env override for fast deterministic unit tests
        env_inactivity = os.getenv("MINIME_WATCHDOG_INACTIVITY_SECONDS")
        env_stall = os.getenv("MINIME_WATCHDOG_STALL_SECONDS")
        env_interval = os.getenv("MINIME_WATCHDOG_INTERVAL_SECONDS")

        self.inactivity_threshold_seconds = (
            float(env_inactivity)
            if env_inactivity is not None
            else (inactivity_threshold_seconds if inactivity_threshold_seconds is not None else 180.0)
        )
        self.stall_timeout_seconds = (
            float(env_stall)
            if env_stall is not None
            else (stall_timeout_seconds if stall_timeout_seconds is not None else 300.0)
        )
        self.check_interval_seconds = (
            float(env_interval)
            if env_interval is not None
            else (check_interval_seconds if check_interval_seconds is not None else 1.0)
        )

        self.state: WatchdogState = WatchdogState.RUNNING
        self.last_activity_at: float = time.monotonic()
        self.signals_recorded: list[dict[str, Any]] = []
        self._last_worktree_mtime: float = self._get_max_worktree_mtime()
        self.diagnostic_reason: str | None = None

    def _get_max_worktree_mtime(self) -> float:
        max_mtime = 0.0
        try:
            if not self.worktree_path.exists():
                return 0.0
            for root, dirs, files in os.walk(self.worktree_path):
                # Avoid scanning git internal object stores deeply
                if ".git" in dirs:
                    dirs.remove(".git")
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        m = os.path.getmtime(fp)
                        if m > max_mtime:
                            max_mtime = m
                    except OSError:
                        pass
        except Exception:
            pass
        return max_mtime

    def record_activity(self, sig: WatchdogSignal, details: str = "") -> None:
        self.last_activity_at = time.monotonic()
        self.signals_recorded.append(
            {"signal": sig.value, "timestamp": self.last_activity_at, "details": details}
        )
        if self.state != WatchdogState.RUNNING:
            logger.info(f"ProgressWatchdog recovered to RUNNING on signal {sig.value}")
            self.state = WatchdogState.RUNNING

    def check_filesystem_activity(self) -> bool:
        current_max = self._get_max_worktree_mtime()
        if current_max > self._last_worktree_mtime:
            self._last_worktree_mtime = current_max
            self.record_activity(WatchdogSignal.FILESYSTEM_MUTATION, "file write observed in worktree")
            return True
        return False

    def check_process_cpu_activity(self, pid: int) -> bool:
        """Non-destructive process polling checking whether process has consumed compute."""
        try:
            # Check if process is alive
            os.kill(pid, 0)
        except OSError:
            return False

        try:
            # Use ps to inspect CPU usage or process state
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", "%cpu=,stat="],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                parts = proc.stdout.strip().split()
                if parts:
                    try:
                        cpu = float(parts[0])
                        stat = parts[1] if len(parts) > 1 else ""
                        # If CPU > 0.0 or stat is active (R/D), consider actively computing
                        if cpu > 0.0 or ("R" in stat or "D" in stat):
                            return True
                    except ValueError:
                        pass
        except Exception:
            pass
        return False

    def evaluate_tick(self, pid: int | None = None) -> WatchdogState:
        """Evaluate state machine progression: RUNNING -> SUSPECTED_STALL -> STALLED -> RECOVERY."""
        self.check_filesystem_activity()
        inactivity = time.monotonic() - self.last_activity_at

        if inactivity < self.inactivity_threshold_seconds:
            self.state = WatchdogState.RUNNING
            return self.state

        if inactivity < self.stall_timeout_seconds:
            # Transition to SUSPECTED_STALL and non-destructively probe
            self.state = WatchdogState.SUSPECTED_STALL
            if pid is not None and self.check_process_cpu_activity(pid):
                # Active CPU consumption observed despite silent I/O; keep thread alive
                self.record_activity(
                    WatchdogSignal.PROCESS_CPU_ACTIVITY, f"PID {pid} actively computing"
                )
                self.state = WatchdogState.RUNNING
            return self.state

        # Inactivity exceeded stall timeout with no forward progress
        self.state = WatchdogState.STALLED
        self.diagnostic_reason = "WATCHDOG_HANG_TERMINATED"
        return self.state


def detect_repetitive_loop(
    blocker_fingerprints: list[str], max_identical_streak: int = 3
) -> bool:
    """Detect repetitive blocker loop streak >= 3."""
    if len(blocker_fingerprints) < max_identical_streak:
        return False
    recent = blocker_fingerprints[-max_identical_streak:]
    return len(set(recent)) == 1 and bool(recent[0])


def detect_zero_diff_stagnation(
    diff_records: list[str], max_zero_diff_streak: int = 2
) -> bool:
    """Detect loop where candidate produced zero net diff progress repeatedly."""
    if len(diff_records) < max_zero_diff_streak:
        return False
    recent = diff_records[-max_zero_diff_streak:]
    return all(not str(d).strip() for d in recent)
