# Arc — Approvals

How Arc stops a high-risk action, who decides it, and how an approved
action is finally run.

Everything below was verified against a running instance, not read from
source. Where behaviour is enforced by a specific line, it is cited.

---

## 1. What an approval is

An approval is a **single-use licence to perform one exact call**.

It is not a role, not a permission, and not a general permit. It binds
five things, and all five must still hold at the moment the action runs:

| Bound to | Enforced by |
|---|---|
| Tenant | `approval_requests.tenant_id`, and every read is tenant-scoped |
| Requester | `requester_user_id` — only they may spend it |
| Tool | `tool_name` |
| Tool version | `tool_version` — a tool that changes invalidates approvals for the old one |
| Exact arguments | `arguments_digest`, SHA-256 of the canonical JSON of the **validated** arguments |

The digest is computed *after* pydantic validation, using the same input
model the execution path uses. An approval can therefore never be
consumed with materially different arguments.

## 2. Why approvals exist

Two separate concepts, which V2-ADR-011 says must not be merged:

- **Skill-level approval** — `skill.approval_required` stops a Skill.
- **Tool-level approval** — `REQUIRE_HUMAN_APPROVAL` execution policy
  stops one tool call.

They answer different questions ("should this procedure run at all?" vs
"should this specific action be taken?"), and collapsing them would make
a low-risk Skill containing a high-risk Tool look safe.

V2-ADR-012 is the other half: **approval is not authorization**.
Authorization is revalidated at execution time. An approval never
substitutes for holding the permission.

## 3. Which actions require approval

Approval is a property of the **tool**, declared in the platform
registry — never inferred from risk level, and never decided by the LLM.

Today the platform catalogue holds two tools:

| Tool | Risk | Policy |
|---|---|---|
| `check_service_health` | low | `ALLOW` |
| `grant_temporary_access` | high | `REQUIRE_HUMAN_APPROVAL` |

Risk level and approval policy are deliberately independent fields. A
high-risk tool is not automatically gated, and a gated tool is not
automatically high-risk. Reading one from the other is the merge
V2-ADR-011 forbids.

## 4. Who can request, and who can decide

Requesting is a side effect of trying to execute: any caller holding
`tool:execute` in the tenant raises an approval by attempting a gated
tool.

Deciding requires `approval:decide`.

Measured in the reference environment:

| Role | `tool:execute` | `approval:read` | `approval:decide` |
|---|---|---|---|
| `platform_administrator` | ✓ | ✓ | ✓ |
| `company_administrator` | ✓ | ✓ | ✓ |
| `operations_user` | ✓ | — | — |
| `employee` | — | — | — |

A platform administrator holds these permissions globally but, per
V2-ADR-003, is not a member of any customer tenant and therefore
receives 403 on every tenant-scoped approval route. Platform
administration does not reach into customer data.

## 5. The four-eyes rule

A requester may never decide their own request.

Enforced server-side in the approval service and verified live:

```
admin raises appr-6d764f4715554785
admin then decides it
→ 403 "Approval appr-6d764f4715554785 requester
   ref-acme-technologies-company-admin cannot approve or reject
   their own request"
```

This is the rule with the most demo value and the most operational
friction: it means a tenant needs at least two people holding
`approval:decide` for any of its own administrators to raise a gated
action. See §9.

## 6. Lifecycle

```
pending ──approve──► approved ──run──► consumed
   │                    │
   │                    └──(never run, TTL elapses)──► expired
   ├──reject──► rejected
   └──(TTL elapses)──► expired
```

- **TTL** is 24 hours from creation (`TTL_HOURS`), enforced both by the
  service and by a database CHECK that `expires_at > created_at`.
- **Expiry is derived on read**, not mutated in place, so a stale row
  never reads as valid. A sweep job settles them.
- **Single use**: `consumed_at` is set atomically on spend. A second
  attempt is refused.
