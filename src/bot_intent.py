"""Bot intent receipt — declared purpose and attenuating edge-traffic authority."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum


def digest(obj: object) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(name)


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
    intent_id: str = ""
    total_requests: int = 0
    not_before: float = 0.0
    parent_fingerprint: str = ""
    delegation_depth: int = 0

    def __post_init__(self) -> None:
        for name, value in (("client_id", self.client_id), ("purpose", self.purpose)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(name)
        if not isinstance(self.contact, str):
            raise TypeError("contact")
        _finite("max_rps", float(self.max_rps))
        _finite("not_after", float(self.not_after))
        _finite("not_before", float(self.not_before))
        if self.max_rps <= 0:
            raise ValueError("max_rps")
        if self.not_after <= self.not_before:
            raise ValueError("validity_window")
        if not isinstance(self.total_requests, int) or isinstance(self.total_requests, bool) or self.total_requests < 0:
            raise ValueError("total_requests")
        if not isinstance(self.delegation_depth, int) or isinstance(self.delegation_depth, bool) or self.delegation_depth < 0:
            raise ValueError("delegation_depth")
        if self.intent_id and not self.intent_id.strip():
            raise ValueError("intent_id")
        if self.parent_fingerprint and (
            len(self.parent_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in self.parent_fingerprint)
        ):
            raise ValueError("parent_fingerprint")

    @property
    def strict(self) -> bool:
        return bool(self.intent_id) and self.total_requests > 0

    def fingerprint(self) -> str:
        return digest(
            {
                "client_id": self.client_id,
                "purpose": self.purpose,
                "max_rps": self.max_rps,
                "not_after": self.not_after,
                "contact": self.contact,
                "intent_id": self.intent_id,
                "total_requests": self.total_requests,
                "not_before": self.not_before,
                "parent_fingerprint": self.parent_fingerprint,
                "delegation_depth": self.delegation_depth,
            }
        )


@dataclass(frozen=True)
class BotRequestDecision:
    intent_id: str
    request_id: str
    verdict: EdgeVerdict
    reason: str | None
    intent_fingerprint: str
    requests: int
    consumed_after: int
    remaining_after: int
    fingerprint: str


class BotIntentGate:
    def __init__(self, allowed_purposes: set[str]):
        if not allowed_purposes or any(not isinstance(p, str) or not p.strip() for p in allowed_purposes):
            raise ValueError("allowed_purposes")
        self.allowed_purposes = frozenset(allowed_purposes)

    def check(
        self,
        intent: BotIntentReceipt | None,
        now: float,
        observed_rps: float,
    ) -> tuple[EdgeVerdict, str | None]:
        _finite("now", float(now))
        _finite("observed_rps", float(observed_rps))
        if observed_rps < 0:
            raise ValueError("observed_rps")
        if intent is None:
            return EdgeVerdict.CHALLENGE, "MISSING_INTENT"
        if now < intent.not_before:
            return EdgeVerdict.CHALLENGE, "NOT_YET_VALID"
        if now > intent.not_after:
            return EdgeVerdict.CHALLENGE, "EXPIRED_INTENT"
        if intent.purpose not in self.allowed_purposes:
            return EdgeVerdict.BLOCK, "PURPOSE_NOT_ALLOWED"
        if observed_rps > intent.max_rps:
            return EdgeVerdict.BLOCK, "RPS_EXCEEDED"
        if not intent.contact:
            return EdgeVerdict.CHALLENGE, "NO_CONTACT"
        return EdgeVerdict.ALLOW, None


class BotIntentLedger:
    """Strict intent registry with hierarchical budgets and replay-resistant request IDs.

    This is a local reference authority ledger. Receipt authenticity is not implied;
    issuer signatures remain an explicit next evolution.
    """

    def __init__(self, gate: BotIntentGate):
        if not isinstance(gate, BotIntentGate):
            raise TypeError("gate")
        self.gate = gate
        self._intents: dict[str, BotIntentReceipt] = {}
        self._consumed: dict[str, int] = {}
        self._allocated_children: dict[str, int] = {}
        self._seen_requests: dict[str, set[str]] = {}

    def _require_strict(self, intent: BotIntentReceipt) -> None:
        if not intent.strict:
            raise ValueError("STRICT_INTENT_REQUIRED")
        if not intent.contact:
            raise ValueError("CONTACT_REQUIRED")
        if intent.purpose not in self.gate.allowed_purposes:
            raise ValueError("PURPOSE_NOT_ALLOWED")

    def register_root(self, intent: BotIntentReceipt) -> BotIntentReceipt:
        self._require_strict(intent)
        if intent.parent_fingerprint or intent.delegation_depth != 0:
            raise ValueError("ROOT_LINEAGE_INVALID")
        prior = self._intents.get(intent.intent_id)
        if prior is not None:
            if prior.fingerprint() != intent.fingerprint():
                raise ValueError("INTENT_ID_REBOUND")
            return prior
        self._intents[intent.intent_id] = intent
        self._consumed[intent.intent_id] = 0
        self._allocated_children[intent.intent_id] = 0
        self._seen_requests[intent.intent_id] = set()
        return intent

    def delegate(
        self,
        parent_intent_id: str,
        child_intent_id: str,
        *,
        client_id: str,
        purpose: str,
        max_rps: float,
        total_requests: int,
        not_after: float,
        contact: str | None = None,
        not_before: float | None = None,
    ) -> BotIntentReceipt:
        parent = self._intents.get(parent_intent_id)
        if parent is None:
            raise KeyError("PARENT_INTENT_UNKNOWN")
        if not child_intent_id or not child_intent_id.strip():
            raise ValueError("child_intent_id")
        if child_intent_id in self._intents:
            raise ValueError("INTENT_ID_ALREADY_REGISTERED")
        if purpose != parent.purpose:
            raise ValueError("PURPOSE_ESCALATION")
        _finite("max_rps", float(max_rps))
        _finite("not_after", float(not_after))
        child_not_before = parent.not_before if not_before is None else float(not_before)
        _finite("not_before", child_not_before)
        if max_rps <= 0 or max_rps > parent.max_rps:
            raise ValueError("RPS_ESCALATION")
        if not isinstance(total_requests, int) or isinstance(total_requests, bool) or total_requests <= 0:
            raise ValueError("total_requests")
        if child_not_before < parent.not_before or not_after > parent.not_after or not_after <= child_not_before:
            raise ValueError("TIME_ESCALATION")

        available = (
            parent.total_requests
            - self._consumed[parent.intent_id]
            - self._allocated_children[parent.intent_id]
        )
        if total_requests > available:
            raise ValueError("BUDGET_ESCALATION")

        child = BotIntentReceipt(
            client_id=client_id,
            purpose=purpose,
            max_rps=max_rps,
            not_after=not_after,
            contact=parent.contact if contact is None else contact,
            intent_id=child_intent_id,
            total_requests=total_requests,
            not_before=child_not_before,
            parent_fingerprint=parent.fingerprint(),
            delegation_depth=parent.delegation_depth + 1,
        )
        self._require_strict(child)
        self._intents[child_intent_id] = child
        self._consumed[child_intent_id] = 0
        self._allocated_children[child_intent_id] = 0
        self._seen_requests[child_intent_id] = set()
        self._allocated_children[parent.intent_id] += total_requests
        return child

    def _decision(
        self,
        intent: BotIntentReceipt,
        request_id: str,
        verdict: EdgeVerdict,
        reason: str | None,
        requests: int,
    ) -> BotRequestDecision:
        consumed = self._consumed[intent.intent_id]
        remaining = max(0, intent.total_requests - consumed)
        body = {
            "intent_id": intent.intent_id,
            "request_id": request_id,
            "verdict": verdict.value,
            "reason": reason,
            "intent_fingerprint": intent.fingerprint(),
            "requests": requests,
            "consumed_after": consumed,
            "remaining_after": remaining,
        }
        return BotRequestDecision(
            intent_id=intent.intent_id,
            request_id=request_id,
            verdict=verdict,
            reason=reason,
            intent_fingerprint=intent.fingerprint(),
            requests=requests,
            consumed_after=consumed,
            remaining_after=remaining,
            fingerprint=digest(body),
        )

    def authorize_request(
        self,
        intent_id: str,
        request_id: str,
        *,
        now: float,
        observed_rps: float,
        requests: int = 1,
    ) -> BotRequestDecision:
        intent = self._intents.get(intent_id)
        if intent is None:
            raise KeyError("INTENT_UNKNOWN")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id")
        if not isinstance(requests, int) or isinstance(requests, bool) or requests <= 0:
            raise ValueError("requests")

        if request_id in self._seen_requests[intent_id]:
            return self._decision(intent, request_id, EdgeVerdict.BLOCK, "REQUEST_REPLAYED", requests)

        verdict, reason = self.gate.check(intent, now, observed_rps)
        if verdict is not EdgeVerdict.ALLOW:
            return self._decision(intent, request_id, verdict, reason, requests)

        if self._consumed[intent_id] + self._allocated_children[intent_id] + requests > intent.total_requests:
            return self._decision(intent, request_id, EdgeVerdict.BLOCK, "TOTAL_BUDGET_EXCEEDED", requests)

        self._consumed[intent_id] += requests
        self._seen_requests[intent_id].add(request_id)
        return self._decision(intent, request_id, EdgeVerdict.ALLOW, None, requests)

    def remaining_unallocated_budget(self, intent_id: str) -> int:
        intent = self._intents[intent_id]
        return max(
            0,
            intent.total_requests
            - self._consumed[intent_id]
            - self._allocated_children[intent_id],
        )
