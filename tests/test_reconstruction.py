from services.reconstruction.state import empty_state, public_state, replay, state_diff

EXEC={"id":"x","organization_id":"o","project_id":"p","agent_id":"a"}
def event(n, kind, payload): return {"event_id":str(n),"sequence_no":n,"occurred_at":f"2026-01-01T00:00:0{n}Z","event_type":kind,"payload":payload}
def test_belief_retraction_preserves_history():
    events=[event(1,"BELIEF_CREATED",{"belief_id":"b","belief_version_id":"v1","statement":"payment succeeds","confidence":.74,"supporting_evidence_ids":["e1"]}),event(2,"BELIEF_RETRACTED",{"belief_id":"b","contradicting_evidence_ids":["e2"]})]
    result=public_state(replay(EXEC,events)); assert result["beliefs"][0]["status"] == "retracted"; assert result["beliefs"][0]["confidence"] == .74
def test_snapshot_plus_replay_matches_full_replay():
    events=[event(1,"EXECUTION_STARTED",{"goal":"resolve"}),event(2,"EVIDENCE_RETRIEVED",{"evidence_id":"e","summary":"fact"}),event(3,"BELIEF_CREATED",{"belief_id":"b","belief_version_id":"v","statement":"fact","confidence":.8})]
    full=replay(EXEC,events); checkpoint=replay(EXEC,events[:2]); resumed=replay(EXEC,events[2:],checkpoint); assert public_state(full)==public_state(resumed)
def test_diff_reports_changed_confidence():
    assert state_diff({"confidence":.7},{"confidence":.2})["changes"] == [{"path":"confidence","before":.7,"after":.2,"kind":"changed"}]
