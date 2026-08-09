package bot

import "testing"

func TestMissing(t *testing.T) {
	g := Gate{Allowed: map[string]struct{}{"index": {}}}
	v, r := g.Check(nil, 1, 0.1)
	if v != Challenge || r != "MISSING_INTENT" {
		t.Fatalf("%s %s", v, r)
	}
}

func TestAllow(t *testing.T) {
	g := Gate{Allowed: map[string]struct{}{"index": {}}}
	v, _ := g.Check(&Intent{"c1", "index", "ops@x.com", 10, 100}, 50, 1)
	if v != Allow {
		t.Fatal(v)
	}
}
