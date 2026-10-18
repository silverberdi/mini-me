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
    PROCESS_NETWORK_ACTIVITY = "PROCESS_NETWORK_ACTIVITY"


def _parse_cputime_seconds(raw: str) -> float:
    """Parse ps cputime format [[days-]hh:]mm:ss[.ss] into total seconds."""
    try:
        raw = raw.strip()
        days = 0.0
        if "-" in raw:
            d_part, raw = raw.split("-", 1)
            days = float(d_part)
        parts = raw.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return days * 86400.0 + float(h) * 3600.0 + float(m) * 60.0 + float(s)
        if len(parts) == 2:
            m, s = parts
            return days * 86400.0 + float(m) * 60.0 + float(s)
        if len(parts) == 1:
            return days * 86400.0 + float(parts[0])
    except Exception:
        pass
    return 0.0


class ProgressWatchdog:
    """Intelligent multi-signal activity and progress monitor."""

    def __init__(
        self,
        worktree_path: Path | str,
        *,
        inactivity_threshold_seconds: float | None = None,
        stall_timeout_seconds: float | None = None,
        check_interval_seconds: float | None = None,
        min_deadlock_confirmation_probes: int | None = None,
    ):
        self.worktree_path = Path(worktree_path)
        # Allow env override for fast deterministic unit tests
        env_inactivity = os.getenv("MINIME_WATCHDOG_INACTIVITY_SECONDS")
        env_stall = os.getenv("MINIME_WATCHDOG_STALL_SECONDS")
        env_interval = os.getenv("MINIME_WATCHDOG_INTERVAL_SECONDS")
        env_probes = os.getenv("MINIME_WATCHDOG_DEADLOCK_PROBES")

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
        self.min_deadlock_confirmation_probes = (
            int(env_probes)
            if env_probes is not None
            else (min_deadlock_confirmation_probes if min_deadlock_confirmation_probes is not None else 3)
        )

        self.state: WatchdogState = WatchdogState.RUNNING
        self.last_activity_at: float = time.monotonic()
        self.signals_recorded: list[dict[str, Any]] = []
        self._last_worktree_mtime: float = self._get_max_worktree_mtime()
        self.diagnostic_reason: str | None = None
        self._deadlock_confirmation_count: int = 0
        self._last_process_cputimes: dict[int, float] = {}
        self._explicit_positive_deadlock: bool = False
        self._explicit_deadlock_reason: str | None = None

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
        self._deadlock_confirmation_count = 0
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

    def get_process_tree_pids(self, pid: int) -> set[int]:
        """Discover the root PID and all recursively spawned descendant PIDs."""
        pids = {pid}
        to_explore = [pid]
        while to_explore:
            curr = to_explore.pop()
            try:
                proc = subprocess.run(
                    ["pgrep", "-P", str(curr)],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    for line in proc.stdout.strip().split():
                        try:
                            child = int(line)
                            if child not in pids:
                                pids.add(child)
                                to_explore.append(child)
                        except ValueError:
                            pass
            except Exception:
                pass
        return pids

    def check_process_tree_activity(self, pid: int) -> bool:
        """Inspect root PID and all children for CPU usage, thread states, CPU time advances, and open sockets."""
        tree = self.get_process_tree_pids(pid)
        any_alive = False
        activity_detected = False

        for p in tree:
            try:
                os.kill(p, 0)
                any_alive = True
            except OSError:
                continue

            try:
                proc = subprocess.run(
                    ["ps", "-p", str(p), "-o", "stat=,cputime="],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    parts = proc.stdout.strip().split()
                    if parts:
                        try:
                            stat = parts[0]
                            cputime_str = parts[1] if len(parts) > 1 else ""

                            # 1. Executing thread state (R=running on CPU, D=disk wait)
                            if "R" in stat or "D" in stat:
                                activity_detected = True

                            # 2. Cumulative CPU time advance
                            if cputime_str:
                                cur_secs = _parse_cputime_seconds(cputime_str)
                                prev_secs = self._last_process_cputimes.get(p)
                                self._last_process_cputimes[p] = cur_secs
                                if prev_secs is not None and cur_secs > prev_secs:
                                    activity_detected = True
                        except (ValueError, IndexError):
                            pass
            except Exception:
                pass

            # 3. Check for active network sockets (e.g. streaming LLM completions or HTTP requests)
            try:
                sock_proc = subprocess.run(
                    ["lsof", "-n", "-P", "-i", "-a", "-p", str(p)],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                )
                if sock_proc.returncode == 0 and sock_proc.stdout.strip():
                    activity_detected = True
            except Exception:
                pass

            if activity_detected:
                break

        if not any_alive:
            return False

        return activity_detected

    def check_process_cpu_activity(self, pid: int) -> bool:
        """Backward-compatible process polling checking whether process tree has consumed compute."""
        return self.check_process_tree_activity(pid)

    def mark_positive_deadlock(self, reason: str) -> None:
        """Explicitly record an authorized irrecoverable deadlock condition."""
        self._explicit_positive_deadlock = True
        self._explicit_deadlock_reason = reason

    def detect_positive_deadlock(self, pid: int) -> tuple[bool, str]:
        """Detect positive, verifiable evidence of irrecoverable deadlock.

        Absence of activity, CPU consumption, or open sockets is negative evidence
        (uncertainty) and is never treated as a deadlock. Legitimate inference calls
        or IO waits may be silent without consuming CPU.

        Positive deadlock evidence requires verifiable proof such as:
        - Zombie / defunct child processes in the tree that cannot make progress (state 'Z')
        - Persistent uninterruptible kernel disk sleep across the entire tree (state 'D')
        - An explicitly marked irrecoverable deadlock condition or cyclic stagnation.
        """
        if self._explicit_positive_deadlock:
            return True, self._explicit_deadlock_reason or "explicitly authorized deadlock condition"

        tree = self.get_process_tree_pids(pid)
        if not tree:
            return False, "no process tree"

        any_alive = False
        zombie_count = 0
        uninterruptible_count = 0
        total_procs = 0

        for p in tree:
            try:
                os.kill(p, 0)
                any_alive = True
            except OSError:
                continue

            total_procs += 1
            try:
                proc = subprocess.run(
                    ["ps", "-p", str(p), "-o", "stat="],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    stat = proc.stdout.strip()
                    if "Z" in stat:
                        zombie_count += 1
                    elif "D" in stat:
                        uninterruptible_count += 1
            except Exception:
                pass

        if not any_alive:
            return False, "process already terminated"

        if zombie_count > 0:
            return True, f"zombie/defunct process detected in tree (count={zombie_count})"

        if total_procs > 0 and uninterruptible_count == total_procs:
            return True, f"entire process tree stuck in uninterruptible sleep (count={uninterruptible_count})"

        return False, "process tree alive in normal wait state; absence of activity is not deadlock"

    def evaluate_tick(self, pid: int | None = None) -> WatchdogState:
        """Evaluate state machine progression: RUNNING -> SUSPECTED_STALL -> STALLED.

        Silence and duration alone are never sufficient to transition to STALLED or
        terminate an attached living process. Absence of activity (CPU, IO, sockets)
        is negative evidence and reflects uncertainty (e.g. an inference model awaiting
        upstream response or an IO wait).

        Under uncertainty, the watchdog maintains diagnostic records of the stall,
        preserves the process and durable state without sending SIGTERM/SIGKILL, and
        only authorizes STALLED when positive, verifiable evidence of an irrecoverable
        deadlock is confirmed.
        """
        self.check_filesystem_activity()
        inactivity = time.monotonic() - self.last_activity_at

        if pid is not None and self.check_process_tree_activity(pid):
            self.record_activity(
                WatchdogSignal.PROCESS_CPU_ACTIVITY, f"PID {pid} process tree active"
            )
            return self.state

        if inactivity < self.inactivity_threshold_seconds:
            self._deadlock_confirmation_count = 0
            self.state = WatchdogState.RUNNING
            return self.state

        if inactivity < self.stall_timeout_seconds:
            self._deadlock_confirmation_count = 0
            self.state = WatchdogState.SUSPECTED_STALL
            return self.state

        # Inactivity has reached or exceeded stall_timeout_seconds
        if pid is not None:
            # Check for positive, verifiable evidence of an irrecoverable deadlock
            is_deadlock, deadlock_reason = self.detect_positive_deadlock(pid)
            if is_deadlock:
                self.state = WatchdogState.STALLED
                self.diagnostic_reason = f"POSITIVE_DEADLOCK_CONFIRMED: {deadlock_reason}"
                return self.state

            # Under uncertainty (process alive but silent without CPU consumption),
            # preserve process and durable state without authorizing termination.
            self.state = WatchdogState.SUSPECTED_STALL
            self.diagnostic_reason = (
                f"INACTIVITY_STALL_DIAGNOSED: PID {pid} silent for {inactivity:.1f}s "
                f"without observable compute/IO; preserving process under uncertainty"
            )
            return self.state

        # When no PID is attached, inactivity exceeding stall timeout declares STALLED
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
