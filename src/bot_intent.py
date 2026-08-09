"""Bot intent receipt — declared purpose for automated edge traffic."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum


def digest(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EdgeVerdict(str, Enum):
    ALLOW = "ALLOW"
    CHALLENGE = "CHALLENGE"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class BotIntentReceipt:
    client_id: str
    purpose: str
    max_rps: float
    not_after: float
    contact: str

    def fingerprint(self) -> str:
        return digest(self.__dict__)


class BotIntentGate:
    def __init__(self, allowed_purposes: set[str]):
        self.allowed_purposes = allowed_purposes

    def check(self, intent: BotIntentReceipt | None, now: float, observed_rps: float) -> tuple[EdgeVerdict, str | None]:
        if intent is None:
            return EdgeVerdict.CHALLENGE, "MISSING_INTENT"
        if now > intent.not_after:
            return EdgeVerdict.CHALLENGE, "EXPIRED_INTENT"
        if intent.purpose not in self.allowed_purposes:
            return EdgeVerdict.BLOCK, "PURPOSE_NOT_ALLOWED"
        if observed_rps > intent.max_rps:
            return EdgeVerdict.BLOCK, "RPS_EXCEEDED"
        if not intent.contact:
            return EdgeVerdict.CHALLENGE, "NO_CONTACT"
        return EdgeVerdict.ALLOW, None
