# ARC Risk Register (Phase 0)

## CRITICAL

- **Authentication bypass/session fixation** — full account takeover. Reason: session cookies + OIDC + dev-auth coexist; any gap is game-over. Covers AUTH-01..04.
- **Cross-tenant data access** — enterprise data breach. Reason: 14 tenant-scoped tables; one missing `tenant_id` predicate leaks customer data. Covers TEN-01..04. Mitigated today by SQL+service+re-check layers, but each new query re-opens it.
- **Connector credential exposure** — secret leakage. Reason: plaintext enters API, encrypted at rest; 503-without-key and whitespace/length guards are the boundary. Covers CON-02.
- **Approval bypass / replay** — unauthorized high-risk tool execution. Reason: single-use atomic consume is the only guard. Covers APL-01/AGT-02.
- **AI cross-tenant context** — prompt carries another tenant's data. Reason: LLM output is irretrievable once generated; prevention (retrieval filter + prompt sanitization) is the only control. Covers TEN-02, RAG-03.
- **Production-impacting mutations without approval** — HIGH-risk tools executing directly. Reason: policy metadata could be malformed; defense-in-depth check exists and must be tested. Covers TOL/APL paths.

## HIGH

- **RBAC matrix drift** — new endpoint ships without permission check. Reason: permissions are per-route declarations; omission fails open at the router. Covers RBAC-01.
- **Webhook forgery/replay** — forged events trigger skills. Reason: HMAC + timestamp window are the entire boundary. Covers WHK-01.
- **Provider outage handling** — raw 500s with no trace. Reason: every new LLM call site re-opens it. Covers LLM-01.
- **Membership/provisioning errors** — wrong users in tenants. Reason: targeted user_id is provisioning input, not caller identity. Covers PLT-01.
- **Platform blindness failure** — tenant data in global aggregates. Reason: one `GROUP BY tenant_id` away from leakage. Covers OBS-02.
- **PII persistence** — regulated data at rest. Reason: guard must run before every write path. Covers RAG-03.

## MEDIUM

- **Observability attribution errors** — wrong tenant/user on telemetry; misbilled usage. Covers OBS-01.
- **Stale/failed background sweeps** — approvals never expire; stuck webhooks never recover. Covers approval_sweep, retry_sweep.
- **Pagination/list-limit bypass** — unbounded reads. Covered by list-limit tests; new lists must obey.
- **Rate-limit gaps** — auth/webhook brute force. Covered for auth+ingest; new public routes need review.
- **Migration safety** — `ensure_schema` splitter forbids `;` in comments; one-off scripts untested in CI path.
- **Accessibility regressions** — dialogs unusable by keyboard. Covered partially by scans.

## LOW

- **Display-only pages** (health badges, static ledgers) — cosmetic.
- **Dev-auth leakage to production** — guarded by `APP_ENV` + production-config job; keep the job.
- **Placeholder/mock copy in UI** — e.g. legacy alias links; UX, not security.
