package bot

type Verdict string

const (
	Allow     Verdict = "ALLOW"
	Challenge Verdict = "CHALLENGE"
	Block     Verdict = "BLOCK"
)

type Intent struct {
	ClientID, Purpose, Contact string
	MaxRPS                     float64
	NotAfter                   float64
}

type Gate struct {
	Allowed map[string]struct{}
}

func (g *Gate) Check(intent *Intent, now, rps float64) (Verdict, string) {
	if intent == nil {
		return Challenge, "MISSING_INTENT"
	}
	if now > intent.NotAfter {
		return Challenge, "EXPIRED_INTENT"
	}
	if _, ok := g.Allowed[intent.Purpose]; !ok {
		return Block, "PURPOSE_NOT_ALLOWED"
	}
	if rps > intent.MaxRPS {
		return Block, "RPS_EXCEEDED"
	}
	if intent.Contact == "" {
		return Challenge, "NO_CONTACT"
	}
	return Allow, ""
}
