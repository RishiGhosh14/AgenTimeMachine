# Evaluation Plan

No performance or quality metrics exist in Phase 0. This document defines how later phases will produce reproducible measurements rather than invented claims.

## Deterministic benchmark corpus

Create versioned fixtures for the support-agent scenario and focused edge cases:

- incomplete payment evidence followed by a contradictory late webhook;
- equal `occurred_at` events ordered by assigned sequence;
- retries using an idempotency key;
- belief update and retraction evolution;
- tool denial and human approval gates;
- snapshot boundary before and after target state;
- cross-tenant access attempts;
- counterfactual substitution with explicit simulated label.

Each fixture defines initial state, immutable ordered events, selected time/event selectors, expected canonical state, expected lineage edges, and expected diff. Expected results are hand-reviewed and checked into version control.

## Measurements

| Metric | Method | Reported value |
|---|---|---|
| Reconstruction correctness | Compare canonical expected state with full replay and snapshot+replay at every fixture selector | pass/fail and fixture count |
| Snapshot invariant | Compare canonical hashes from full and checkpoint replay | pass/fail; mismatches are failures |
| Evidence lineage accuracy | Compare investigation graph edges to expected fixture graph | precision/recall plus missed/extra edges |
| Replay fidelity | Compare replayed event IDs, order, and before/after state hashes | exact-match rate |
| Ingestion latency | Measure API elapsed time under documented local/CI load | p50/p95/p99 with environment |
| Reconstruction latency | Measure targets at varying event counts/checkpoint distances | p50/p95/p99 with fixture size |
| Storage efficiency | Compare bytes for all-event snapshots vs interval checkpoints plus events | actual byte counts |
| Security isolation | Run cross-organization API and RLS tests | pass/fail and coverage count |

Every benchmark run records Git commit, dataset version, machine/CI runner, PostgreSQL version/configuration, concurrency, warm/cold status, event counts, checkpoint interval, and raw samples. Published documentation links the raw result artifact. A failed invariant is never averaged away.

## Test layers by phase

1. Phase 1: API validation, immutability, ordering, idempotency, tenancy predicate tests.
2. Phase 2: pure transition unit tests, full-vs-snapshot property tests, ordering and malformed-reference tests.
3. Phase 3–5: SDK contract tests, deterministic demo integration tests, investigation/diff/replay/counterfactual fixtures.
4. Phase 6–9: browser journeys, RBAC/RLS integration, load tests, migration and backup-restore smoke tests.
