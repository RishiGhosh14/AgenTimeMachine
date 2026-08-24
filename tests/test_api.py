import os, uuid
os.environ["DATABASE_URL"] = "sqlite:///./test_agent_time_machine.db"
from fastapi.testclient import TestClient
from apps.api.app.main import app

def test_events_state_and_investigation():
    client=TestClient(app); key=str(uuid.uuid4())
    created=client.post("/api/v1/executions",json={"organization_id":str(uuid.uuid4()),"project_id":str(uuid.uuid4()),"agent_id":str(uuid.uuid4()),"external_execution_key":key})
    execution=created.json()["id"]
    payloads=[("EXECUTION_STARTED",{"goal":"test"}),("EVIDENCE_RETRIEVED",{"evidence_id":"e","summary":"recorded fact"}),("DECISION_CREATED",{"decision_id":"d","objective":"test","selected_action":"CLOSE","decision_summary":"Recorded evidence supports close.","confidence":.8,"evidence_ids":["e"]})]
    for kind,payload in payloads:
        result=client.post("/api/v1/events",json={"execution_id":execution,"event_type":kind,"occurred_at":"2026-01-01T00:00:00Z","payload":payload})
        assert result.status_code==201
    events=client.get(f"/api/v1/executions/{execution}/timeline").json(); assert [x["sequence_no"] for x in events]==[1,2,3]
    state=client.get(f"/api/v1/executions/{execution}/state?event_id={events[-1]['event_id']}").json(); assert state["state"]["evidence"][0]["evidence_id"]=="e"
    why=client.post(f"/api/v1/executions/{execution}/investigations",json={"decision_id":"d"}).json(); assert why["conclusion"]=="established_from_record"
