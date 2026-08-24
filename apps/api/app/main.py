from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Any, Literal
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from apps.api.app.store import EventStore
from services.reconstruction.state import empty_state, public_state, replay, state_diff

store = EventStore(os.getenv("DATABASE_URL"))
app = FastAPI(title="Agent Time Machine", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
)
VALID_EVENTS = {"EXECUTION_STARTED","EXECUTION_COMPLETED","GOAL_CREATED","PLAN_CREATED","PLAN_UPDATED","OBSERVATION_CREATED","EVIDENCE_RETRIEVED","BELIEF_CREATED","BELIEF_UPDATED","BELIEF_RETRACTED","TOOL_DISCOVERED","TOOL_AUTHORIZED","TOOL_DENIED","TOOL_CALLED","TOOL_RESULT_RECEIVED","DECISION_CREATED","ACTION_STARTED","ACTION_COMPLETED","ACTION_FAILED","POLICY_EVALUATED","HUMAN_APPROVAL_REQUESTED","HUMAN_APPROVAL_GRANTED","HUMAN_APPROVAL_DENIED","ENVIRONMENT_CHANGED","ERROR_OCCURRED"}

class ExecutionIn(BaseModel): organization_id: str; project_id: str; agent_id: str; external_execution_key: str | None = None
class EventIn(BaseModel):
    execution_id: str; event_type: str; occurred_at: datetime; payload: dict[str, Any]; parent_event_id: str | None = None; correlation_id: str | None = None; metadata: dict[str, Any] = Field(default_factory=dict)
class InvestigationIn(BaseModel): action_id: str | None = None; decision_id: str | None = None
class CounterfactualIn(BaseModel): base_event_id: str; substitutions: list[dict[str, Any]]

def utc(v: datetime) -> str:
    if v.tzinfo is None: raise HTTPException(422, "occurred_at must include timezone")
    return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
def get_execution(execution_id: str) -> dict[str, Any]:
    value = store.execution(execution_id)
    if not value: raise HTTPException(404, "execution not found")
    return value
def reconstructed(execution_id: str, timestamp: str | None = None, event_id: str | None = None) -> tuple[dict[str, Any], int]:
    execution = get_execution(execution_id); sequence = store.selector(execution_id, timestamp, event_id)
    checkpoint = store.nearest_snapshot(execution_id, sequence)
    checkpoint_sequence, base = checkpoint if checkpoint else (0, None)
    state = replay(execution, store.events(execution_id, through_sequence=sequence, after_sequence=checkpoint_sequence), base)
    if sequence and sequence % 10 == 0 and not checkpoint: store.save_snapshot(execution_id, sequence, state)
    return state, sequence

@app.get("/health")
def health() -> dict[str,str]: return {"status":"ok"}
@app.post("/api/v1/executions", status_code=201)
def create_execution(body: ExecutionIn) -> dict[str, Any]: return store.create_execution(body.organization_id, body.project_id, body.agent_id, body.external_execution_key)
@app.get("/api/v1/executions/{execution_id}")
def read_execution(execution_id: str) -> dict[str, Any]: return get_execution(execution_id)
@app.post("/api/v1/events", status_code=201)
def append_event(body: EventIn, idempotency_key: str | None = Header(None, alias="Idempotency-Key")) -> dict[str, Any]:
    if body.event_type not in VALID_EVENTS: raise HTTPException(422, "unsupported event_type")
    try: return store.append(body.execution_id, body.event_type, utc(body.occurred_at), body.payload, parent_event_id=body.parent_event_id, correlation_id=body.correlation_id, idempotency_key=idempotency_key, metadata=body.metadata)
    except KeyError as e: raise HTTPException(404, str(e))
