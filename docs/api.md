# API Contract

Base path: `/api/v1`. JSON requests and responses use UTC RFC 3339 timestamps and UUID identifiers. The initial API is REST because temporal inspection needs cacheable, explicit resource boundaries; live streaming can later add server-sent events without changing the core contract.

## Cross-cutting rules

- Authentication: `Authorization: Bearer <service-api-key>` for SDK ingestion or authenticated user session for dashboard calls.
- The server derives organization and permitted projects from authentication. Supplying foreign tenant IDs returns `404` rather than confirming their existence.
- Every write accepts `Idempotency-Key`; identical retries return the original accepted resource. Reuse with a different body returns `409`.
- Responses include `X-Correlation-ID`; clients may submit one for end-to-end tracing.
- Inputs are validated with Pydantic models, redacted before persistence, size-limited, and rate-limited.

## Core resources

| Method and path | Purpose | Request body / query | Success |
|---|---|---|---|
| `POST /executions` | Start an execution | `agent_id`, `external_execution_key`, `goal`, optional environment | `201 Execution` |
| `GET /executions/{id}` | Execution aggregate | — | `200 Execution` |
| `GET /executions/{id}/timeline` | Ordered events with filters | `from`, `to`, `types[]`, `cursor`, `limit` | `200 TimelinePage` |
| `POST /events` | Append one event | `execution_id`, `event_type`, `occurred_at`, payload, tracing metadata | `201 Event` |
| `POST /events:batch` | Atomically append validated event batch | ordered events, optional client batch ID | `201 Event[]` |
| `GET /events/{id}` | Read an event | — | `200 Event` |
| `GET /executions/{id}/state` | Historical reconstruction | exactly one of `timestamp`, `event_id`; `include=` | `200 ReconstructedState` |
| `GET /executions/{id}/diff` | Compare two reconstructed points | `from_timestamp|from_event_id`, `to_timestamp|to_event_id` | `200 StateDiff` |
| `GET /decisions/{id}` | Structured decision record | — | `200 Decision` |
| `GET /decisions/{id}/evidence` | Decision provenance graph | `depth` (bounded) | `200 EvidenceLineage` |
| `POST /executions/{id}/investigations` | Evidence-bounded “why” query | `action_id` or `decision_id` | `200 Investigation` |
| `POST /executions/{id}/replay` | Replay a bounded range | start/end selector, `include_states` | `200 Replay` |
| `POST /executions/{id}/counterfactuals` | Controlled non-persistent simulation | base selector, allowed substitutions | `201 CounterfactualRun` |

## Representative contracts

### Append event

```json
{
  "execution_id": "c0e73c2a-8f1d-4f3e-9083-030bb9f01ea5",
  "event_type": "DECISION_CREATED",
  "occurred_at": "2026-08-19T10:31:08Z",
  "parent_event_id": "8b0f8bd7-806f-42a8-9a23-2ab01e1fa0ce",
  "correlation_id": "56d9c188-362a-4e1a-9151-9773e685b0b4",
  "payload": {
    "decision_id": "60ee82c2-2e4c-42b3-9490-3a62b88e3e96",
    "objective": "Resolve customer ticket",
    "selected_action": "CLOSE_TICKET",
    "alternative_actions": ["REQUEST_MORE_INFORMATION", "ESCALATE"],
    "decision_summary": "Recorded payment and policy evidence indicated resolution.",
    "confidence": 0.74,
    "risk_score": 0.21,
    "evidence_ids": ["c5b1e5f6-96a0-4fa2-ac4d-a82c7dcb1631"],
    "belief_version_ids": ["e3a2234f-23c6-4587-9b3e-a7cf4c9a8a79"],
    "policy_ids": ["2e11d93f-c5ab-48df-bb4e-d407485f4027"],
    "constraints": ["ticket_close_requires_resolved_status"]
  }
}
```

The response adds server-owned fields, including `event_id`, `sequence_no`, `ingested_at`, `payload_sha256`, and redaction metadata. It does not alter submitted business facts.

### Reconstructed state

```json
{
  "execution_id": "c0e73c2a-8f1d-4f3e-9083-030bb9f01ea5",
  "as_of": {
    "event_id": "ee7a30a4-843b-4375-9da8-3e8e74bc5238",
    "sequence_no": 12,
    "occurred_at": "2026-08-19T10:31:08Z"
  },
  "state": {
    "goals": [], "active_plan": null, "beliefs": [], "evidence": [],
    "available_tools": [], "permissions": [], "pending_actions": [],
    "completed_actions": [], "decision_metadata": []
  },
  "reconstruction": { "checkpoint_sequence_no": 10, "replayed_event_count": 2 }
}
```

### Investigation

`POST /executions/{id}/investigations` returns an explicit directed graph of action, decision, belief, policy, evidence, observation, and source nodes. Its `conclusion` is one of `established_from_record`, `partial_record`, or `insufficient_recorded_evidence`. The explanatory text may summarize recorded metadata only and must cite the graph node IDs it relies on.

### Counterfactual

The request supports only typed substitutions:

```json
{
  "base_event_id": "ee7a30a4-843b-4375-9da8-3e8e74bc5238",
  "substitutions": [
    { "kind": "belief_confidence", "belief_version_id": "e3a2234f-23c6-4587-9b3e-a7cf4c9a8a79", "value": 0.35 },
    { "kind": "tool_availability", "tool_id": "b5eddbed-e4f1-4dac-9085-cfed63429487", "enabled": false }
  ]
}
```

The response always includes `classification: "SIMULATED / COUNTERFACTUAL"`, base execution/sequence, substitutions, derived state/diff, and limitations. It never records an asserted real-world outcome.

## Errors

All errors use one envelope:

```json
{
  "error": {
    "code": "EVENT_REFERENCE_NOT_VISIBLE",
    "message": "The referenced evidence is not visible at this execution point.",
    "details": [{ "field": "payload.evidence_ids[0]", "reason": "unknown_or_future_reference" }],
    "correlation_id": "56d9c188-362a-4e1a-9151-9773e685b0b4"
  }
}
```

Use `400` for invalid selector combinations, `401` for invalid authentication, `403` for known-but-forbidden administrative operations, `404` for non-visible resources, `409` for idempotency/conflict errors, `422` for model validation, and `429` for rate limiting. `500` responses never return stored payload data or secrets.
