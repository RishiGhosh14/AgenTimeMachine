"""Dependency-free instrumentation SDK for Agent Time Machine."""
from __future__ import annotations
import json, os, uuid
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from typing import Any

def iso_now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

class Tracker:
    def __init__(self, api_url: str = "http://localhost:8000", api_key: str | None = None, organization_id: str = "00000000-0000-0000-0000-000000000001", project_id: str = "00000000-0000-0000-0000-000000000002") -> None:
        self.api_url, self.api_key = api_url.rstrip("/"), api_key or os.getenv("AGENT_TIME_MACHINE_API_KEY")
        self.organization_id, self.project_id, self.execution_id = organization_id, project_id, None
    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers={"Content-Type":"application/json", "Idempotency-Key":str(uuid.uuid4())}
        if self.api_key: headers["Authorization"] = f"Bearer {self.api_key}"
        req=Request(f"{self.api_url}/api/v1{path}", data=json.dumps(payload).encode(), headers=headers, method=method)
        with urlopen(req, timeout=15) as response: return json.loads(response.read())
    def start_execution(self, agent_id: str, goal: str, external_execution_key: str | None = None) -> str:
        execution=self._request("POST","/executions",{"organization_id":self.organization_id,"project_id":self.project_id,"agent_id":agent_id,"external_execution_key":external_execution_key})
        self.execution_id=execution["id"]; self.event("EXECUTION_STARTED", {"goal":goal}); return self.execution_id
    def event(self, event_type: str, payload: dict[str, Any], occurred_at: str | None = None) -> dict[str, Any]:
        if not self.execution_id: raise RuntimeError("call start_execution first")
        return self._request("POST","/events",{"execution_id":self.execution_id,"event_type":event_type,"occurred_at":occurred_at or iso_now(),"payload":payload})
    def record_observation(self, observation_id: str, summary: str, **extra: Any) -> dict[str, Any]: return self.event("OBSERVATION_CREATED",{"observation_id":observation_id,"summary":summary,**extra})
    def record_evidence(self, evidence_id: str, summary: str, source_type: str, **extra: Any) -> dict[str, Any]: return self.event("EVIDENCE_RETRIEVED",{"evidence_id":evidence_id,"summary":summary,"source_type":source_type,**extra})
    def record_belief(self, belief_id: str, statement: str, confidence: float, evidence_ids: list[str], **extra: Any) -> dict[str, Any]: return self.event("BELIEF_CREATED",{"belief_id":belief_id,"belief_version_id":str(uuid.uuid4()),"statement":statement,"confidence":confidence,"supporting_evidence_ids":evidence_ids,**extra})
    def record_decision(self, decision_id: str, objective: str, selected_action: str, summary: str, confidence: float, evidence_ids: list[str], **extra: Any) -> dict[str, Any]: return self.event("DECISION_CREATED",{"decision_id":decision_id,"objective":objective,"selected_action":selected_action,"decision_summary":summary,"confidence":confidence,"evidence_ids":evidence_ids,**extra})
    def record_tool_call(self, tool_call_id: str, tool_id: str, input_summary: str) -> dict[str, Any]: return self.event("TOOL_CALLED",{"tool_call_id":tool_call_id,"tool_id":tool_id,"input_summary":input_summary})
    def end_execution(self, outcome: str, status: str = "completed") -> dict[str, Any]: return self.event("EXECUTION_COMPLETED",{"outcome":outcome,"status":status})
