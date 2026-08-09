from __future__ import annotations
import unittest
from src.bot_intent import BotIntentGate, BotIntentReceipt, EdgeVerdict

class Adv(unittest.TestCase):
    def test_rps_exceeded_blocks(self):
        g = BotIntentGate({"index"})
        intent = BotIntentReceipt("c1", "index", 1.0, 100.0, "ops@x.com")
        v, r = g.check(intent, 50.0, 5.0)
        self.assertEqual(v, EdgeVerdict.BLOCK)
        self.assertEqual(r, "RPS_EXCEEDED")
    def test_bad_purpose_blocks(self):
        g = BotIntentGate({"index"})
        intent = BotIntentReceipt("c1", "scrape", 10.0, 100.0, "ops@x.com")
        v, r = g.check(intent, 50.0, 1.0)
        self.assertEqual(v, EdgeVerdict.BLOCK)
    def test_expired_challenges(self):
        g = BotIntentGate({"index"})
        intent = BotIntentReceipt("c1", "index", 10.0, 10.0, "ops@x.com")
        v, r = g.check(intent, 50.0, 1.0)
        self.assertEqual(v, EdgeVerdict.CHALLENGE)

