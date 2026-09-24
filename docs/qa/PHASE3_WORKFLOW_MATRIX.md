# Phase 3 Workflow Matrix

| Workflow | Entry Point | Roles | Expected State Changes | Coverage | Result |
|---|---|---|---|---|---|
| Approval request→decide→resume→replay→reject | Skills UI + approvals queue + resume API | ops-user (requester), company-admin (decider) | pending → approved → consumed; replay refused; 2nd rejected | `e2e/workflows/approval-lifecycle.spec.js` | PASS |
| Agent run→trace | Agents page | company-admin | FAILED/no_decision + persisted trace, tenant-attributed | `e2e/workflows/agent-run.spec.js` | PASS |
| Employee skill surface denial | Skills page + API | employee | redirect from route; API 403 | `e2e/security/rbac-matrix.spec.js` | PASS |
| Ops create denial | Skills page + API | ops-user | no create UI; API 403; execute UI present | `e2e/security/rbac-matrix.spec.js` | PASS |
| Tenant isolation (UI+API) | foreign workspace URL + APIs | company-admin (non-member) | blocked page; 403/404, no disclosure | `e2e/security/tenant-isolation.spec.js`, `tests/test_tenant_isolation_matrix.py` (16) | PASS |
| Login / Ask Arc / skill execute | login, ask, skills pages | company-admin | session; grounded answer; succeeded run | `e2e/smoke/*.spec.js` (6) | PASS |
