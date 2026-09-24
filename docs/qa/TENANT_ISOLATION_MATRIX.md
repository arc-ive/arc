# Tenant Isolation Matrix (Phase 2)

Invariant: a principal of Tenant A must not read, modify, delete, execute, or operate on Tenant B resources unless the documented authorization model explicitly permits it.

Enforcement layers (all must hold): SQL `WHERE tenant_id` → service derives tenant only from trusted `TenantContext` (X-10 membership) → path-vs-context mismatch 403 → cross-tenant reads indistinguishable from missing (404/empty).

## Resource matrix

| Resource | Endpoints | Owner | R/C/U/D/X | Auth mechanism | Expected cross-tenant |
|---|---|---|---|---|---|
| Skills | `/tenants/{t}/skills*`, `/execute`, `/resume` | `skills.tenant_id` | R+C+U+D+X | `skill:*` perms + membership + path check | 404; execute 404; lists exclude |
| Knowledge docs/chunks | `/tenants/{t}/knowledge*`, `/search` | `knowledge_documents/chunks.tenant_id` | R+C+U+D+S | `knowledge:*` + membership + path check | 404; search empty; lists exclude |
| Tool executions | observability reads only | `tool_execution_records.tenant_id` | R | `observability:read` | excluded from aggregates |
| Approvals | `/tenants/{t}/approvals*`, `/decisions`, resume paths | `approval_requests.tenant_id` | R+Dc+X | `approval:read/decide` + four-eyes | 404; consume refused, zero executions |
| Agent runs/traces | `/agent/runs*`, observability reads | `agent_run_records.tenant_id` | R+X | `agent:execute`, `observability:read` | 404/empty traces |
| Connectors | `/tenants/{t}/connectors*`, `/sync` | `connector_configs.tenant_id` | R+C+X | `connector:*` + membership | 404; lists exclude |
| Connector credentials | `/tenants/{t}/connectors/credentials/*` | `connector_credentials.tenant_id` | R+C+U+D | `connector:manage_credentials` | 404; metadata never leaks |
| Webhook events | `/tenants/{t}/webhooks/events`, `/process`, ingest HMAC | `webhook_events.tenant_id` | R+X | `webhook:read/process`; ingress bound by env config | 404; uniform 401 on ingest |
| Memberships/users | `/tenants/{t}/memberships`, `/users` | `memberships` junction | R+C+D | `membership:create`, `tenant:read` | 404/empty; no enumeration |
| Observability aggregates | `/tenants/{t}/observability/*` | computed per tenant | R | `observability:read` | no B rows; platform view tenant-blind |
| LLM usage | `/tenants/{t}/observability/llm-usage*` | `llm_usage_records.tenant_id` | R | `observability:read` | excluded |
| Capabilities | `/platform/*`, `/tenants/{t}/capabilities` | platform + `tenant_capabilities` | R+U | platform-admin only | 403 for non-admins (not tenant-gated) |
| Tenants | `/tenants/{t}`, `/platform/tenants` | `tenants` | R+U | `tenant:read/update` + membership | denied without membership |

Platform-global (no tenant boundary by design): `tenants` identity rows via platform listings (admin only), `users` directory (admin only), `platform_capabilities`, `sessions` (user-scoped).

## Indirect access paths to test

IDs/UUIDs in paths, `?tenant_id=` query overrides, path-vs-context mismatches, search/substring queries, pagination over full lists, sorted listings, filters (`status`, `source_type`), observability aggregations, approval resume with foreign IDs, webhook event IDs, connector sync IDs, knowledge external IDs.
