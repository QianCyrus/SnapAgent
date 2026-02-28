# SnapAgent Observability + Doctor Architecture

## Goal

Build a lightweight but operable observability architecture so production issues can be diagnosed directly from chat channels (`/doctor`) without coupling diagnosis logic to core runtime internals.

## Design Principles

1. Thin connector, strong evidence.
2. Session-scoped control, no global pause.
3. Read-only diagnostics first, no risky auto-fix by default.
4. Separate deterministic data collection from model reasoning.

## Four Surfaces

### 1) Event Backbone (Track 0)

- Unified event model: `DiagnosticEvent`.
- Correlation fields: `session_key`, `run_id`, `turn_id`.
- Message bus emits structured inbound/outbound/runtime events.

Role:
- Foundation for cross-surface correlation and postmortem timeline reconstruction.

### 2) Health Surface (Track 1)

- CLI: `snapagent health --json`, `snapagent status --deep --json`.
- Aggregates provider/config/workspace/channel/runtime queue evidence.

Role:
- Fast readiness/liveness check and root-cause narrowing.

### 3) Logging Surface (Track 2)

- Structured JSONL sink (`diagnostic.jsonl`) with rotation/follow.
- CLI: `snapagent logs --json --session ... --run ... --follow`.

Role:
- Session/run-scoped evidence retrieval for operational debugging.

### 4) Doctor Surface (Codex-Driven)

- Chat commands:
  - `/doctor`
  - `/doctor status`
  - `/doctor cancel`
  - `/doctor resume`
- `/doctor` first pauses current session tasks (reuse stop/cancel path).
- Provider precheck before diagnostics:
  - if provider not ready, return setup guidance and block doctor mode.
  - guidance includes OAuth/API-key paths and validation command.
- Diagnostic execution is model-driven via read-only tool:
  - `doctor_check(check=health|status|logs|events, session_key?, run_id?, lines?)`

Role:
- Turn observability data into interactive diagnosis in user channels (Feishu/Telegram/CLI).

## End-to-End Flow

1. User sends `/doctor` in a chat session.
2. Agent cancels active tasks for this session only.
3. Agent runs provider precheck.
4. If precheck fails: return setup guidance and stop.
5. If precheck passes: enter doctor mode and start diagnostic turn.
6. Codex decides which `doctor_check` calls to run and synthesizes conclusions.
7. User can continue with follow-up questions, or `/doctor cancel`/`/doctor resume`.

## Safety Boundaries

- Session-local interruption only; other sessions/cron are unaffected by default.
- Diagnostics are read-only (`health/status/logs/events`).
- No automatic code mutation/restart in M0.

## Why This Shape

- Deterministic observability primitives stay in SnapAgent.
- Dynamic diagnosis stays in Codex reasoning layer.
- Keeps code volume low while preserving operational control and auditability.
