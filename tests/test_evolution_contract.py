import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = json.loads((ROOT / "machine" / "excellence-state.json").read_text(encoding="utf-8"))
POSITION = json.loads((ROOT / "machine" / "canonical-position.json").read_text(encoding="utf-8"))
TARGET_PATH = ROOT / "machine" / "target-contract.json"
TARGET = json.loads(TARGET_PATH.read_text(encoding="utf-8"))
RECEIPT_PATH = ROOT / "machine" / "evolution-receipts" / "2026-08-11-hierarchical-intent-ledger.json"
RECEIPT = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


class EvolutionContractTests(unittest.TestCase):
    def test_machine_target_is_conflict_free(self):
        raw = TARGET_PATH.read_text(encoding="utf-8")
        self.assertNotIn("<<<<<<<", raw)
        self.assertNotIn("=======", raw)
        self.assertNotIn(">>>>>>>", raw)
        self.assertEqual(TARGET["current"]["state"], "EVOLVING")

    def test_consumed_cursor_is_exact_proof_bound(self):
        self.assertEqual(RECEIPT["result"], "PASS")
        self.assertEqual(RECEIPT["candidate_source_sha"], "adc535a7f2bcb6a2bf5856c0462ecc9ce0de6667")
        self.assertEqual(RECEIPT["workflow_run"], 31463256513)
        event = STATE["evolution_history"][-1]
        self.assertEqual(event["consumed_cursor"], RECEIPT["consumed_cursor"])
        self.assertEqual(event["receipt"], str(RECEIPT_PATH.relative_to(ROOT)))

    def test_next_cursor_is_consistent(self):
        expected = "next:signed_intent_issuer_authority_durable_distributed_nonce_and_budget_state"
        self.assertEqual(STATE["evolution_cursor"], expected)
        self.assertEqual(TARGET["next_evolution"], expected)
        self.assertEqual(RECEIPT["next_cursor"], expected)
        self.assertIn("Authenticate intent issuers", POSITION["next_evolution"])
        self.assertIn("durable distributed storage", POSITION["next_evolution"])

    def test_claim_ceiling_and_authority_boundary_do_not_inflate(self):
        self.assertEqual(STATE["claim_ceiling"], "PROMOTED")
        boundary = " ".join(TARGET["nonclaims"]).lower()
        self.assertIn("no cloudflare affiliation", boundary)
        self.assertIn("issuer authenticity is not cryptographically verified", boundary)
        self.assertIn("in-memory rather than durable distributed state", boundary)


if __name__ == "__main__":
    unittest.main()