- **Idempotent creation**: a unique partial index on
  `(tenant_id, tool_name, tool_version, arguments_digest)` where
  `status='pending'` means retrying the same call reuses the open
  request instead of creating duplicates.

## 7. Security

Every one of these was exercised against a running instance and refused:

| Attack | Result |
|---|---|
| Fabricated approval id | `ApprovalNotFoundError` |
| Approval id from another tenant | 403 — reads are tenant-scoped |
| Resume by a different user | 403 — only the requester may spend it |
| Modified arguments + valid approval | 403 — digest mismatch |
| Reuse of a consumed approval | 403 — single use |
| Decision by a user without `approval:decide` | 403 |
| Requester deciding their own request | 403 — four-eyes |

The model never participates. An LLM may *propose* a tool call; the
proposal is untrusted data. Authorization, policy, approval and audit
are decided by deterministic services after the proposal is parsed.

## 8. Resume — how an approved action runs

The problem this solves: resuming requires the **exact** arguments to
match `arguments_digest`, and nothing held them. `input_summary` is
deliberately redacted and truncated, so it cannot reconstruct them, and
the requester's browser cannot be relied on — approval is asynchronous
and the tab is long closed by the time someone decides.

So the exact arguments are stored with the approval, **encrypted at
rest** using the same AES-256-GCM service and key versioning that
protects connector credentials.

```
POST /tenants/{id}/tools/{name}/execute
{"approval_id": "appr-…"}          ← no arguments

→ server recovers the approved arguments
→ re-hashes them and checks arguments_digest
→ revalidates authorization
→ executes
→ 200 {"status": "executed", "output": {…}}
```

Three properties make this safe:

1. **Recovery is a convenience, never an authority.** The recovered
   arguments are checked against the digest exactly as caller-supplied
   arguments are. The stored copy is never trusted on its own.
2. **The ciphertext never leaves storage by accident.** It is not in the
   repository's shared column list, so it never rides along on an
   approval object returned to a caller. The resume path asks for it by
   name, through a tenant-scoped read that additionally requires
   `APPROVED` status and the original requester.
3. **Sending arguments still works, and is still bound.** A caller who
   supplies arguments is checked against the digest as before, so
   modified arguments are refused.

If no encryption key is configured, approvals still work in full — only
server-side resume is unavailable. The degradation is logged, not
silent.

## 9. Configuration

| Variable | Effect if unset |
|---|---|
| `CONNECTOR_ENCRYPTION_KEY` | Approval gate unaffected; server-side resume unavailable; connector credential management falls back to ENV |

The key is base64-encoded 32 bytes (AES-256).

## 10. Worked example

```bash
# 1. A requester attempts a gated action.
POST /tenants/acme/tools/grant_temporary_access/execute
{"input": {"justification": "INC-9001 needs billing access"}}
→ 200 {"status": "approval_required", "approval_id": "appr-358b…"}
#      Nothing ran. An approval now exists.

# 2. Spending it before a decision is refused.
POST …/execute {"approval_id": "appr-358b…"}
→ 403

# 3. A DIFFERENT person with approval:decide approves it.
POST /tenants/acme/approvals/appr-358b…/decisions
{"decision": "approve"}
→ 200 {"status": "approved", "decided_by_user_id": "…"}

# 4. The requester spends it, sending no arguments.
POST …/execute {"approval_id": "appr-358b…"}
→ 200 {"status": "executed",
       "output": {"justification": "INC-9001 needs billing access",
                  "granted": true}}

# 5. Spending it again is refused.
→ 403
```

## 11. Known gap

A requester holding `tool:execute` but **not** `approval:read` cannot
reach the Approvals page to spend their own approval. In the reference
environment that is the operations user. The company administrator who
does hold `approval:read` cannot approve their own request under
four-eyes.

The API loop is complete; the UI loop needs a decision — either a second
administrator in the reference data, or a self-scoped read letting a
requester always see the requests they made.
