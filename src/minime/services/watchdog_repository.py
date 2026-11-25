"""Persistence adapter for the small, global Watchdog configuration and records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from minime.db.models import WatchdogDiagnosisModel, WatchdogSettingsModel


class PostgresWatchdogRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_settings(self) -> dict[str, Any]:
        row = self.session.get(WatchdogSettingsModel, "global")
        if row is None:
            return {
                "provider_id": None,
                "harness_id": None,
                "canonical_model_id": None,
                "inactivity_threshold_minutes": 15,
                "mode": "diagnostic_only",
                "updated_at": None,
            }
        return self._settings_payload(row)

    def save_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.session.scalar(
            select(WatchdogSettingsModel)
            .where(WatchdogSettingsModel.settings_id == "global")
            .with_for_update()
        )
        if row is None:
            row = WatchdogSettingsModel(settings_id="global")
            self.session.add(row)
        row.provider_id = values.get("provider_id")
        row.harness_id = values.get("harness_id")
        row.canonical_model_id = values.get("canonical_model_id")
        row.inactivity_threshold_minutes = int(values["inactivity_threshold_minutes"])
        row.mode = str(values["mode"])
        row.updated_at = datetime.now(UTC)
        self.session.flush()
        return self._settings_payload(row)

    def save_diagnosis(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.session.scalar(
            select(WatchdogDiagnosisModel)
            .where(
                WatchdogDiagnosisModel.run_id == values["run_id"],
                WatchdogDiagnosisModel.stage == values["stage"],
                WatchdogDiagnosisModel.candidate_generation == values["candidate_generation"],
            )
            .with_for_update()
        )
        if row is None:
            row = WatchdogDiagnosisModel(
                id=uuid4().hex,
                project_id=values["project_id"],
                run_id=values["run_id"],
                change_name=values["change_name"],
                stage=values["stage"],
                candidate_sha=values.get("candidate_sha"),
                candidate_generation=int(values["candidate_generation"]),
                status=str(values["status"]),
                root_cause=str(values["root_cause"]),
                affected_component=str(values["affected_component"]),
                summary=str(values["summary"]),
                evidence=dict(values.get("evidence") or {}),
                action=values.get("action"),
                action_result=dict(values.get("action_result") or {}),
                improvement_suggestion=values.get("improvement_suggestion"),
                suggestion_status="pending",
            )
            self.session.add(row)
        else:
            if (
                row.project_id != values["project_id"]
                or row.change_name != values["change_name"]
                or row.candidate_sha != values.get("candidate_sha")
            ):
                raise ValueError(
                    "Watchdog diagnosis identity changed for an existing run/stage generation"
                )
            row.status = str(values["status"])
            row.root_cause = str(values["root_cause"])
            row.summary = str(values["summary"])
            row.evidence = dict(values.get("evidence") or {})
            row.action = values.get("action")
            row.action_result = dict(values.get("action_result") or {})
            if values.get("improvement_suggestion"):
                row.improvement_suggestion = values["improvement_suggestion"]
            row.updated_at = datetime.now(UTC)
        self.session.flush()
        return self._diagnosis_payload(row)

    def get_by_run_stage_generation(
        self, run_id: str, stage: str, candidate_generation: int
    ) -> dict[str, Any] | None:
        row = self.session.scalar(
            select(WatchdogDiagnosisModel).where(
                WatchdogDiagnosisModel.run_id == run_id,
                WatchdogDiagnosisModel.stage == stage,
                WatchdogDiagnosisModel.candidate_generation == candidate_generation,
            )
        )
        return self._diagnosis_payload(row) if row is not None else None

    def get_diagnosis(self, diagnosis_id: str) -> dict[str, Any] | None:
        row = self.session.get(WatchdogDiagnosisModel, diagnosis_id)
        return self._diagnosis_payload(row) if row is not None else None

    def update_diagnosis(
        self, diagnosis_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = self.session.get(WatchdogDiagnosisModel, diagnosis_id)
        if row is None:
            return None
        for key, value in updates.items():
            if hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = datetime.now(UTC)
        self.session.flush()
        return self._diagnosis_payload(row)

    def list_diagnoses(
        self,
        *,
        project_id: str | None = None,
        run_id: str | None = None,
        suggestion_status: str | None = None,
        suggestions_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        statement = select(WatchdogDiagnosisModel)
        if project_id:
            statement = statement.where(WatchdogDiagnosisModel.project_id == project_id)
        if run_id:
            statement = statement.where(WatchdogDiagnosisModel.run_id == run_id)
        if suggestion_status:
            statement = statement.where(
                WatchdogDiagnosisModel.suggestion_status == suggestion_status
            )
        if suggestions_only:
            statement = statement.where(WatchdogDiagnosisModel.improvement_suggestion.is_not(None))
        rows = self.session.scalars(
            statement.order_by(WatchdogDiagnosisModel.created_at.desc()).limit(limit)
        ).all()
        return [self._diagnosis_payload(row) for row in rows]

    def set_suggestion_status(self, diagnosis_id: str, value: str) -> dict[str, Any] | None:
        if value not in {"converted", "discarded"}:
            raise ValueError("Unsupported suggestion status")
        row = self.session.scalar(
            select(WatchdogDiagnosisModel)
            .where(WatchdogDiagnosisModel.id == diagnosis_id)
            .with_for_update()
        )
        if row is None or row.improvement_suggestion is None:
            return None
        if row.suggestion_status == "pending":
            row.suggestion_status = value
            row.updated_at = datetime.now(UTC)
        elif row.suggestion_status != value:
            raise ValueError("Suggestion was already handled")
        self.session.flush()
        return self._diagnosis_payload(row)

    @staticmethod
    def _settings_payload(row: WatchdogSettingsModel) -> dict[str, Any]:
        return {
            "provider_id": row.provider_id,
            "harness_id": row.harness_id,
            "canonical_model_id": row.canonical_model_id,
            "inactivity_threshold_minutes": row.inactivity_threshold_minutes,
            "mode": row.mode,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _diagnosis_payload(row: WatchdogDiagnosisModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "run_id": row.run_id,
            "change_name": row.change_name,
            "stage": row.stage,
            "candidate_sha": row.candidate_sha,
            "candidate_generation": row.candidate_generation,
            "status": row.status,
            "root_cause": row.root_cause,
            "affected_component": row.affected_component,
            "summary": row.summary,
            "evidence": dict(row.evidence or {}),
            "action": row.action,
            "action_result": dict(row.action_result or {}),
            "improvement_suggestion": row.improvement_suggestion,
            "suggestion_status": row.suggestion_status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
