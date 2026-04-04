"""Engram memory object model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MemoryKind(str, Enum):
    CONSTRAINT = "constraint"
    DECISION = "decision"
    PROCEDURE = "procedure"
    FACT = "fact"
    GUARDRAIL = "guardrail"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUSPECT = "suspect"
    OBSOLETE = "obsolete"


class MemoryOrigin(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    COMPILED = "compiled"


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_summary(content: str) -> str:
    if len(content) <= 200:
        return content
    return content[:197] + "..."


@dataclass
class MemoryObject:
    content: str
    kind: MemoryKind
    id: str = field(default_factory=_generate_id)
    summary: str = ""
    project: str | None = None
    path_scope: str | None = None
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    evidence_link: str | None = None
    origin: MemoryOrigin = MemoryOrigin.HUMAN
    status: MemoryStatus = MemoryStatus.ACTIVE
    strength: float = 0.5
    pinned: bool = False
    created_at: datetime = field(default_factory=_now)
    accessed_at: datetime | None = None
    last_verified: datetime | None = None
    access_count: int = 0

    def __post_init__(self):
        if not self.summary:
            self.summary = _make_summary(self.content)