@app.get("/api/v1/executions/{execution_id}/timeline")
def timeline(execution_id: str) -> list[dict[str, Any]]: get_execution(execution_id); return store.events(execution_id)
@app.get("/api/v1/executions/{execution_id}/state")
def state_at(execution_id: str, timestamp: str | None = None, event_id: str | None = None) -> dict[str, Any]:
    if bool(timestamp) == bool(event_id): raise HTTPException(400, "provide exactly one of timestamp or event_id")
    try:
        state, sequence = reconstructed(execution_id, timestamp, event_id); checkpoint = store.nearest_snapshot(execution_id, sequence)
        return {"state": public_state(state), "reconstruction":{"checkpoint_sequence_no":checkpoint[0] if checkpoint else 0,"replayed_event_count":sequence-(checkpoint[0] if checkpoint else 0)}}
    except KeyError as e: raise HTTPException(404, str(e))
@app.get("/api/v1/executions/{execution_id}/diff")
def diff(execution_id: str, from_event_id: str, to_event_id: str) -> dict[str, Any]:
    before, _ = reconstructed(execution_id, event_id=from_event_id); after, _ = reconstructed(execution_id, event_id=to_event_id); return state_diff(public_state(before), public_state(after))
@app.post("/api/v1/executions/{execution_id}/replay")
def replay_route(execution_id: str, start_event_id: str | None = None, end_event_id: str | None = None) -> dict[str, Any]:
    execution = get_execution(execution_id); events = store.events(execution_id); start = next((x["sequence_no"] for x in events if x["event_id"] == start_event_id),1); end = next((x["sequence_no"] for x in events if x["event_id"] == end_event_id),len(events)); state = empty_state(execution); steps=[]
    for event in events:
        before = public_state(state); state = replay(execution,[event],state)
        if start <= event["sequence_no"] <= end: steps.append({"event":event,"state_before":before,"state_after":public_state(state)})
    return {"execution_id":execution_id,"steps":steps}
@app.post("/api/v1/executions/{execution_id}/investigations")
def investigate(execution_id: str, body: InvestigationIn) -> dict[str, Any]:
    if not body.action_id and not body.decision_id: raise HTTPException(422,"provide action_id or decision_id")
    state, _ = reconstructed(execution_id, event_id=store.events(execution_id)[-1]["event_id"]); decisions = state["decision_metadata"]
    decision = decisions.get(body.decision_id) if body.decision_id else next((a for a in state["completed_actions"].values() if a.get("action_id")==body.action_id),{}).get("decision_id")
    if isinstance(decision,str): decision = decisions.get(decision)
    if not decision: return {"conclusion":"insufficient_recorded_evidence","summary":"Insufficient recorded evidence to establish why this decision was made.","nodes":[],"edges":[]}
    nodes=[{"id":decision["decision_id"],"type":"decision","data":decision}]; edges=[]
    for eid in decision.get("evidence_ids",[]): nodes.append({"id":eid,"type":"evidence"}); edges.append({"from":decision["decision_id"],"to":eid,"type":"supported_by"})
    return {"conclusion":"established_from_record" if decision.get("evidence_ids") else "partial_record","summary":decision.get("decision_summary","Insufficient recorded evidence to establish why this decision was made."),"nodes":nodes,"edges":edges}
@app.post("/api/v1/executions/{execution_id}/counterfactuals", status_code=201)
def counterfactual(execution_id: str, body: CounterfactualIn) -> dict[str, Any]:
    original, _ = reconstructed(execution_id,event_id=body.base_event_id); simulated = public_state(original)
    for change in body.substitutions:
        if change.get("kind") == "environment": simulated["environment_snapshot"][change["key"]]=change.get("value")
        elif change.get("kind") == "tool_availability":
            for tool in simulated["available_tools"]:
                if tool.get("tool_id")==change.get("tool_id"): tool["authorized"]=change.get("enabled",False)
        elif change.get("kind") == "belief_confidence":
            for belief in simulated["beliefs"]:
                if belief.get("belief_version_id")==change.get("belief_version_id"): belief["confidence"]=change["value"]
    return {"classification":"SIMULATED / COUNTERFACTUAL","base_event_id":body.base_event_id,"substitutions":body.substitutions,"state":simulated}
