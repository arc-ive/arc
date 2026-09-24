# Tenant Isolation Findings (Phase 2)

## Verdict

**No tested cross-tenant violation was reproduced.** 16 API scenarios + 2 browser scenarios pass: direct cross-tenant reads return 404/403, listings and search exclude foreign rows, writes are denied, and the foreign workspace URL renders a blocked page.

## Coverage

API (`tests/test_tenant_isolation_matrix.py`, 16 tests): skills get/list/execute, knowledge get/list/search, approvals get/list, agent-run list/trace, connectors get/list, webhook events list, usage + LLM-usage aggregates, membership listing by non-members. Browser (`frontend/e2e/security/tenant-isolation.spec.js`, 2 tests): foreign workspace blocked page + own workspace loads; foreign API denied without disclosure.

## Gaps (not vulnerabilities — untested paths)

- Approval consume with a foreign approval ID at API level (covered at service level in existing suites, not via HTTP here).
- Webhook event injection into Tenant B then read as A (requires HMAC endpoint config; list-emptiness asserted).
- Platform-admin cross-tenant visibility is by design (admin routes), not tested here.

## Environment notes

- `authorization_override` replaces (not merges) the role map — tests register both users in one call.
- Local runs need `POSTGRES_DB=arc_test` (Issue #232 guard) and the dev `APPLICATION_ROLE_ASSIGNMENTS` mapping, otherwise all requests 403.
- No application code was modified; no vulnerability found to fix.
