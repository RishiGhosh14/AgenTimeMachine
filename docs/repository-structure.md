# Repository Structure

Phase 0 creates a documentation-first skeleton. Source directories remain intentionally empty until their corresponding implementation phase.

```text
agent-time-machine/
├── apps/
│   ├── api/                     # FastAPI service (Phase 1)
│   └── web/                     # Next.js dashboard (Phase 6)
├── packages/
│   └── sdk/                     # Python SDK (Phase 3)
├── agents/
│   └── support-agent/           # deterministic reference agent (Phase 3)
├── services/
│   ├── reconstruction/          # pure state transition/reconstruction (Phase 2)
│   ├── replay/                  # replay/counterfactual layer (Phase 5)
│   └── investigation/           # lineage and explanation layer (Phase 4)
├── database/
│   ├── migrations/              # migration files begin in Phase 1
│   └── seeds/                   # reproducible demo seed support
├── tests/                       # tests follow each vertical slice
├── docs/
│   ├── architecture.md
│   ├── event-model.md
│   ├── database-schema.md
│   ├── api.md
│   ├── repository-structure.md
│   └── evaluation.md
├── examples/                    # runnable SDK examples (Phase 3)
├── .github/workflows/           # CI begins with implementation
├── docker-compose.yml            # introduced with Phase 1 local stack
├── .env.example                 # introduced with Phase 1, no secrets
└── README.md
```

The backend owns persistence and authorization. The reconstruction package must be dependency-light and independently testable. The SDK must not import API internals. The web app consumes versioned REST contracts only. This separation keeps replay correctness testable without browser or database dependencies while keeping the event store transactional.
