"""Standalone adversarial B03 verification script for Ubuntu 24.04 with Bubblewrap, two Linux UIDs, and disposable PostgreSQL."""

import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path


def log(msg: str):
    print(f"[B03-UBUNTU] {msg}", flush=True)


def run_as_user(
    user: str, cmd: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    u = pwd.getpwnam(user)

    def demote():
        os.setgid(u.pw_gid)
        os.setuid(u.pw_uid)
        os.environ["HOME"] = u.pw_dir
        os.environ["USER"] = user

    return subprocess.run(
        cmd, preexec_fn=demote, env=env, capture_output=True, text=True, check=False
    )


def main():
    log("=== Starting B03 Isolated Ubuntu Acceptance Proof ===")
    uname = subprocess.check_output(["uname", "-a"], text=True).strip()
    log(f"Host OS: {uname}")

    # 1. Verify two Linux user identities exist
    minime_pw = pwd.getpwnam("minime")
    other_pw = pwd.getpwnam("otheruser")
    log(f"User 1: minime (UID {minime_pw.pw_uid}, GID {minime_pw.pw_gid}, HOME {minime_pw.pw_dir})")
    log(f"User 2: otheruser (UID {other_pw.pw_uid}, GID {other_pw.pw_gid}, HOME {other_pw.pw_dir})")
    assert minime_pw.pw_uid != other_pw.pw_uid, "UIDs must be distinct!"

    # 2. Verify Bubblewrap is installed and executable
    bwrap_ver = subprocess.check_output(["bwrap", "--version"], text=True).strip()
    log(f"Bubblewrap version: {bwrap_ver}")

    # Import minime confinement services
    sys.path.insert(0, "/workspace")
    sys.path.insert(0, "/workspace/src")

    job_id = "job-b03-acceptance-test"

    # 3. Test Primary Cache Confinement & Cross-User Boundary (0700)
    minime_home = Path(minime_pw.pw_dir)
    primary_cache = minime_home / ".cache" / "minime" / "pycache" / job_id
    log(f"Preparing primary cache as minime: {primary_cache}")

    # Run safe_prepare_cache_dir as minime
    code_prep = f"""
import sys; sys.path.insert(0, '/workspace'); sys.path.insert(0, '/workspace/src')
from minime.services.agent_confinement import safe_prepare_cache_dir
from pathlib import Path
p = safe_prepare_cache_dir(Path('{primary_cache}'), expected_uid={minime_pw.pw_uid}, job_id='{job_id}')
print(f'PREPARED:{{p}}')
"""
    res = run_as_user("minime", ["python3", "-c", code_prep])
    assert res.returncode == 0, f"safe_prepare_cache_dir failed: {res.stderr}"
    log(f"safe_prepare_cache_dir created successfully: {res.stdout.strip()}")

    # Check mode is strictly 0700
    st = os.stat(primary_cache)
    assert st.st_uid == minime_pw.pw_uid
    assert stat.S_IMODE(st.st_mode) == 0o700, (
        f"Mode must be 0700, got {oct(stat.S_IMODE(st.st_mode))}"
    )
    log(
        f"Primary cache permissions verified: {oct(stat.S_IMODE(st.st_mode))} owned by UID {st.st_uid}"
    )

    # 4. Adversarial Attack 1: User 'otheruser' attempts to read or write into minime's cache
    log("Adversarial Test: 'otheruser' attempting to write inside minime's private cache...")
    code_tamper = f"""
try:
    with open('{primary_cache}/exploit.txt', 'w') as f:
        f.write('tampered')
    print('TAMPER_SUCCESS')
except PermissionError as e:
    print(f'TAMPER_REJECTED: {{e}}')
"""
    res_tamper = run_as_user("otheruser", ["python3", "-c", code_tamper])
    assert "TAMPER_REJECTED" in res_tamper.stdout, (
        f"Cross-user isolation failed! Output: {res_tamper.stdout}"
    )
    assert not (primary_cache / "exploit.txt").exists(), "Exploit file was created!"
    log(f"Cross-user tamper blocked by Linux kernel DAC: {res_tamper.stdout.strip()}")

    # 5. Adversarial Attack 2: User 'otheruser' plants a symlink in /tmp to hijack cache
    log("Adversarial Test: Symlink hijack in /tmp...")
    spoof_target = Path("/tmp") / f"minime_cache_{minime_pw.pw_uid}_{job_id}"
    real_target = Path("/tmp") / f"otheruser_target_{job_id}"
    real_target.mkdir(mode=0o700, exist_ok=True)
    os.chown(real_target, other_pw.pw_uid, other_pw.pw_gid)
    if spoof_target.is_symlink() or spoof_target.exists():
        spoof_target.unlink()
    spoof_target.symlink_to(real_target)

    # Validate that minime strictly rejects this symlink
    code_sym_test = f"""
import sys; sys.path.insert(0, '/workspace'); sys.path.insert(0, '/workspace/src')
from minime.services.agent_confinement import safe_prepare_cache_dir
from pathlib import Path
try:
    safe_prepare_cache_dir(Path('{spoof_target}'), expected_uid={minime_pw.pw_uid}, job_id='{job_id}')
    print('SYMLINK_ACCEPTED_ERROR')
except PermissionError as e:
    print(f'SYMLINK_REJECTED_SUCCESS: {{e}}')
"""
    res_sym = run_as_user("minime", ["python3", "-c", code_sym_test])
    assert "SYMLINK_REJECTED_SUCCESS" in res_sym.stdout, (
        f"Symlink was not rejected! {res_sym.stdout} {res_sym.stderr}"
    )
    log(f"Symlink hijack blocked: {res_sym.stdout.strip()}")
    spoof_target.unlink()
    import shutil

    shutil.rmtree(real_target, ignore_errors=True)

    # 6. Real Bubblewrap Confinement Execution under 'minime'
    log("Executing real Bubblewrap confinement test under 'minime'...")
    wt_dir = Path("/tmp/bwrap_test_worktree")
    wt_dir.mkdir(parents=True, mode=0o755, exist_ok=True)
    os.chown(wt_dir, minime_pw.pw_uid, minime_pw.pw_gid)

    # Initialize a test python module in the worktree
    (wt_dir / "calc.py").write_text("def add(a, b): return a + b\n")
    (wt_dir / "test_calc.py").write_text(
        "import calc\nassert calc.add(2, 3) == 5\nprint('PYTEST_BWRAP_PASSED')\n"
    )
    os.chown(wt_dir / "calc.py", minime_pw.pw_uid, minime_pw.pw_gid)
    os.chown(wt_dir / "test_calc.py", minime_pw.pw_uid, minime_pw.pw_gid)

    # Run Bubblewrap wrapping python execution
    code_bwrap = f"""
import os, sys, subprocess
sys.path.insert(0, '/workspace')
sys.path.insert(0, '/workspace/src')
from minime.services.agent_confinement import AgentProcessConfinement
from pathlib import Path

confinement = AgentProcessConfinement(
    allowed_worktree_path='{wt_dir}',
    runtime_root='/tmp/runtime_root',
    require_kernel_confinement=True,
)
cache_dir = Path('{primary_cache}')
wrapped_cmd = confinement.wrap_command(
    ['python3', 'test_calc.py'],
    secure_cache_path=cache_dir,
    job_id='{job_id}',
)
print('WRAPPED_CMD:', ' '.join(wrapped_cmd))

# Execute wrapped command with PYTHONPYCACHEPREFIX set to private cache
env = os.environ.copy()
env['PYTHONPYCACHEPREFIX'] = str(cache_dir)
res = subprocess.run(wrapped_cmd, cwd='{wt_dir}', env=env, capture_output=True, text=True)
print('BWRAP_RETURNCODE:', res.returncode)
print('BWRAP_STDOUT:', res.stdout.strip())
print('BWRAP_STDERR:', res.stderr.strip())
assert res.returncode == 0
assert 'PYTEST_BWRAP_PASSED' in res.stdout
"""
    # Create runtime root
    rr = Path("/tmp/runtime_root")
    rr.mkdir(parents=True, mode=0o755, exist_ok=True)
    os.chown(rr, minime_pw.pw_uid, minime_pw.pw_gid)

    res_bwrap = run_as_user("minime", ["python3", "-c", code_bwrap])
    assert res_bwrap.returncode == 0, (
        f"Bubblewrap test failed! {res_bwrap.stdout}\n{res_bwrap.stderr}"
    )
    log(f"Bubblewrap execution succeeded under unprivileged UID {minime_pw.pw_uid}!")
    for line in res_bwrap.stdout.strip().splitlines():
        log(f"  {line}")

    # 7. Verify Bytecode Isolation:
    # Verify that .pyc was written to primary_cache and NOT to worktree
    pyc_in_worktree = list(wt_dir.glob("**/__pycache__"))
    assert len(pyc_in_worktree) == 0, f"Bytecode leaked into worktree: {pyc_in_worktree}"
    log("Worktree purity verified: zero __pycache__ directories created in worktree.")

    pyc_in_cache = list(primary_cache.glob("**/*.pyc"))
    assert len(pyc_in_cache) > 0, "Bytecode was NOT written to private cache directory!"
    log(
        f"Bytecode confinement verified: {len(pyc_in_cache)} .pyc files compiled strictly into private cache: {pyc_in_cache[0].name}"
    )

    # 8. Test RO root filesystem inside Bubblewrap:
    # Attempting to write to /usr or /tmp/other from inside bwrap MUST fail
    code_ro_test = f"""
import os, sys, subprocess
sys.path.insert(0, '/workspace')
sys.path.insert(0, '/workspace/src')
from minime.services.agent_confinement import AgentProcessConfinement
from pathlib import Path

confinement = AgentProcessConfinement(
    allowed_worktree_path='{wt_dir}',
    runtime_root='/tmp/runtime_root',
    require_kernel_confinement=True,
)
wrapped_cmd = confinement.wrap_command(
    ['python3', '-c', "import os; open('/etc/evil.txt', 'w').write('bad')"],
    secure_cache_path=Path('{primary_cache}'),
    job_id='{job_id}',
)
res = subprocess.run(wrapped_cmd, cwd='{wt_dir}', capture_output=True, text=True)
print('RO_RETURNCODE:', res.returncode)
print('RO_STDERR:', res.stderr.strip())
assert res.returncode != 0
assert 'Read-only file system' in res.stderr
"""
    res_ro = run_as_user("minime", ["python3", "-c", code_ro_test])
    assert res_ro.returncode == 0, f"RO test failed: {res_ro.stdout}\n{res_ro.stderr}"
    log(
        "Read-only root enforcement verified inside Bubblewrap: writing to /etc blocked with 'Read-only file system'."
    )

    # 9. Test Disposable PostgreSQL Lifecycle (Fail-Closed, G1 Requirement)
    log(
        "[NOTICE] Container environment with --cap-add=SYS_ADMIN --security-opt apparmor=unconfined provides isolated Linux/DAC validation, not production host parity."
    )

    admin_db_url = os.environ.get(
        "MINIME_TEST_ADMIN_DATABASE_URL",
        "postgresql+psycopg://silveriobernal@host.docker.internal:54333/postgres",
    )

    import uuid

    from sqlalchemy import create_engine, make_url, text
    from sqlalchemy.pool import NullPool

    from minime.db.models import Base
    from minime.db.repository import PostgresPersistenceUnitOfWork
    from minime.db.session import EXPECTED_ALEMBIC_HEAD
    from minime.domain.enums import (
        JobStatus,
    )
    from minime.domain.models import Job, Project

    # Mask credentials for display
    def mask_url(u_str: str) -> str:
        try:
            u = make_url(u_str)
            return str(u.set(password="***" if u.password else None))
        except Exception:
            return "<masked-url>"

    log(f"Validating administrative PostgreSQL server URL: {mask_url(admin_db_url)}")
    admin_parsed = make_url(admin_db_url)
    if admin_parsed.host not in {"host.docker.internal", "localhost", "127.0.0.1", "::1", None}:
        raise ValueError(f"Refusing non-local/non-host-gateway DB host: {admin_parsed.host}")

    admin_engine = create_engine(
        admin_parsed.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )

    # Generate dedicated disposable test database name
    disposable_db_name = f"minime_test_b03_{uuid.uuid4().hex[:12]}"
    disposable_db_url = str(admin_parsed.set(database=disposable_db_name))
    log(f"Creating dedicated disposable test database: {disposable_db_name}")

    with admin_engine.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{disposable_db_name}"')

    disposable_engine = create_engine(disposable_db_url, poolclass=NullPool)
    try:
        log("Initializing database schema via Base.metadata.create_all...")
        Base.metadata.create_all(disposable_engine)

        with disposable_engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) PRIMARY KEY);"
                )
            )
            conn.execute(
                text(
                    f"INSERT INTO alembic_version (version_num) VALUES ('{EXPECTED_ALEMBIC_HEAD}');"
                )
            )
            conn.commit()

        # Execute transactional readback test using PostgresPersistenceUnitOfWork
        log("Executing transactional state verification with PostgresPersistenceUnitOfWork...")
        from sqlalchemy.orm import sessionmaker

        b03_session_factory = sessionmaker(
            bind=disposable_engine, autoflush=False, expire_on_commit=False
        )

        session1 = b03_session_factory()
        uow1 = PostgresPersistenceUnitOfWork(session1)
        p = Project(
            project_id="b03-proj",
            display_name="B03 Verification Project",
            repository="/workspace",
            base_branch="main",
        )
        uow1.projects.save(p)
        j = Job(
            job_id=job_id,
            project_id="b03-proj",
            change_name="b03-change",
            base_sha="0000000000000000000000000000000000000000",
            candidate_sha="1111111111111111111111111111111111111111",
            status=JobStatus.CHECKS_RUNNING,
            current_generation=1,
            implementer_role="codex",
            current_executor="codex",
        )
        uow1.jobs.save(j)
        uow1.commit()
        session1.close()

        # Read back from fresh independent session
        session2 = b03_session_factory()
        uow2 = PostgresPersistenceUnitOfWork(session2)
        persisted_j = uow2.jobs.get_by_id(job_id)
        assert persisted_j is not None, (
            "Failed to read back persisted job from disposable PostgreSQL!"
        )
        assert persisted_j.candidate_sha == "1111111111111111111111111111111111111111"
        assert persisted_j.status == JobStatus.CHECKS_RUNNING
        session2.close()
        log("Disposable PostgreSQL transactional readback verified successfully.")

    finally:
        disposable_engine.dispose()
        log(f"Dropping disposable test database: {disposable_db_name}")
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": disposable_db_name},
            )
            conn.exec_driver_sql(f'DROP DATABASE "{disposable_db_name}"')
        admin_engine.dispose()

    # Cleanup test worktree
    import shutil

    shutil.rmtree(wt_dir, ignore_errors=True)
    shutil.rmtree(primary_cache, ignore_errors=True)

    log("=== B03 ISOLATED UBUNTU ACCEPTANCE PROOF COMPLETE: ALL INVARIANTS VERIFIED ===")


if __name__ == "__main__":
    main()
