"""Domain enumeration types for mini me."""

from enum import Enum


class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


class ChangeStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class ReadinessState(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    BLOCKED = "BLOCKED"


class AgentRole(str, Enum):
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"
    HELPER = "helper"


class EventType(str, Enum):
    PROJECT_REGISTERED = "PROJECT_REGISTERED"
    PROJECT_UPDATED = "PROJECT_UPDATED"
    CHANGE_DISCOVERED = "CHANGE_DISCOVERED"
    READINESS_EVALUATED = "READINESS_EVALUATED"
    WORK_BOUND = "WORK_BOUND"
    SYNC_FAILED = "SYNC_FAILED"
    SYNC_RECONCILED = "SYNC_RECONCILED"
    STATUS_CHECKED = "STATUS_CHECKED"
