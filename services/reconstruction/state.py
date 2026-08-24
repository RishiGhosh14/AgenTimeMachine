"""Deterministic, side-effect-free temporal state transition functions."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def empty_state(execution: dict[str, Any]) -> dict[str, Any]:
    return {
        "organization_id": execution["organization_id"], "project_id": execution["project_id"],
        "agent_id": execution["agent_id"], "execution_id": execution["id"], "execution_status": "running",
        "goals": [], "active_plan": None, "beliefs": {}, "evidence": {}, "observations": {},
        "available_tools": {}, "permissions": {}, "environment_snapshot": {}, "pending_actions": {},
        "completed_actions": {}, "decision_metadata": {}, "errors": [], "as_of": None,
    }


def _items(values: dict[str, Any]) -> list[dict[str, Any]]:
    return list(values.values())


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(state)
    for name in ("beliefs", "evidence", "observations", "available_tools", "permissions",
                 "pending_actions", "completed_actions", "decision_metadata"):
        result[name] = _items(result[name])
    return result


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Apply one validated event. This function must remain pure and deterministic."""
    next_state = deepcopy(state)
    payload = event["payload"]
    kind = event["event_type"]
    if kind == "EXECUTION_STARTED":
        next_state["execution_status"] = "running"
        if payload.get("goal"):
            next_state["goals"].append({"goal_id": payload.get("goal_id", "initial"), "statement": payload["goal"], "status": "active"})
        next_state["environment_snapshot"].update(payload.get("environment", {}))
    elif kind == "EXECUTION_COMPLETED":
        next_state["execution_status"] = payload.get("status", "completed")
    elif kind == "GOAL_CREATED":
        next_state["goals"].append({**payload, "status": payload.get("status", "active")})
    elif kind in {"PLAN_CREATED", "PLAN_UPDATED"}:
        next_state["active_plan"] = payload
    elif kind == "OBSERVATION_CREATED":
        next_state["observations"][payload["observation_id"]] = payload
    elif kind == "EVIDENCE_RETRIEVED":
        next_state["evidence"][payload["evidence_id"]] = payload
    elif kind in {"BELIEF_CREATED", "BELIEF_UPDATED"}:
        if kind == "BELIEF_UPDATED" and payload.get("supersedes_version_id"):
            for belief in next_state["beliefs"].values():
                if belief.get("belief_version_id") == payload["supersedes_version_id"]:
                    belief["status"] = "superseded"
                    belief["valid_until"] = event["occurred_at"]
        version_id = payload.get("belief_version_id", payload["belief_id"])
        next_state["beliefs"][version_id] = {**payload, "status": payload.get("status", "active"), "valid_from": payload.get("valid_from", event["occurred_at"])}
    elif kind == "BELIEF_RETRACTED":
        for belief in next_state["beliefs"].values():
            if belief.get("belief_id") == payload["belief_id"] and belief.get("status") == "active":
                belief["status"] = "retracted"; belief["valid_until"] = event["occurred_at"]
                belief["contradicting_evidence_ids"] = payload.get("contradicting_evidence_ids", [])
    elif kind == "TOOL_DISCOVERED":
        next_state["available_tools"][payload["tool_id"]] = {**payload, "authorized": False}
    elif kind in {"TOOL_AUTHORIZED", "TOOL_DENIED"}:
        tool = next_state["available_tools"].setdefault(payload["tool_id"], {"tool_id": payload["tool_id"]})
        tool["authorized"] = kind == "TOOL_AUTHORIZED"; tool["policy_id"] = payload.get("policy_id")
        next_state["permissions"][payload["tool_id"]] = {"tool_id": payload["tool_id"], "allowed": kind == "TOOL_AUTHORIZED"}
    elif kind == "TOOL_CALLED":
        next_state["pending_actions"][payload["tool_call_id"]] = {**payload, "status": "running"}
    elif kind == "TOOL_RESULT_RECEIVED":
        call = next_state["pending_actions"].pop(payload["tool_call_id"], {"tool_call_id": payload["tool_call_id"]})
        call.update({"status": "completed", "result_evidence_id": payload.get("evidence_id")})
        next_state["completed_actions"][payload["tool_call_id"]] = call
    elif kind == "DECISION_CREATED":
        next_state["decision_metadata"][payload["decision_id"]] = payload
    elif kind == "ACTION_STARTED":
        next_state["pending_actions"][payload["action_id"]] = {**payload, "status": "running"}
    elif kind in {"ACTION_COMPLETED", "ACTION_FAILED"}:
        action = next_state["pending_actions"].pop(payload["action_id"], {"action_id": payload["action_id"]})
        action.update(payload); action["status"] = "failed" if kind == "ACTION_FAILED" else "completed"
        next_state["completed_actions"][payload["action_id"]] = action
    elif kind == "ENVIRONMENT_CHANGED":
        next_state["environment_snapshot"].update(payload.get("patch", {}))
    elif kind == "ERROR_OCCURRED":
        next_state["errors"].append(payload)
    next_state["as_of"] = {k: event[k] for k in ("event_id", "sequence_no", "occurred_at")}
    return next_state


def replay(execution: dict[str, Any], events: list[dict[str, Any]], state: dict[str, Any] | None = None) -> dict[str, Any]:
    result = deepcopy(state) if state is not None else empty_state(execution)
    for event in events:
        result = apply_event(result, event)
    return result


def state_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """A compact, deterministic structural diff suitable for the UI."""
    changes: list[dict[str, Any]] = []
    def visit(path: str, left: Any, right: Any) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)): visit(f"{path}.{key}" if path else key, left.get(key), right.get(key))
        elif left != right:
            changes.append({"path": path, "before": left, "after": right, "kind": "added" if left is None else "removed" if right is None else "changed"})
    visit("", before, after)
    return {"changes": changes}
