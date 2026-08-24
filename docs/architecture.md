# Architecture

## System boundary

Agent Time Machine is a temporal observability platform. Its authoritative data is an ordered, immutable event stream per execution. Read models (belief history, evidence lineage, timeline entries, and snapshots) are materialized from that stream and may always be rebuilt.

```text
                    +-----------------------+
                    |  Next.js dashboard    |
                    | timeline / inspect /  |
                    | diff / replay         |
                    +-----------+-----------+
                                | HTTPS REST
                                v
+----------------+    +-----------------------+    +----------------------+
| Python SDK /   |--->| FastAPI               |--->| PostgreSQL           |
| external agent |    | auth, validation,     |    | event store          |
+----------------+    | redaction, tenancy    |    | projections,         |
                      +-----+------------+----+    | snapshots            |
                            |            |         +----------+-----------+
                            |            |                    ^
                            v            v                    |
                 +--------------+  +----------------+          |
                 | Reconstruction|  | Investigation  |----------+
                 | engine        |  | / replay       |
                 +--------------+  +----------------+
                            |
                            v
                 +------------------+
                 | canonical state  |
                 | transition rules |
                 +------------------+

                 Optional, non-critical path
                 +----------------------------------------------+
                 | worker: projections, analytics, embeddings   |
                 | Redis only for job queue/cache if introduced  |
                 +----------------------------------------------+
```

## Components and responsibilities

| Component | Responsibility | Must not do |
|---|---|---|
| SDK | Validate and redact locally where configured; attach execution context; send idempotent events | Infer or upload private reasoning |
| Ingestion API | Authenticate API key, enforce tenant and project boundary, validate, assign deterministic sequence, append event | Mutate an existing event |
| Event store | Preserve original accepted event envelope and payload hash | Serve as a mutable state store |
| Reconstruction engine | Load checkpoint and replay ordered events into canonical `AgentState` | Call external tools or an LLM |
| Projection worker | Maintain fast query tables and create checkpoints | Become a correctness dependency for exact reconstruction |
| Investigation service | Traverse recorded decision, belief, evidence, observation, policy and tool references | Invent an explanation when lineage is absent |
| Replay service | Return ordered transitions and controlled simulations | Claim simulations occurred |
| Dashboard | Render a time-selected state and source-linked provenance | Present raw logs as the primary investigation experience |

## Temporal model and ordering

Every event has three relevant times:

- `occurred_at`: when the agent says the transition occurred (UTC).
- `ingested_at`: when the platform accepted it (UTC).
- `sequence_no`: a strictly increasing, transactionally assigned number within an execution.

`sequence_no` is the replay order and resolves clock skew and equal timestamps. Requests at a timestamp replay all events with `occurred_at <= T`, ordered by `(occurred_at, sequence_no)`. A request addressed by event ID replays through that event's sequence. An SDK may provide an idempotency key; a retry returns the already accepted event rather than duplicating a transition.

Late-arriving events are never inserted retroactively into the original sequence. They receive the next sequence number and retain their supplied `occurred_at`. The timeline distinguishes occurrence and ingestion time. This makes audit history honest and replay deterministic.

## Reconstruction algorithm

`state_at(execution_id, selector)` is synchronous and deterministic.

1. Authorize the caller for the execution's organization and project.
2. Resolve `selector` to a target sequence: event ID, or the greatest qualifying `(occurred_at, sequence_no)`.
3. Load the newest valid checkpoint with `last_sequence_no <= target` (otherwise use an empty execution state).
4. Read immutable events after that checkpoint through the target in replay order.
5. Apply the versioned pure transition function for each event.
6. Return the canonical state, replay boundary, and source event IDs.

Snapshots are an optimization, not authority. A checkpoint records the canonical serialized state, state-schema version, final sequence, and a hash of the state and event prefix. On read or test, replaying all events and replaying from a checkpoint must yield identical canonical state. A schema migration introduces a new transition version and rebuilds affected checkpoints.

## Canonical historical state

```text
AgentState
  organization_id, project_id, agent_id, execution_id
  as_of: { event_id, sequence_no, occurred_at }
  execution_status
  goals[]
  active_plan
  beliefs[]                 # current versions as of the selected point
  evidence[]                # visible provenance objects
  observations[]
  available_tools[]
  permissions[]
  environment_snapshot
  pending_actions[]
  completed_actions[]
  decision_metadata[]
  aggregate_confidence
  active_risk
```

The canonical transition function is shared by API reconstruction, replay, benchmark oracle fixtures, and snapshot creation. It has no network calls, random values, or wall-clock reads.

## Investigation and replay

An investigation starts with an action or decision and follows only explicit references:

```text
action -> decision -> belief(s) / policy -> evidence -> observation or source
```

It returns a structured causal graph plus a concise explanation assembled from the recorded decision summary and lineage. Missing edges produce an `insufficient_evidence` conclusion; no model-generated causal claims may fill a gap.

Replay iterates each event with `{state_before, event, state_after}`. Counterfactual requests create an ephemeral simulation branch from a selected base sequence plus explicitly allowed substitutions (belief confidence, tool result, policy result, environment field, tool availability). The branch is labeled `SIMULATED / COUNTERFACTUAL`, has its own ID and lineage, and cannot append to or modify the original execution.

## Security and tenancy

The ownership chain is `organization -> project -> agent -> execution -> event`. Tenant identifiers appear on all tenant-scoped tables, not merely parent tables, so every query can be scoped and indexed directly. The API derives tenant scope from the authenticated principal; request bodies cannot choose another organization.

- API keys are stored only as a keyed hash and displayed only once at creation.
- RBAC roles: `owner`, `admin`, `developer`, `viewer`, plus narrowly scoped service API keys.
- PostgreSQL row-level security is defense in depth; application predicates are still required.
- A redaction pipeline runs before persistence, replaces configured sensitive patterns with typed redaction markers, and records that redaction occurred without retaining the secret.
- Audit records cover authentication, key changes, access to executions, exports, and counterfactual creation.
- Rate limits apply per organization, key, and endpoint class.

## Deployment shape

The initial deployment consists of Next.js, FastAPI, and managed PostgreSQL. Redis and a worker are introduced only when asynchronous projection, analytics, or embedding throughput requires them. The critical ingestion and reconstruction path remains available without the worker. PostgreSQL backups, migration gating, structured JSON logs, correlation IDs, health checks, and metrics are production requirements.

## Architecture decisions

| Decision | Why | Consequence |
|---|---|---|
| PostgreSQL event store | Strong transactions, JSONB only for flexible event payloads, relational provenance queries | Partitioning and archival policy needed at scale |
| Per-execution sequence | Deterministic replay despite clock skew | Client timestamps cannot change historical order |
| Snapshots as cache | Fast temporal lookup without compromising auditability | Requires invariant tests and rebuild tooling |
| Explicit graph references | Evidence explanations are auditable | Instrumented agents must supply IDs |
| No chain-of-thought | Privacy and reliability | Explanations are bounded by recorded summaries and links |
| REST first | Simple SDK and dashboard integration | Streaming can be added later for live timelines |
