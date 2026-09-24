# ARC E2E Test Matrix (Phase 0)

Columns: ID · Module · Workflow · Role · Preconditions · Actions · Expected · API · DB effect · Tenant boundary · Failures · Layer · Priority.

## Authentication/session (CRITICAL)

- **AUTH-01** · Auth · Google login · anonymous · OIDC configured · click sign-in, approve, callback · lands `/app`, session+CSRF cookies set · `GET /auth/google`, `/auth/callback` · `sessions` row · n/a · denied identity → `/login?error` · E2E · P0
- **AUTH-02** · Auth · Logout (all) · any · active session · logout-all · cookies cleared, session invalidated · `POST /auth/logout-all` · sessions deleted · n/a · — · E2E/API · P0
- **AUTH-03** · Auth · Session expiry · any · aged session · use app · redirected to login · `GET /auth/me` 401 · — · n/a · — · API · P0
- **AUTH-04** · Auth · Dev reference login (dev only) · anonymous · `APP_ENV=development` · persona sign-in · session as reference user · `/internal/dev/auth/*` · sessions row · n/a · unknown user 403 · API · P1

## Authorization/RBAC (CRITICAL)

- **RBAC-01..N** · each permission × 5 roles · matrix sweep · seeded user · call endpoint per role · allow/deny per matrix · all guarded routes · none · wrong-role 403 · API · P0
- **RBAC-02** · Approvals · four-eyes · requester + decider · requester attempts decide · 403, state unchanged · decisions endpoint · no state change · — · — · API · P0
- **RBAC-03** · Platform · non-admin hits `/platform/*` · member · open console routes · 403, redirect · platform routes · none · — · E2E · P0

## Tenant isolation (CRITICAL)

- **TEN-01..N** · each tenant-scoped resource (skills, docs/chunks, tools audit, approvals, agent runs/traces, connectors/creds/sync, webhooks, memberships, usage, LLM usage, capabilities) · cross-tenant read · A-member, B-data exists · GET B's resource as A · 404/empty, never B data · resource GETs · none · **A≠B enforced** · API+E2E · P0
- **TEN-02** · RAG · cross-tenant retrieval · B has docs · A searches B terms · empty contract, LLM never called · search/intelligence · none · SQL filter + re-check · SECURITY · P0
- **TEN-03** · Approvals · cross-tenant consume · B's approved approval · A resumes with it · refused, zero executions · resume endpoints · none · tenant-scoped lookup · SECURITY · P0
- **TEN-04** · Membership · path-vs-context mismatch · member of A · call with B path · 403 · all tenant routes · none · — · API · P0

## Skills/Tools/Agent/Approvals (CRITICAL/HIGH)

- **SKL-01** · Skills · create→execute→result · admin · — · dialog flow · succeeded + steps · skills+execute · skill row + tool audit · own tenant · invalid input 400 · E2E · P0
- **SKL-02** · Skills · declared inputs enforced · admin · input-declaring skill · omit/extra inputs · `invalid_skill_inputs`, zero executions · execute · none · — · API · P0
- **APL-01** · Approvals · queue→decide→resume→consumed · requester+decider · HIGH tool denial · approve, resume, replay · first succeeds, replay refused · approvals+resume · approval terminal states · — · wrong digest/tool rejected · E2E · P0
- **APL-02** · Approvals · deny path · decider · pending approval · reject then resume · refused · decisions+resume · rejected state · — · — · API · P1
- **AGT-01** · Agents · goal→run→trace · admin · skill catalogued · start run, open trace · terminal outcome + persisted trace · runs + agent-runs reads · `agent_run_records` · own tenant · provider outage → controlled failure · E2E · P1
- **AGT-02** · Agents · approval-gated skill run · admin · approval_required skill · run → approve → resume · succeeds then replay refused · runs/resume/decisions · trace chain · — · fabricated approval refused · E2E · P0
- **TOL-01** · Tools · unknown per-call key · any with execute · — · execute with `parameters` key · 400/422, zero executions · tools execute · audit row (denial) · — · — · API · P1

## Knowledge/RAG/Intelligence (HIGH)

- **RAG-01** · Company Brain · ingest→search→answer · admin/member · seeded docs · ask question · grounded answer + citations · knowledge+intelligence · docs/chunks/vectors · own tenant · no-match → `answer=None`, LLM uncalled · E2E · P1
- **RAG-02** · Intelligence · source scoping · member · multi-source corpus · scoped ask · only matching-source citations · intelligence/query · none · — · invalid enum 422 · API · P1
- **RAG-03** · Knowledge · PII pre-persist · admin · PII-laden content · ingest + read raw · stored/returned sanitized only · knowledge CRUD · sanitized rows · — · guard failure blocks persist · SECURITY · P0
- **LLM-01** · Providers · outage/429/timeout/invalid-model · any · forced failure · controlled error + trace, no 500 leak · runs/query · usage row (`succeeded=false`) · — · — · INTEGRATION · P1

## Connectors/Webhooks (HIGH)

- **CON-01** · Connectors · connect→sync · admin · provider configured · create + sync · items + audit record · connectors+sync · config+sync rows · own tenant · bad provider 400 · E2E · P1
- **CON-02** · Credentials · create/rotate/delete · admin · encryption key set · lifecycle · metadata only, 409/404 rules · credential endpoints · encrypted bytes · — · whitespace/oversize rejected, missing key 503 · SECURITY · P0
- **WHK-01** · Webhooks · signed ingest→auto-process · external sender · endpoint configured · POST signed event · 200 persisted state, skill executed · ingest/process APIs · event terminal state · tenant from config · bad signature uniform 401, replay deduped · SECURITY · P0
- **WHK-02** · Webhooks · retry→dead-letter · system · failing downstream · sweeps run · terminal verdict, INFO not ERROR · — · status transitions · — · — · INTEGRATION · P2

## Observability/Platform (MEDIUM)

- **OBS-01** · Usage dashboards · member views own metrics · member · traffic exists · open usage · aggregates, no raw rows · usage-summary · none · tenant-scoped · — · E2E · P2
- **OBS-02** · Platform console · admin views global · platform admin · — · open console · tenant-agnostic totals only · platform summary · none · blindness verified · — · SECURITY · P1
- **PLT-01** · Tenants/users admin · platform admin · — · create tenant/user/member · rows + OWNER auto-membership · tenants/users/memberships · rows · — · duplicate 409 · E2E · P1
- **SET-01** · Settings · company profile edit · admin · — · save valid/invalid · persisted/rejected · tenant update · row · own tenant · — · E2E · P2

## Accessibility (MEDIUM, extend scans)

- **A11Y-01** · Dialogs (execute/add-member/create-tenant) · keyboard-only user · — · tab/enter/escape flows · full operability · — · none · — · — · E2E · P2
- **A11Y-02** · Form validation announcements · member · — · submit invalid · errors announced · — · none · — · — · E2E · P2
