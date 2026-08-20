## Purpose

Provides durable PostgreSQL persistence, versioned Alembic migration `004_deepseek_audit` (revising `003_review_pipeline`), and relational models for DeepSeek audit executions, overall risk assessments, structured audit findings, and immutable lifecycle events.

## ADDED Requirements

### Requirement: Audit record persistence
The system SHALL persist audit execution records in a dedicated PostgreSQL `audits` table via Alembic revision `004_deepseek_audit` (revising `003_review_pipeline`), recording `id`, `job_id`, `project_id`, `change_name`, `candidate_sha`, `base_sha`, `status`, `risk`, `summary`, `error_message`, and UTC timestamps.

#### Scenario: Audit lifecycle state tracked
- **WHEN** an audit execution begins and completes
- **THEN** an audit record is created with initial status `AUDIT_RUNNING`, updating atomically to `AUDIT_COMPLETED` (for passing low/medium risk), `AUDIT_BLOCKED` (for high/critical risk), `AUDIT_FAILED`, or `AUDIT_TIMED_OUT` with populated risk assessment and summary.

#### Scenario: Candidate identity binding
- **WHEN** an audit record is inserted or updated
- **THEN** the system guarantees the record is immutably linked to the exact `candidate_sha` and `base_sha` evaluated by the auditor.

### Requirement: Structured audit findings persistence
The system SHALL persist individual auditor findings in a dedicated PostgreSQL `audit_findings` table referencing the parent audit record, capturing `severity` (`low`, `medium`, `high`, `critical`), `category`, `message`, `file`, and `location`.

#### Scenario: Audit findings stored transactionally
- **WHEN** DeepSeek Direct returns an audit result containing one or more findings
- **THEN** the findings are inserted into `audit_findings` within the same database transaction that updates the parent audit status and risk level.

#### Scenario: Audit completed with zero findings
- **WHEN** DeepSeek Direct returns an audit result with an empty findings array and low risk
- **THEN** the parent audit record is marked `AUDIT_COMPLETED` with risk `low` and zero associated rows in `audit_findings`.

### Requirement: Audit lifecycle event logging
The system SHALL append structured event records to the `events` table across all audit lifecycle transitions.

#### Scenario: Lifecycle events emitted
- **WHEN** an audit transitions between lifecycle states (e.g. running, completed, blocked, failed, timed out)
- **THEN** structured events (`JOB_AUDIT_RUNNING`, `JOB_AUDIT_COMPLETED`, `JOB_AUDIT_BLOCKED`, `JOB_AUDIT_FAILED`, `AUDIT_TIMEOUT`, `AUDIT_MALFORMED_OUTPUT`) are appended with timestamp and payload details.
