from __future__ import annotations
import unittest
from src.bot_intent import BotIntentGate, BotIntentReceipt, EdgeVerdict

class BotTests(unittest.TestCase):
    def test_missing(self):
        g = BotIntentGate({"index"})
        v, r = g.check(None, 1.0, 0.1)
        self.assertEqual(v, EdgeVerdict.CHALLENGE)

    def test_allow(self):
        g = BotIntentGate({"index"})
        intent = BotIntentReceipt("c1", "index", 10.0, 100.0, "ops@example.com")
        v, r = g.check(intent, 50.0, 1.0)
        self.assertEqual(v, EdgeVerdict.ALLOW)

if __name__ == "__main__":
    unittest.main()
