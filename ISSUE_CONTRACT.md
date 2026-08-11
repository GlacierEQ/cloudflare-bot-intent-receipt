# ISSUE CONTRACT

## Pain
Flat self-declared bot intent cannot prevent intent-ID rebinding, delegated budget expansion, request replay, or child authority that exceeds the parent that delegated it.

## Success
- Strict intent IDs bind immutable receipt content.
- Delegated child purpose, RPS, total request budget, and validity window can only attenuate parent authority.
- Aggregate child allocations plus parent traffic stay within the parent request budget.
- Successful request IDs cannot consume budget twice.
- Child receipts bind the exact parent fingerprint and delegation depth.
- Request decisions expose deterministic intent-bound budget receipts.
- Legacy flat-gate behavior remains separate from the stronger strict ledger path.

## Boundaries
- Intent issuer identity and receipt authenticity are not cryptographically verified.
- Nonce and budget state are process-local, not durable distributed state.
- No Cloudflare affiliation, adoption, or production traffic-enforcement claim.
