#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bot_intent import BotIntentGate, BotIntentReceipt, EdgeVerdict

def main() -> int:
    g = BotIntentGate({"index"})
    intent = BotIntentReceipt("c1", "index", 10.0, 100.0, "ops@example.com")
    v, r = g.check(intent, 50.0, 1.0)
    out = {"verdict": v.value, "reason": r, "ok": v is EdgeVerdict.ALLOW}
    print(json.dumps(out, sort_keys=True))
    return 0 if out["ok"] else 1
if __name__ == "__main__":
    raise SystemExit(main())
