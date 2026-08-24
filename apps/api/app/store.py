"""Small transactional event store. SQLite is for local development; PostgreSQL is used in Docker."""
from __future__ import annotations

import hashlib, json, os, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS organizations (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, project_id TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS executions (id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, project_id TEXT NOT NULL, agent_id TEXT NOT NULL, external_key TEXT, status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT, next_sequence_no INTEGER NOT NULL DEFAULT 1, UNIQUE(agent_id, external_key));
CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, project_id TEXT NOT NULL, agent_id TEXT NOT NULL, execution_id TEXT NOT NULL, sequence_no INTEGER NOT NULL, event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, ingested_at TEXT NOT NULL, parent_event_id TEXT, correlation_id TEXT, idempotency_key TEXT, payload TEXT NOT NULL, metadata TEXT NOT NULL, payload_sha256 TEXT NOT NULL, UNIQUE(execution_id, sequence_no), UNIQUE(organization_id, idempotency_key));
CREATE INDEX IF NOT EXISTS idx_events_execution_time ON events(execution_id, occurred_at, sequence_no);
CREATE TABLE IF NOT EXISTS state_snapshots (id TEXT PRIMARY KEY, execution_id TEXT NOT NULL, last_sequence_no INTEGER NOT NULL, state_schema_version INTEGER NOT NULL DEFAULT 1, state_document TEXT NOT NULL, state_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(execution_id,last_sequence_no));
"""

def now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def canonical(value: Any) -> str: return json.dumps(value, sort_keys=True, separators=(",", ":"))
def digest(value: Any) -> str: return hashlib.sha256(canonical(value).encode()).hexdigest()

class EventStore:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("DATABASE_URL", "sqlite:///./agent_time_machine.db")
        self.postgres = self.url.startswith(("postgres://", "postgresql://"))
        if self.postgres:
            from psycopg import connect
            from psycopg.rows import dict_row
            self.conn = connect(self.url, row_factory=dict_row)
        else:
            path = self.url.removeprefix("sqlite:///")
            Path(path).parent.mkdir(parents=True, exist_ok=True) if Path(path).parent != Path(".") else None
            self.conn = sqlite3.connect(path, check_same_thread=False); self.conn.row_factory = sqlite3.Row
            self.conn.executescript(SCHEMA); self.conn.commit()

    def execute(self, sql: str, params: Any = None) -> Any:
        """Keep query text portable between local SQLite and production PostgreSQL."""
        if self.postgres: sql = sql.replace("?", "%s")
        return self.conn.execute(sql, params)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self.postgres:
            with self.conn.transaction(): yield self
        else:
            try:
                self.conn.execute("BEGIN IMMEDIATE"); yield self; self.conn.commit()
            except Exception: self.conn.rollback(); raise

    def seed_scope(self, organization_id: str, project_id: str, agent_id: str, agent_name: str = "support-agent") -> None:
        with self.transaction() as db:
            if self.postgres:
                db.execute("INSERT INTO organizations(id,name) VALUES (?,?) ON CONFLICT DO NOTHING", (organization_id, "Demo organization"))
                db.execute("INSERT INTO projects(id,organization_id,name) VALUES (?,?,?) ON CONFLICT DO NOTHING", (project_id, organization_id, "Demo project"))
                db.execute("INSERT INTO agents(id,organization_id,project_id,name) VALUES (?,?,?,?) ON CONFLICT DO NOTHING", (agent_id, organization_id, project_id, agent_name))
            else:
                db.execute("INSERT OR IGNORE INTO organizations VALUES (?,?)", (organization_id, "Demo organization"))
                db.execute("INSERT OR IGNORE INTO projects VALUES (?,?,?)", (project_id, organization_id, "Demo project"))
                db.execute("INSERT OR IGNORE INTO agents VALUES (?,?,?,?)", (agent_id, organization_id, project_id, agent_name))

    def create_execution(self, organization_id: str, project_id: str, agent_id: str, external_key: str | None = None) -> dict[str, Any]:
        self.seed_scope(organization_id, project_id, agent_id)
        result = {"id": str(uuid.uuid4()), "organization_id": organization_id, "project_id": project_id, "agent_id": agent_id, "external_key": external_key, "status": "running", "started_at": now(), "completed_at": None, "next_sequence_no": 1}
        with self.transaction() as db:
            db.execute("INSERT INTO executions(id,organization_id,project_id,agent_id,external_key,status,started_at,completed_at,next_sequence_no) VALUES (?,?,?,?,?,?,?,?,?)", tuple(result.values()))
        return result

    def execution(self, execution_id: str) -> dict[str, Any] | None:
        row = self.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone(); return dict(row) if row else None

    def append(self, execution_id: str, event_type: str, occurred_at: str, payload: dict[str, Any], *, parent_event_id: str | None = None, correlation_id: str | None = None, idempotency_key: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        metadata = metadata or {}
        with self.transaction() as db:
            execution = db.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone()
            if not execution: raise KeyError("execution not found")
            if idempotency_key:
                prior = db.execute("SELECT * FROM events WHERE organization_id=? AND idempotency_key=?", (execution["organization_id"], idempotency_key)).fetchone()
                if prior: return self._event(prior)
            seq = execution["next_sequence_no"]
            event = {"event_id": str(uuid.uuid4()), "organization_id": execution["organization_id"], "project_id": execution["project_id"], "agent_id": execution["agent_id"], "execution_id": execution_id, "sequence_no": seq, "event_type": event_type, "occurred_at": occurred_at, "ingested_at": now(), "parent_event_id": parent_event_id, "correlation_id": correlation_id, "idempotency_key": idempotency_key, "payload": payload, "metadata": metadata, "payload_sha256": digest(payload)}
            db.execute("INSERT INTO events VALUES (:event_id,:organization_id,:project_id,:agent_id,:execution_id,:sequence_no,:event_type,:occurred_at,:ingested_at,:parent_event_id,:correlation_id,:idempotency_key,:payload,:metadata,:payload_sha256)", {**event, "payload": canonical(payload), "metadata": canonical(metadata)})
            db.execute("UPDATE executions SET next_sequence_no=? WHERE id=?", (seq + 1, execution_id))
            if event_type == "EXECUTION_COMPLETED": db.execute("UPDATE executions SET status=?, completed_at=? WHERE id=?", (payload.get("status", "completed"), event["occurred_at"], execution_id))
            return event

    def _event(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row); value["payload"] = json.loads(value["payload"]); value["metadata"] = json.loads(value["metadata"]); return value
    def events(self, execution_id: str, *, through_sequence: int | None = None, after_sequence: int = 0) -> list[dict[str, Any]]:
        q = "SELECT * FROM events WHERE execution_id=? AND sequence_no>?"; args: list[Any] = [execution_id, after_sequence]
        if through_sequence is not None: q += " AND sequence_no<=?"; args.append(through_sequence)
        q += " ORDER BY occurred_at, sequence_no"; return [self._event(x) for x in self.execute(q, args).fetchall()]
    def selector(self, execution_id: str, timestamp: str | None, event_id: str | None) -> int:
        if event_id:
            row = self.execute("SELECT sequence_no FROM events WHERE execution_id=? AND event_id=?", (execution_id,event_id)).fetchone()
        else: row = self.execute("SELECT sequence_no FROM events WHERE execution_id=? AND occurred_at<=? ORDER BY occurred_at DESC, sequence_no DESC LIMIT 1", (execution_id,timestamp)).fetchone()
        if not row: raise KeyError("state selector does not resolve to an event")
        return row["sequence_no"]

    def nearest_snapshot(self, execution_id: str, target_sequence: int) -> tuple[int, dict[str, Any]] | None:
        row = self.execute("SELECT last_sequence_no,state_document FROM state_snapshots WHERE execution_id=? AND last_sequence_no<=? ORDER BY last_sequence_no DESC LIMIT 1", (execution_id,target_sequence)).fetchone()
        return (row["last_sequence_no"], json.loads(row["state_document"])) if row else None

    def save_snapshot(self, execution_id: str, sequence: int, state: dict[str, Any]) -> None:
        with self.transaction() as db:
            if self.postgres:
                db.execute("INSERT INTO state_snapshots(id,execution_id,last_sequence_no,state_schema_version,state_document,state_hash) VALUES (?,?,?,?,?::jsonb,?) ON CONFLICT (execution_id,last_sequence_no) DO NOTHING", (str(uuid.uuid4()),execution_id,sequence,1,canonical(state),digest(state)))
            else:
                db.execute("INSERT OR IGNORE INTO state_snapshots(id,execution_id,last_sequence_no,state_schema_version,state_document,state_hash,created_at) VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()),execution_id,sequence,1,canonical(state),digest(state),now()))
