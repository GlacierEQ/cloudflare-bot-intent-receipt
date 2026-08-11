package bot

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
)

type Verdict string

const (
	Allow     Verdict = "ALLOW"
	Challenge Verdict = "CHALLENGE"
	Block     Verdict = "BLOCK"
)

type Intent struct {
	ClientID          string
	Purpose           string
	Contact           string
	MaxRPS            float64
	NotAfter          float64
	IntentID          string
	TotalRequests     int
	NotBefore         float64
	ParentFingerprint string
	DelegationDepth   int
}

func (i Intent) Strict() bool { return i.IntentID != "" && i.TotalRequests > 0 }

func (i Intent) Fingerprint() string {
	body := struct {
		ClientID          string  `json:"client_id"`
		Purpose           string  `json:"purpose"`
		MaxRPS            float64 `json:"max_rps"`
		NotAfter          float64 `json:"not_after"`
		Contact           string  `json:"contact"`
		IntentID          string  `json:"intent_id"`
		TotalRequests     int     `json:"total_requests"`
		NotBefore         float64 `json:"not_before"`
		ParentFingerprint string  `json:"parent_fingerprint"`
		DelegationDepth   int     `json:"delegation_depth"`
	}{i.ClientID, i.Purpose, i.MaxRPS, i.NotAfter, i.Contact, i.IntentID, i.TotalRequests, i.NotBefore, i.ParentFingerprint, i.DelegationDepth}
	encoded, _ := json.Marshal(body)
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:])
}

type Gate struct {
	Allowed map[string]struct{}
}

func finite(value float64) bool { return !math.IsNaN(value) && !math.IsInf(value, 0) }

