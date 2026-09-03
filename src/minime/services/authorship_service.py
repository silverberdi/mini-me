"""Authorship service and mixed-authorship tracking for mini me.

Implements Mandatory Rule G: Reviewer Independence Technical Enforcement.
Builds durable material-authorship provenance for each candidate and strictly excludes
material authors from complementary review eligibility.
"""

from __future__ import annotations

import logging
from typing import Any

from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import CandidateAuthorship, MaterialAuthorshipSummary, utc_now

logger = logging.getLogger(__name__)


class AuthorshipService:
    """Tracks multi-attempt code authorship and strictly enforces reviewer independence."""

    def record_attempt_authorship(
        self,
        job_id: str,
        agent_role: str,
        model_identity: str,
        attempt_number: int,
        files_touched: list[str],
        uow: PersistenceUnitOfWork,
    ) -> CandidateAuthorship:
        """Record an attempt's contribution and update mixed-authorship status."""
        authorship = CandidateAuthorship(
            job_id=job_id,
            agent_role=agent_role,
            model_identity=model_identity,
            attempt_number=attempt_number,
            files_touched=files_touched,
            is_primary_author=(attempt_number == 1),
        )
        uow.candidate_authorships.save(authorship)

        # Evaluate if job now has mixed authorship
        all_authorships = uow.candidate_authorships.list_by_job(job_id)
        distinct_models = {a.model_identity for a in all_authorships}
        distinct_roles = {a.agent_role for a in all_authorships}

        is_mixed = len(distinct_models) > 1 or len(distinct_roles) > 1

        job = uow.jobs.get_by_id(job_id)
        if job and job.is_mixed_authorship != is_mixed:
            job.is_mixed_authorship = is_mixed
            uow.jobs.save(job)

        return authorship

    def get_authorship_summary(
        self,
        job_id: str,
        uow: PersistenceUnitOfWork,
    ) -> dict[str, Any]:
        """Compile a summary of authors and touched files for the candidate."""
        authorships = uow.candidate_authorships.list_by_job(job_id)
        distinct_models = sorted({a.model_identity for a in authorships})
        distinct_roles = sorted({a.agent_role for a in authorships})
        is_mixed = len(distinct_models) > 1 or len(distinct_roles) > 1

        all_files: set[str] = set()
        for a in authorships:
            all_files.update(a.files_touched)

        return {
            "job_id": job_id,
            "is_mixed_authorship": is_mixed,
            "author_count": len(authorships),
            "distinct_models": distinct_models,
            "distinct_roles": distinct_roles,
            "total_files_touched": len(all_files),
            "authorships": [a.model_dump(mode="json") for a in authorships],
        }

    def get_material_candidate_authors(
        self,
        job_id: str,
        uow: PersistenceUnitOfWork,
    ) -> set[str]:
        """Return the set of all provider/agent roles that authored candidate code."""
        authorships = uow.candidate_authorships.list_by_job(job_id)
        material_authors: set[str] = set()
        for a in authorships:
            if a.files_touched and len(a.files_touched) > 0:
                if a.agent_role:
                    material_authors.add(a.agent_role.strip().lower())
                if a.model_identity:
                    material_authors.add(a.model_identity.strip().lower())

        if not material_authors:
            job = uow.jobs.get_by_id(job_id)
            if job and job.current_executor:
                material_authors.add(job.current_executor.strip().lower())
            elif job and job.implementer_role:
                material_authors.add(job.implementer_role.strip().lower())

        return material_authors

    def evaluate_reviewer_independence(
        self,
        job_id: str,
        configured_reviewers: list[str],
        uow: PersistenceUnitOfWork,
        candidate_sha: str = "",
        generation: int = 1,
    ) -> MaterialAuthorshipSummary:
        """Evaluate reviewer independence and determine eligible vs disqualified reviewers."""
        material_authors = self.get_material_candidate_authors(job_id, uow)

        eligible: list[str] = []
        disqualified: list[str] = []

        for rev in configured_reviewers:
            rev_norm = rev.strip().lower()
            if rev_norm in material_authors:
                disqualified.append(rev)
            else:
                eligible.append(rev)

        is_independent = len(eligible) > 0

        return MaterialAuthorshipSummary(
            candidate_sha=candidate_sha,
            generation=generation,
            material_authors=sorted(material_authors),
            configured_reviewers=configured_reviewers,
            eligible_reviewers=eligible,
            disqualified_reviewers=disqualified,
            is_independent=is_independent,
            evaluated_at=utc_now(),
        )

    def is_reviewer_eligible(
        self,
        job_id: str,
        reviewer_role: str,
        uow: PersistenceUnitOfWork,
    ) -> tuple[bool, str | None]:
        """Strictly validate whether the assigned reviewer is independent from candidate authorship."""
        material_authors = self.get_material_candidate_authors(job_id, uow)
        rev_norm = reviewer_role.strip().lower()

        if rev_norm in material_authors:
            return (
                False,
                f"Reviewer '{reviewer_role}' has material authorship in candidate for job '{job_id}' "
                f"and is strictly disqualified under reviewer independence policy.",
            )

        return True, None

    def evaluate_reviewer_authorship(
        self,
        job_id: str,
        reviewer_role: str,
        surviving_files: list[str] | set[str],
        candidate_sha: str,
        candidate_generation: int | None,
        uow: PersistenceUnitOfWork,
    ) -> dict[str, Any]:
        """Evaluate contribution files proven to survive the frozen candidate."""
        surviving = {str(path).strip().lstrip("./") for path in surviving_files}
        contributions = []
        for record in uow.candidate_authorships.list_by_job(job_id):
            files = sorted(
                surviving.intersection(
                    {str(path).strip().lstrip("./") for path in record.files_touched}
                )
            )
            if record.agent_role.lower() == reviewer_role.lower() and files:
                contributions.append(
                    {
                        "attempt_number": record.attempt_number,
                        "agent_role": record.agent_role,
                        "model_identity": record.model_identity,
                        "files": files,
                    }
                )
        return {
            "candidate_sha": candidate_sha,
            "candidate_generation": candidate_generation,
            "reviewer_role": reviewer_role,
            "surviving_contributions": contributions,
            "is_mixed_authorship": bool(contributions),
        }
