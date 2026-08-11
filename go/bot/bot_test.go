package bot

import "testing"

func strictRoot(total int) Intent {
	return Intent{
		ClientID: "root-client", Purpose: "index", Contact: "ops@x.com",
		MaxRPS: 20, NotAfter: 100, IntentID: "root", TotalRequests: total, NotBefore: 10,
	}
}

func TestMissing(t *testing.T) {
	g := Gate{Allowed: map[string]struct{}{"index": {}}}
	v, r := g.Check(nil, 1, 0.1)
	if v != Challenge || r != "MISSING_INTENT" {
		t.Fatalf("%s %s", v, r)
	}
}

func TestLegacyAllow(t *testing.T) {
	g := Gate{Allowed: map[string]struct{}{"index": {}}}
	legacy := Intent{ClientID: "c1", Purpose: "index", Contact: "ops@x.com", MaxRPS: 10, NotAfter: 100}
	v, _ := g.Check(&legacy, 50, 1)
	if v != Allow {
		t.Fatal(v)
	}
}

func TestIntentIdentityOneShot(t *testing.T) {
	ledger := NewLedger(Gate{Allowed: map[string]struct{}{"index": {}}})
	root := strictRoot(100)
	if _, err := ledger.RegisterRoot(root); err != nil {
		t.Fatal(err)
	}
	if _, err := ledger.RegisterRoot(root); err != nil {
		t.Fatal(err)
	}
	rebound := root
	rebound.ClientID = "other"
	if _, err := ledger.RegisterRoot(rebound); err == nil || err.Error() != "INTENT_ID_REBOUND" {
		t.Fatalf("expected rebound rejection, got %v", err)
	}
}

func TestDelegationAttenuatesAndReservesBudget(t *testing.T) {
	ledger := NewLedger(Gate{Allowed: map[string]struct{}{"index": {}, "crawl": {}}})
	root := strictRoot(100)
	if _, err := ledger.RegisterRoot(root); err != nil {
		t.Fatal(err)
	}
	child, err := ledger.Delegate(DelegateRequest{
		ParentIntentID: "root", ChildIntentID: "child-1", ClientID: "worker",
		Purpose: "index", MaxRPS: 10, TotalRequests: 60, NotBefore: 20, NotAfter: 80,
	})
	if err != nil {
		t.Fatal(err)
	}
	if child.DelegationDepth != 1 || child.ParentFingerprint != root.Fingerprint() {
		t.Fatal(child)
	}
	remaining, _ := ledger.RemainingUnallocatedBudget("root")
	if remaining != 40 {
		t.Fatalf("remaining=%d", remaining)
	}
	_, err = ledger.Delegate(DelegateRequest{
		ParentIntentID: "root", ChildIntentID: "bad", ClientID: "worker",
		Purpose: "crawl", MaxRPS: 10, TotalRequests: 10, NotAfter: 80,
	})
	if err == nil || err.Error() != "PURPOSE_ESCALATION" {
		t.Fatalf("expected purpose escalation, got %v", err)
	}
	_, err = ledger.Delegate(DelegateRequest{
		ParentIntentID: "root", ChildIntentID: "rate", ClientID: "worker",
		Purpose: "index", MaxRPS: 21, TotalRequests: 10, NotAfter: 80,
	})
	if err == nil || err.Error() != "RPS_ESCALATION" {
		t.Fatalf("expected rate escalation, got %v", err)
	}
	_, err = ledger.Delegate(DelegateRequest{
		ParentIntentID: "root", ChildIntentID: "time", ClientID: "worker",
		Purpose: "index", MaxRPS: 10, TotalRequests: 10, NotAfter: 101,
	})
	if err == nil || err.Error() != "TIME_ESCALATION" {
		t.Fatalf("expected time escalation, got %v", err)
	}
}

func TestAggregateChildBudgetCannotExceedParent(t *testing.T) {
	ledger := NewLedger(Gate{Allowed: map[string]struct{}{"index": {}}})
	if _, err := ledger.RegisterRoot(strictRoot(10)); err != nil {
		t.Fatal(err)
	}
	if _, err := ledger.Delegate(DelegateRequest{
		ParentIntentID: "root", ChildIntentID: "a", ClientID: "a", Purpose: "index",
		MaxRPS: 5, TotalRequests: 8, NotAfter: 90,
	}); err != nil {
		t.Fatal(err)
	}
	_, err := ledger.Delegate(DelegateRequest{
		ParentIntentID: "root", ChildIntentID: "b", ClientID: "b", Purpose: "index",
		MaxRPS: 5, TotalRequests: 3, NotAfter: 90,
	})
	if err == nil || err.Error() != "BUDGET_ESCALATION" {
		t.Fatalf("expected budget escalation, got %v", err)
	}
}

func TestRequestReplayAndBudget(t *testing.T) {
	ledger := NewLedger(Gate{Allowed: map[string]struct{}{"index": {}}})
	if _, err := ledger.RegisterRoot(strictRoot(3)); err != nil {
		t.Fatal(err)
	}
	first, err := ledger.AuthorizeRequest("root", "r1", 20, 1, 2)
	if err != nil || first.Verdict != Allow || first.ConsumedAfter != 2 || first.RemainingAfter != 1 {
		t.Fatal(first, err)
	}
	replay, err := ledger.AuthorizeRequest("root", "r1", 20, 1, 2)
	if err != nil || replay.Verdict != Block || replay.Reason != "REQUEST_REPLAYED" || replay.ConsumedAfter != 2 {
		t.Fatal(replay, err)
	}
	blocked, err := ledger.AuthorizeRequest("root", "r2", 20, 1, 2)
	if err != nil || blocked.Verdict != Block || blocked.Reason != "TOTAL_BUDGET_EXCEEDED" || blocked.ConsumedAfter != 2 {
		t.Fatal(blocked, err)
	}
}

func TestParentReservationLimitsOwnTraffic(t *testing.T) {
	ledger := NewLedger(Gate{Allowed: map[string]struct{}{"index": {}}})
	if _, err := ledger.RegisterRoot(strictRoot(10)); err != nil {
		t.Fatal(err)
	}
	if _, err := ledger.Delegate(DelegateRequest{
		ParentIntentID: "root", ChildIntentID: "child", ClientID: "child", Purpose: "index",
		MaxRPS: 5, TotalRequests: 8, NotAfter: 90,
	}); err != nil {
		t.Fatal(err)
	}
	allowed, _ := ledger.AuthorizeRequest("root", "own-1", 20, 1, 2)
	if allowed.Verdict != Allow {
		t.Fatal(allowed)
	}
	blocked, _ := ledger.AuthorizeRequest("root", "own-2", 20, 1, 1)
	if blocked.Reason != "TOTAL_BUDGET_EXCEEDED" {
		t.Fatal(blocked)
	}
}

func TestNotBefore(t *testing.T) {
	ledger := NewLedger(Gate{Allowed: map[string]struct{}{"index": {}}})
	if _, err := ledger.RegisterRoot(strictRoot(10)); err != nil {
		t.Fatal(err)
	}
	decision, err := ledger.AuthorizeRequest("root", "early", 9, 1, 1)
	if err != nil || decision.Verdict != Challenge || decision.Reason != "NOT_YET_VALID" {
		t.Fatal(decision, err)
	}
}
