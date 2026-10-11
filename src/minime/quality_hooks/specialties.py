"""Dynamic Specialty Selection based on changed files and diff content."""

from __future__ import annotations

import re

from minime.quality_hooks.models import ReviewSpecialty

# Pattern definitions for dynamic specialty assignment
_SECURITY_PATTERNS = [
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"jwt", re.IGNORECASE),
    re.compile(r"crypto", re.IGNORECASE),
    re.compile(r"permission", re.IGNORECASE),
    re.compile(r"github_app", re.IGNORECASE),
    re.compile(r"session", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"bearer", re.IGNORECASE),
    re.compile(r"header", re.IGNORECASE),
]

_DATA_PATTERNS = [
    re.compile(r"alembic", re.IGNORECASE),
    re.compile(r"migrations?", re.IGNORECASE),
    re.compile(r"versions?/", re.IGNORECASE),
    re.compile(r"models?\.py$", re.IGNORECASE),
    re.compile(r"db/", re.IGNORECASE),
    re.compile(r"database", re.IGNORECASE),
    re.compile(r"\.sql$", re.IGNORECASE),
    re.compile(r"repository\.py$", re.IGNORECASE),
]

_RELIABILITY_PATTERNS = [
    re.compile(r"subprocess", re.IGNORECASE),
    re.compile(r"asyncio", re.IGNORECASE),
    re.compile(r"retry", re.IGNORECASE),
    re.compile(r"recovery", re.IGNORECASE),
    re.compile(r"restart", re.IGNORECASE),
    re.compile(r"saga", re.IGNORECASE),
    re.compile(r"concurrency", re.IGNORECASE),
    re.compile(r"savepoint", re.IGNORECASE),
    re.compile(r"timeout", re.IGNORECASE),
    re.compile(r"fail[-_]closed", re.IGNORECASE),
]

_TESTS_PATTERNS = [
    re.compile(r"^tests?/", re.IGNORECASE),
    re.compile(r"/tests?/", re.IGNORECASE),
    re.compile(r"test_[^/]+\.py$", re.IGNORECASE),
    re.compile(r"conftest\.py$", re.IGNORECASE),
    re.compile(r"fixture", re.IGNORECASE),
]

_OPERATIONAL_PATTERNS = [
    re.compile(r"Dockerfile", re.IGNORECASE),
    re.compile(r"docker-compose", re.IGNORECASE),
    re.compile(r"\.service$", re.IGNORECASE),
    re.compile(r"systemd", re.IGNORECASE),
    re.compile(r"deployment", re.IGNORECASE),
    re.compile(r"deploy", re.IGNORECASE),
    re.compile(r"\.env", re.IGNORECASE),
    re.compile(r"\.github/workflows", re.IGNORECASE),
]


def select_specialties_for_files(files: list[str]) -> list[ReviewSpecialty]:
    """Deterministically select required review specialties from changed file paths."""
    selected: set[ReviewSpecialty] = set()

    for f in files:
        f_norm = f.replace("\\", "/")

        # Check security
        if any(p.search(f_norm) for p in _SECURITY_PATTERNS):
            selected.add(ReviewSpecialty.SECURITY_AUTH)

        # Check data
        if any(p.search(f_norm) for p in _DATA_PATTERNS):
            selected.add(ReviewSpecialty.DATA_MIGRATIONS)

        # Check reliability
        if any(p.search(f_norm) for p in _RELIABILITY_PATTERNS):
            selected.add(ReviewSpecialty.RELIABILITY_RECOVERY)

        # Check tests
        if any(p.search(f_norm) for p in _TESTS_PATTERNS):
            selected.add(ReviewSpecialty.TESTS_COVERAGE)

        # Check operational
        if any(p.search(f_norm) for p in _OPERATIONAL_PATTERNS):
            selected.add(ReviewSpecialty.OPERATIONAL_DELIVERY)

    # If no specialized category matched, or as general fallback, require GENERAL_ARCHITECTURE
    if not selected:
        selected.add(ReviewSpecialty.GENERAL_ARCHITECTURE)

    # Return sorted deterministically by enum value
    return sorted(list(selected), key=lambda x: x.value)


def select_specialties_for_diff(diff_text: str, changed_files: list[str] | None = None) -> list[ReviewSpecialty]:
    """Deterministically select required specialties combining file names and diff content."""
    files = list(changed_files or [])

    # Extract filenames from diff headers if not provided
    if not files and diff_text:
        diff_file_matches = re.findall(r"^(?:---|\+\+\+)\s+[ab]/(.+)$", diff_text, flags=re.MULTILINE)
        files = list(set(diff_file_matches))

    specialties = set(select_specialties_for_files(files))

    # Inspect diff text for sensitive security/reliability signals introduced in code
    if re.search(r"\b(?:api_key|token|auth_header|secret|private_key|Bearer|credential)\b", diff_text, re.IGNORECASE):
        specialties.add(ReviewSpecialty.SECURITY_AUTH)

    if re.search(r"\b(?:create_engine|Alembic|alembic_version|execute\(|session\.commit)\b", diff_text):
        specialties.add(ReviewSpecialty.DATA_MIGRATIONS)

    if re.search(r"\b(?:asyncio\.create_subprocess|subprocess\.run|retry|backoff|SagaEngine)\b", diff_text):
        specialties.add(ReviewSpecialty.RELIABILITY_RECOVERY)

    # If any specific specialty matched, remove fallback GENERAL_ARCHITECTURE
    if len(specialties) > 1 and ReviewSpecialty.GENERAL_ARCHITECTURE in specialties:
        specialties.remove(ReviewSpecialty.GENERAL_ARCHITECTURE)

    return sorted(list(specialties), key=lambda x: x.value)
