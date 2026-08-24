# Database Schema

## Data model

PostgreSQL is the system of record. The event stream is authoritative; the remaining event-derived tables are query projections that can be rebuilt. All timestamps are `timestamptz`, all identifiers are UUID unless shown otherwise, and all tenant-scoped relations carry `organization_id` and `project_id` directly.

```text
organizations 1--* projects 1--* agents 1--* executions 1--* events
                                      |                  |        |
                                      |                  |        +--* state_snapshots
                                      |                  +--* beliefs (versions)
                                      |                  +--* evidence
                                      |                  +--* decisions --* decision_evidence --* evidence
                                      |                  +--* tool_calls
                                      |                  +--* environment_states
                                      +--* tools

organizations 1--* memberships
organizations 1--* api_keys
organizations 1--* audit_logs
executions    1--* execution_tags
```

## Core ownership tables

| Table | Key columns | Purpose |
|---|---|---|
| `organizations` | `id`, `name`, `status`, `created_at` | Tenant boundary |
| `projects` | `id`, `organization_id`, `name`, `environment` | Logical product/application scope |
| `agents` | `id`, org/project IDs, `external_agent_key`, `name`, `kind` | Registered instrumented agent |
| `executions` | `id`, org/project/agent IDs, `external_execution_key`, `status`, `started_at`, `completed_at`, `next_sequence_no` | Execution aggregate and sequence allocator |
| `events` | envelope fields in event model | Immutable source of truth |
| `state_snapshots` | `id`, execution ID, `last_sequence_no`, `state_schema_version`, `state_document`, `state_hash`, `event_prefix_hash` | Replay checkpoint |

`external_agent_key` is unique per project; `external_execution_key` is unique per agent. `next_sequence_no` is incremented in the same transaction that inserts an event, using a row lock on `executions`.

## Query projections

| Table | Key columns | Purpose |
|---|---|---|
| `beliefs` | `belief_version_id`, `belief_id`, execution ID, `supersedes_version_id`, `valid_from_sequence`, `valid_until_sequence`, `confidence`, `status` | Belief evolution and point-in-time filters |
| `evidence` | `id`, execution ID, `source_type`, `source_reference`, `produced_by_event_id`, `content_hash`, `redaction_status` | Evidence provenance |
| `decisions` | `id`, execution ID, `event_id`, `selected_action`, `confidence`, `risk_score` | Decision inspection |
| `decision_evidence` | `decision_id`, `evidence_id` | Explicit many-to-many lineage |
| `decision_beliefs` | `decision_id`, `belief_version_id` | Explicit belief lineage |
| `tools` | `id`, project ID, `external_tool_key`, version, descriptor | Tool catalog |
| `tool_calls` | `id`, execution ID, tool ID, `called_event_id`, `result_event_id`, `status` | Call lifecycle |
| `policies` | `id`, project ID, `external_policy_key`, version, descriptor | Policy catalog |
| `policy_evaluations` | `id`, execution ID, policy ID, event ID, result | Decision constraints |
| `environment_states` | `id`, execution ID, event ID, version, sanitized patch/hash | Environment state history |
| `execution_tags` | execution ID, tag | Filtering and retention classes |

Projection rows retain the creating event ID and sequence so their provenance is explicit. Projection updates are idempotent and must be reproducible from the event log.

## Security and operations tables

| Table | Key columns | Purpose |
|---|---|---|
| `memberships` | organization ID, user subject, role | RBAC membership |
| `api_keys` | org/project scope, prefix, `secret_hash`, role, expiry, revoked timestamp | SDK authentication; plaintext never persisted |
| `audit_logs` | org ID, actor, action, resource type/ID, correlation ID, metadata | Security audit trail |
| `counterfactual_runs` | base execution/sequence, substitutions, result state/hash, created_by | Clearly separate simulated branches |

## Constraints and indexes

| Relation | Constraint or index | Reason |
|---|---|---|
| `events` | unique `(execution_id, sequence_no)` | Deterministic replay |
| `events` | unique `(organization_id, idempotency_key)` where key is not null | Safe retries |
| `events` | `(execution_id, occurred_at, sequence_no)` | Timestamp state reconstruction/timeline |
| `events` | `(agent_id, occurred_at desc)` | Agent activity queries |
| `events` | `(event_type, occurred_at desc)` | Event-type operations/analytics |
| `state_snapshots` | unique `(execution_id, last_sequence_no)` | Checkpoint lookup |
| `beliefs` | `(execution_id, belief_id, valid_from_sequence)` | Evolution and as-of queries |
| `decisions` | `(execution_id, event_id)` | Decision lookup from timeline |
| lineage join tables | primary key on both foreign keys | No duplicate graph edges |
| all tenant tables | leading `(organization_id, project_id)` query indexes | Tenant-scoped access paths |

Use JSONB only for versioned event payloads, metadata, serialized snapshots, flexible descriptors, and sanitized environment patches. First-class query fields such as ownership, timestamps, status, confidence, event type, and graph edges are relational columns.

## Partitioning, RLS, and retention

Start with ordinary tables and the indexes above. Partition `events` and large derived tables by `organization_id` hash and time only when observed volume warrants it; premature partitioning complicates migrations and tenant lifecycle operations.

PostgreSQL row-level security policies require `organization_id` to equal the request-scoped database setting, set only after API authentication. Worker jobs use a constrained service role and set the same scope. RLS supplements, rather than replaces, application-level scoped queries.

Retention is configured per organization/project. Expiry is implemented through governed archival or tombstoning workflows, never an unlogged mutation of an event. Backups encrypt at rest and recovery testing is part of the deployment runbook.
