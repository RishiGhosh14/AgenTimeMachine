# Event Model

## Principles

Events are append-only facts accepted by the platform. A correction, retraction, authorization change, or new evidence is represented by another event; historical payloads are never overwritten. Event payloads contain structured operational facts, concise decision summaries, and stable references—not private chain-of-thought.

## Event envelope

Every event uses this logical schema (UUIDs and timestamps are UTC):

| Field | Type | Notes |
|---|---|---|
| `event_id` | UUID | Platform-generated immutable ID |
| `organization_id`, `project_id`, `agent_id`, `execution_id` | UUID | Required ownership scope |
| `sequence_no` | bigint | Platform-assigned, unique within execution |
| `event_type` | enum | Controlled vocabulary below |
| `occurred_at`, `ingested_at` | timestamptz | Agent time and platform time |
| `parent_event_id` | UUID nullable | Causal predecessor when known |
| `causation_id`, `correlation_id` | UUID nullable | Cross-event tracing |
| `idempotency_key` | string nullable | Unique within tenant/key scope when supplied |
| `payload` | JSONB | Validated per event type; no credentials or CoT |
| `metadata` | JSONB | SDK version, redaction markers, source integration |
| `payload_sha256` | char(64) | Canonical payload integrity hash |
| `schema_version` | smallint | Event payload contract version |

The immutable database role has no `UPDATE` or `DELETE` on event rows. A retention or legal-erasure workflow appends a tombstone/redaction event while retaining the audit identity and avoiding content exposure.

## Event vocabulary and state effects

| Event type | Required payload highlights | Canonical state transition |
|---|---|---|
| `EXECUTION_STARTED` | `goal`, optional initial environment | Opens execution and creates initial goal |
| `EXECUTION_COMPLETED` | `outcome`, `status` | Closes execution |
| `GOAL_CREATED` | `goal_id`, `statement`, priority | Adds goal |
| `PLAN_CREATED`, `PLAN_UPDATED` | `plan_id`, steps, status | Sets/replaces active plan version |
| `OBSERVATION_CREATED` | `observation_id`, content, source ref | Adds observation |
| `EVIDENCE_RETRIEVED` | `evidence_id`, kind, source, content/ref | Adds evidence with provenance |
| `BELIEF_CREATED` | belief version object | Opens belief version |
| `BELIEF_UPDATED` | belief version object, supersedes ID | Ends prior version and activates new version |
| `BELIEF_RETRACTED` | `belief_id`, reason, contradicting evidence IDs | Marks version retracted |
| `TOOL_DISCOVERED` | tool descriptor | Adds tool to known set |
| `TOOL_AUTHORIZED`, `TOOL_DENIED` | `tool_id`, policy/ref, scope | Changes available permissions |
| `TOOL_CALLED` | `tool_call_id`, tool ID, sanitized input | Adds pending action/tool call |
| `TOOL_RESULT_RECEIVED` | `tool_call_id`, result evidence/ref | Resolves tool call and adds result evidence |
| `DECISION_CREATED` | decision record | Adds decision metadata and lineage |
| `ACTION_STARTED` | `action_id`, decision ID | Marks action pending/in progress |
| `ACTION_COMPLETED`, `ACTION_FAILED` | `action_id`, outcome/error | Moves action to completed |
| `POLICY_EVALUATED` | `policy_id`, result, rule version | Records policy evidence |
| `HUMAN_APPROVAL_REQUESTED`, `HUMAN_APPROVAL_GRANTED`, `HUMAN_APPROVAL_DENIED` | request ID, actor/ref | Changes approval gate state |
| `ENVIRONMENT_CHANGED` | sanitized patch, source | Applies versioned environment change |
| `ERROR_OCCURRED` | code, category, safe detail | Adds execution diagnostic |

## Belief version contract

```text
belief_id                 stable identity across versions
belief_version_id         immutable version identity
statement                 concise, inspectable proposition
confidence                decimal [0, 1]
status                    active | superseded | retracted
valid_from, valid_until   temporal validity interval
supporting_evidence_ids[]
contradicting_evidence_ids[]
source                    agent | tool | human | policy
supersedes_version_id     required for update
```

The `BELIEF_UPDATED` payload creates a new version; it does not modify the previous version. Contradicting evidence must be linked explicitly, permitting the belief evolution view to show exactly when confidence or status changed.

## Evidence contract

Evidence is an immutable provenance object. It may include sanitized inline content for small safe facts or a governed source reference for larger content.

```text
evidence_id, kind, title, summary, source_type, source_reference
observed_at, retrieved_at, content_hash, redaction_status
produced_by_event_id, tool_call_id?, observation_id?
```

`source_type` is one of `tool_output`, `api_response`, `retrieved_document`, `database_query`, `user_input`, `policy`, or `environment`. Source references must not contain credentials or raw sensitive data.

## Decision record contract

```text
decision_id, objective, selected_action, alternative_actions[]
decision_summary, confidence, evidence_ids[], belief_version_ids[]
policy_ids[], constraints[], risk_score, timestamp
```

`decision_summary` is a human-readable, concise rationale provided by the instrumented agent or application. It is not a hidden reasoning trace. A decision may be recorded without sufficient evidence; investigation must then report that limitation.

## Validity rules

- An event's ownership IDs must match its execution.
- `sequence_no` is assigned by the server and cannot be client supplied.
- Referenced IDs must be visible in the execution at or before the referring event unless declared as an external immutable source.
- Confidence and risk are decimals in `[0,1]`.
- Timestamps must be parseable UTC instants; configurable skew limits generate an audit warning, not a reordered event.
- Payload validation is event-type and schema-version specific.
- Redaction runs before hashing and persistence.

## Example lineage

```text
ACTION_COMPLETED(issue_refund)
  <- ACTION_STARTED(decision D-19)
       <- DECISION_CREATED(D-19, evidence E-payment-failed)
            <- BELIEF_UPDATED(payment failed, supports E-payment-failed)
                 <- EVIDENCE_RETRIEVED(E-payment-failed, webhook)
                      <- OBSERVATION_CREATED(late payment webhook)
```
