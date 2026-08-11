from __future__ import annotations
import math
import unittest
from src.bot_intent import (
    BotIntentGate,
    BotIntentLedger,
    BotIntentReceipt,
    EdgeVerdict,
)


class BotTests(unittest.TestCase):
    def test_missing(self):
        gate = BotIntentGate({"index"})
        verdict, reason = gate.check(None, 1.0, 0.1)
        self.assertEqual(verdict, EdgeVerdict.CHALLENGE)
        self.assertEqual(reason, "MISSING_INTENT")

    def test_legacy_allow_remains_compatible(self):
        gate = BotIntentGate({"index"})
        intent = BotIntentReceipt("c1", "index", 10.0, 100.0, "ops@example.com")
        verdict, reason = gate.check(intent, 50.0, 1.0)
        self.assertEqual(verdict, EdgeVerdict.ALLOW)
        self.assertIsNone(reason)

    def strict_root(self, total=100):
        return BotIntentReceipt(
            client_id="root-client",
            purpose="index",
            max_rps=20.0,
            not_after=100.0,
            contact="ops@example.com",
            intent_id="root",
            total_requests=total,
            not_before=10.0,
        )

    def test_intent_identity_is_one_shot(self):
        ledger = BotIntentLedger(BotIntentGate({"index"}))
        root = self.strict_root()
        first = ledger.register_root(root)
        second = ledger.register_root(root)
        self.assertEqual(first, second)
        rebound = BotIntentReceipt(
            client_id="other",
            purpose="index",
            max_rps=20.0,
            not_after=100.0,
            contact="ops@example.com",
            intent_id="root",
            total_requests=100,
            not_before=10.0,
        )
        with self.assertRaisesRegex(ValueError, "INTENT_ID_REBOUND"):
            ledger.register_root(rebound)

    def test_delegation_only_attenuates_and_reserves_hierarchical_budget(self):
        ledger = BotIntentLedger(BotIntentGate({"index", "crawl"}))
        ledger.register_root(self.strict_root(total=100))
        child = ledger.delegate(
            "root",
            "child-1",
            client_id="worker",
            purpose="index",
            max_rps=10.0,
            total_requests=60,
            not_before=20.0,
            not_after=80.0,
        )
        self.assertEqual(child.delegation_depth, 1)
        self.assertEqual(child.parent_fingerprint, self.strict_root(total=100).fingerprint())
        self.assertEqual(ledger.remaining_unallocated_budget("root"), 40)

        ledger.delegate(
            "root",
            "child-2",
            client_id="worker2",
            purpose="index",
            max_rps=5.0,
            total_requests=40,
            not_after=70.0,
        )
        self.assertEqual(ledger.remaining_unallocated_budget("root"), 0)
        with self.assertRaisesRegex(ValueError, "BUDGET_ESCALATION"):
            ledger.delegate(
                "root",
                "child-3",
                client_id="worker3",
                purpose="index",
                max_rps=1.0,
                total_requests=1,
                not_after=60.0,
            )

    def test_delegation_rejects_scope_rate_and_time_escalation(self):
        ledger = BotIntentLedger(BotIntentGate({"index", "crawl"}))
        ledger.register_root(self.strict_root())
        base = dict(client_id="worker", total_requests=10, not_after=80.0)
        with self.assertRaisesRegex(ValueError, "PURPOSE_ESCALATION"):
            ledger.delegate("root", "p", purpose="crawl", max_rps=10.0, **base)
        with self.assertRaisesRegex(ValueError, "RPS_ESCALATION"):
            ledger.delegate("root", "r", purpose="index", max_rps=21.0, **base)
        with self.assertRaisesRegex(ValueError, "TIME_ESCALATION"):
            ledger.delegate(
                "root", "t", purpose="index", max_rps=10.0,
                client_id="worker", total_requests=10, not_after=101.0,
            )

    def test_successful_request_nonce_is_replay_resistant(self):
        ledger = BotIntentLedger(BotIntentGate({"index"}))
        ledger.register_root(self.strict_root(total=10))
        first = ledger.authorize_request("root", "req-1", now=20.0, observed_rps=2.0, requests=3)
        self.assertEqual(first.verdict, EdgeVerdict.ALLOW)
        self.assertEqual(first.consumed_after, 3)
        self.assertEqual(first.remaining_after, 7)
        replay = ledger.authorize_request("root", "req-1", now=20.0, observed_rps=2.0, requests=3)
        self.assertEqual(replay.verdict, EdgeVerdict.BLOCK)
        self.assertEqual(replay.reason, "REQUEST_REPLAYED")
        self.assertEqual(replay.consumed_after, 3)
        replay_again = ledger.authorize_request("root", "req-1", now=20.0, observed_rps=2.0, requests=3)
        self.assertEqual(replay.fingerprint, replay_again.fingerprint)

    def test_total_budget_blocks_without_overconsumption(self):
        ledger = BotIntentLedger(BotIntentGate({"index"}))
        ledger.register_root(self.strict_root(total=2))
        allowed = ledger.authorize_request("root", "r1", now=20.0, observed_rps=1.0, requests=2)
        self.assertEqual(allowed.verdict, EdgeVerdict.ALLOW)
        blocked = ledger.authorize_request("root", "r2", now=20.0, observed_rps=1.0, requests=1)
        self.assertEqual(blocked.verdict, EdgeVerdict.BLOCK)
        self.assertEqual(blocked.reason, "TOTAL_BUDGET_EXCEEDED")
        self.assertEqual(blocked.consumed_after, 2)

    def test_parent_allocation_limits_own_traffic(self):
        ledger = BotIntentLedger(BotIntentGate({"index"}))
        ledger.register_root(self.strict_root(total=10))
        ledger.delegate(
            "root", "child", client_id="w", purpose="index", max_rps=5.0,
            total_requests=8, not_after=90.0,
        )
        allowed = ledger.authorize_request("root", "own-1", now=20.0, observed_rps=1.0, requests=2)
        self.assertEqual(allowed.verdict, EdgeVerdict.ALLOW)
        blocked = ledger.authorize_request("root", "own-2", now=20.0, observed_rps=1.0, requests=1)
        self.assertEqual(blocked.reason, "TOTAL_BUDGET_EXCEEDED")

    def test_not_before_and_nonfinite_observations_fail_closed(self):
        ledger = BotIntentLedger(BotIntentGate({"index"}))
        ledger.register_root(self.strict_root())
        early = ledger.authorize_request("root", "early", now=9.0, observed_rps=1.0)
        self.assertEqual(early.verdict, EdgeVerdict.CHALLENGE)
        self.assertEqual(early.reason, "NOT_YET_VALID")
        with self.assertRaises(ValueError):
            BotIntentGate({"index"}).check(self.strict_root(), math.nan, 1.0)
        with self.assertRaises(ValueError):
            BotIntentReceipt("c", "index", math.inf, 100.0, "x")


if __name__ == "__main__":
    unittest.main()