func (g *Gate) Check(intent *Intent, now, rps float64) (Verdict, string) {
	if !finite(now) || !finite(rps) || rps < 0 {
		return Block, "INVALID_OBSERVATION"
	}
	if intent == nil {
		return Challenge, "MISSING_INTENT"
	}
	if now < intent.NotBefore {
		return Challenge, "NOT_YET_VALID"
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

type Decision struct {
	IntentID          string
	RequestID         string
	Verdict           Verdict
	Reason            string
	IntentFingerprint string
	Requests          int
	ConsumedAfter     int
	RemainingAfter    int
	Fingerprint       string
}

type Ledger struct {
	Gate              Gate
	intents           map[string]Intent
	consumed          map[string]int
	allocatedChildren map[string]int
	seenRequests      map[string]map[string]struct{}
}

func NewLedger(gate Gate) *Ledger {
	return &Ledger{
		Gate:              gate,
		intents:           map[string]Intent{},
		consumed:          map[string]int{},
		allocatedChildren: map[string]int{},
		seenRequests:      map[string]map[string]struct{}{},
	}
}

func (l *Ledger) validateStrict(intent Intent) error {
	if !intent.Strict() {
		return errors.New("STRICT_INTENT_REQUIRED")
	}
	if intent.ClientID == "" || intent.Purpose == "" || intent.Contact == "" {
		return errors.New("INTENT_IDENTITY_REQUIRED")
	}
	if !finite(intent.MaxRPS) || intent.MaxRPS <= 0 || !finite(intent.NotBefore) || !finite(intent.NotAfter) || intent.NotAfter <= intent.NotBefore {
		return errors.New("INTENT_LIMIT_INVALID")
	}
	if intent.TotalRequests <= 0 || intent.DelegationDepth < 0 {
		return errors.New("INTENT_BUDGET_INVALID")
	}
	if _, ok := l.Gate.Allowed[intent.Purpose]; !ok {
		return errors.New("PURPOSE_NOT_ALLOWED")
	}
	return nil
}

func (l *Ledger) RegisterRoot(intent Intent) (Intent, error) {
	if err := l.validateStrict(intent); err != nil {
		return Intent{}, err
	}
	if intent.ParentFingerprint != "" || intent.DelegationDepth != 0 {
		return Intent{}, errors.New("ROOT_LINEAGE_INVALID")
	}
	if prior, ok := l.intents[intent.IntentID]; ok {
		if prior.Fingerprint() != intent.Fingerprint() {
			return Intent{}, errors.New("INTENT_ID_REBOUND")
		}
		return prior, nil
	}
	l.intents[intent.IntentID] = intent
	l.consumed[intent.IntentID] = 0
	l.allocatedChildren[intent.IntentID] = 0
	l.seenRequests[intent.IntentID] = map[string]struct{}{}
	return intent, nil
}

type DelegateRequest struct {
	ParentIntentID string
	ChildIntentID  string
	ClientID       string
	Purpose        string
	MaxRPS         float64
	TotalRequests  int
	NotAfter       float64
	Contact        string
	NotBefore      float64
}

func (l *Ledger) Delegate(req DelegateRequest) (Intent, error) {
	parent, ok := l.intents[req.ParentIntentID]
	if !ok {
		return Intent{}, errors.New("PARENT_INTENT_UNKNOWN")
	}
	if req.ChildIntentID == "" {
		return Intent{}, errors.New("CHILD_INTENT_ID_REQUIRED")
	}
	if _, exists := l.intents[req.ChildIntentID]; exists {
		return Intent{}, errors.New("INTENT_ID_ALREADY_REGISTERED")
	}
	if req.Purpose != parent.Purpose {
		return Intent{}, errors.New("PURPOSE_ESCALATION")
	}
	if !finite(req.MaxRPS) || req.MaxRPS <= 0 || req.MaxRPS > parent.MaxRPS {
		return Intent{}, errors.New("RPS_ESCALATION")
	}
	if req.TotalRequests <= 0 {
		return Intent{}, errors.New("TOTAL_REQUESTS_INVALID")
	}
	notBefore := req.NotBefore
	if notBefore == 0 {
		notBefore = parent.NotBefore
	}
	if !finite(notBefore) || !finite(req.NotAfter) || notBefore < parent.NotBefore || req.NotAfter > parent.NotAfter || req.NotAfter <= notBefore {
		return Intent{}, errors.New("TIME_ESCALATION")
	}
	available := parent.TotalRequests - l.consumed[parent.IntentID] - l.allocatedChildren[parent.IntentID]
	if req.TotalRequests > available {
		return Intent{}, errors.New("BUDGET_ESCALATION")
	}
	contact := req.Contact
	if contact == "" {
		contact = parent.Contact
	}
	child := Intent{
		ClientID: req.ClientID, Purpose: req.Purpose, Contact: contact,
		MaxRPS: req.MaxRPS, NotAfter: req.NotAfter, IntentID: req.ChildIntentID,
		TotalRequests: req.TotalRequests, NotBefore: notBefore,
		ParentFingerprint: parent.Fingerprint(), DelegationDepth: parent.DelegationDepth + 1,
	}
	if err := l.validateStrict(child); err != nil {
		return Intent{}, err
	}
	l.intents[child.IntentID] = child
	l.consumed[child.IntentID] = 0
	l.allocatedChildren[child.IntentID] = 0
	l.seenRequests[child.IntentID] = map[string]struct{}{}
	l.allocatedChildren[parent.IntentID] += child.TotalRequests
	return child, nil
}

func (l *Ledger) decision(intent Intent, requestID string, verdict Verdict, reason string, requests int) Decision {
	consumed := l.consumed[intent.IntentID]
	remaining := intent.TotalRequests - consumed
	if remaining < 0 {
		remaining = 0
	}
	body := struct {
		IntentID          string  `json:"intent_id"`
		RequestID         string  `json:"request_id"`
		Verdict           Verdict `json:"verdict"`
		Reason            string  `json:"reason"`
		IntentFingerprint string  `json:"intent_fingerprint"`
		Requests          int     `json:"requests"`
		ConsumedAfter     int     `json:"consumed_after"`
		RemainingAfter    int     `json:"remaining_after"`
	}{intent.IntentID, requestID, verdict, reason, intent.Fingerprint(), requests, consumed, remaining}
	encoded, _ := json.Marshal(body)
	sum := sha256.Sum256(encoded)
	return Decision{intent.IntentID, requestID, verdict, reason, intent.Fingerprint(), requests, consumed, remaining, hex.EncodeToString(sum[:])}
}

func (l *Ledger) AuthorizeRequest(intentID, requestID string, now, observedRPS float64, requests int) (Decision, error) {
	intent, ok := l.intents[intentID]
	if !ok {
		return Decision{}, errors.New("INTENT_UNKNOWN")
	}
	if requestID == "" || requests <= 0 {
		return Decision{}, errors.New("REQUEST_INVALID")
	}
	if _, replayed := l.seenRequests[intentID][requestID]; replayed {
		return l.decision(intent, requestID, Block, "REQUEST_REPLAYED", requests), nil
	}
	verdict, reason := l.Gate.Check(&intent, now, observedRPS)
	if verdict != Allow {
		return l.decision(intent, requestID, verdict, reason, requests), nil
	}
	if l.consumed[intentID]+l.allocatedChildren[intentID]+requests > intent.TotalRequests {
		return l.decision(intent, requestID, Block, "TOTAL_BUDGET_EXCEEDED", requests), nil
	}
	l.consumed[intentID] += requests
	l.seenRequests[intentID][requestID] = struct{}{}
	return l.decision(intent, requestID, Allow, "", requests), nil
}

func (l *Ledger) RemainingUnallocatedBudget(intentID string) (int, error) {
	intent, ok := l.intents[intentID]
	if !ok {
		return 0, errors.New("INTENT_UNKNOWN")
	}
	remaining := intent.TotalRequests - l.consumed[intentID] - l.allocatedChildren[intentID]
	if remaining < 0 {
		remaining = 0
	}
	return remaining, nil
}
