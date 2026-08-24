"""Deterministic customer-support scenario; run after `uvicorn apps.api.app.main:app --reload`."""
from __future__ import annotations
import os, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "sdk"))
from agent_time_machine import Tracker

def main() -> None:
    tracker=Tracker(api_url=os.getenv("AGENT_TIME_MACHINE_URL","http://localhost:8000"))
    execution=tracker.start_execution("00000000-0000-0000-0000-000000000003", "Determine whether refund should be issued", "refund-demo-001")
    tracker.event("PLAN_CREATED",{"plan_id":"refund-plan","steps":["get customer","get payment","check policy","resolve ticket"]})
    tracker.event("TOOL_DISCOVERED",{"tool_id":"get_payment","name":"get_payment"}); tracker.event("TOOL_AUTHORIZED",{"tool_id":"get_payment","policy_id":"refund-policy-v1"})
    tracker.record_observation("ticket-4821","Customer says payment may have failed",source="customer_ticket")
    tracker.record_tool_call("call-payment-1","get_payment","payment_id=pay_100")
    tracker.record_evidence("payment-api-182","Payment API initially reports succeeded","api_response",payment_status="succeeded")
    tracker.event("TOOL_RESULT_RECEIVED",{"tool_call_id":"call-payment-1","evidence_id":"payment-api-182"})
    belief=tracker.record_belief("payment-status","Payment appears successful",0.74,["payment-api-182"])["payload"]["belief_version_id"]
    tracker.record_decision("close-4821","Resolve customer ticket","CLOSE_TICKET","Recorded payment API evidence indicated the issue was resolved.",0.74,["payment-api-182"],belief_version_ids=[belief],risk_score=0.21)
    tracker.event("ACTION_STARTED",{"action_id":"close-ticket-4821","decision_id":"close-4821","action":"CLOSE_TICKET"}); tracker.event("ACTION_COMPLETED",{"action_id":"close-ticket-4821","outcome":"ticket closed"})
    tracker.record_observation("late-webhook","Late payment webhook reports transaction failure",source="payment_webhook")
    tracker.record_evidence("payment-webhook-211","Payment provider reports transaction failed","api_response",payment_status="failed")
    tracker.event("BELIEF_RETRACTED",{"belief_id":"payment-status","reason":"late webhook contradicts original payment result","contradicting_evidence_ids":["payment-webhook-211"]})
    tracker.end_execution("Ticket was closed before contradictory payment evidence arrived")
    print(f"Demo execution created: {execution}")
if __name__ == "__main__": main()
