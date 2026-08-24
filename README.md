# Agent Time Machine

> Temporal observability and debugging infrastructure for autonomous AI agents.

Agent Time Machine reconstructs what an agent observed, believed, was allowed to do, decided, and did at any historical point in an execution. It is an event-sourced debugger for agent behavior—not a chatbot, generic memory layer, or store of private reasoning.

## Phase 0 status

This repository contains a runnable MVP: immutable event ingestion, deterministic state reconstruction, investigation and replay APIs, a Python SDK, deterministic support-agent scenario, a time-travel dashboard, PostgreSQL migration, Docker files, and CI. The API uses SQLite by default for zero-setup local development; the supplied migration is the PostgreSQL production schema.

The implementation order is deliberately vertical:

## Run locally

```bash
python -m pip install -r requirements.txt
set PYTHONPATH=.
uvicorn apps.api.app.main:app --reload
```

In another terminal, run `python examples/support_agent.py`. It prints an execution ID. Start the dashboard with `cd apps/web && npm install && npm run dev`, paste that ID, and scrub its event timeline.

The local API is at `http://localhost:8000/docs`; the dashboard defaults to `http://localhost:3000`. Use `NEXT_PUBLIC_API_URL` to point the dashboard elsewhere.

## Security note

The production PostgreSQL schema provides tenant/RLS and API-key tables. This runnable local MVP accepts scope identifiers to keep the demo frictionless; before handling real tenant data, enable the production PostgreSQL adapter plus API-key and session enforcement as described in the architecture document.

## Design documents

- [Architecture](docs/architecture.md)
- [Event model](docs/event-model.md)
- [Database schema](docs/database-schema.md)
- [API contract](docs/api.md)
- [Repository plan](docs/repository-structure.md)
- [Evaluation plan](docs/evaluation.md)

## Product guardrails

- Events are immutable; corrections are new events.
- Historical state is derived by deterministic replay, never edited in place.
- Decision records contain concise, evidence-grounded summaries and metadata only—never hidden chain-of-thought.
- Every tenant-scoped record is isolated by organization and project.
- Counterfactual results are explicitly simulated and cannot alter the original execution.

## Target architecture

```text
External agent / Python SDK -> FastAPI ingestion -> PostgreSQL event store
                                                -> synchronous reconstruction
Next.js dashboard             -> FastAPI query -> projections + snapshots
Background worker (optional)  -> analytics / similarity indexing
```

See [docs/architecture.md](docs/architecture.md) for the full design and trade-offs.
