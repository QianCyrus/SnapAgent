# Doctor Connector (Codex-Driven) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a slim `/doctor` connector that pauses the current session task, lets Codex decide which built-in diagnostics to run, and reports evidence-first diagnosis in chat.

**Architecture:** Keep SnapAgent as a thin control plane. `AgentLoop` handles `/doctor` lifecycle and session isolation, while Codex drives investigation by calling a new read-only diagnostic tool (`doctor_check`) for `health`, `status`, `logs`, and `events`. No OTel scope in this iteration.

**Tech Stack:** Python 3.11, Typer/CLI internals, AgentLoop + ToolRegistry, existing observability modules (`health`, `JsonlLoggingSink`), pytest.

---

## Task 1: Add doctor command lifecycle in AgentLoop

**Files:**
- Modify: `snapagent/agent/loop.py`
- Test: `tests/test_doctor_command.py`

**Step 1: Write failing tests for doctor commands**
- Add tests for:
  - `/doctor` starts doctor mode and cancels current session tasks.
  - `/doctor status` reports current doctor state.
  - `/doctor cancel` cancels doctor diagnostics for this session.
  - `/help` includes doctor commands.

**Step 2: Run tests to verify RED**
- Run: `pytest -q tests/test_doctor_command.py`
- Expected: FAIL due to missing `/doctor` behavior.

**Step 3: Implement minimal doctor lifecycle**
- In `run()`, route `/doctor...` to a dedicated handler (same priority level as `/stop`).
- Reuse existing cancellation logic so `/doctor` pauses current session work before diagnostics.
- Track per-session doctor task state in memory.
- Expose `/doctor`, `/doctor status`, `/doctor cancel`, `/doctor resume`.

**Step 4: Run tests to verify GREEN**
- Run: `pytest -q tests/test_doctor_command.py`
- Expected: PASS.

**Step 5: Commit**
- `git add snapagent/agent/loop.py tests/test_doctor_command.py`
- `git commit -m "feat(agent): add /doctor session lifecycle and command routing"`

## Task 2: Add read-only doctor diagnostics tool

**Files:**
- Create: `snapagent/agent/tools/doctor.py`
- Modify: `snapagent/agent/loop.py` (tool registration)
- Test: `tests/test_doctor_tool.py`

**Step 1: Write failing tests for tool behavior**
- Add tests for `doctor_check`:
  - `check=health` returns deep health snapshot payload.
  - `check=status` returns status payload with config/workspace context.
  - `check=logs` filters by session/run and respects line limits.
  - `check=events` returns timeline-oriented event rows.

**Step 2: Run tests to verify RED**
- Run: `pytest -q tests/test_doctor_tool.py`
- Expected: FAIL because tool does not exist.

**Step 3: Implement tool**
- Implement one tool with strict enum-based checks:
  - `health`
  - `status`
  - `logs`
  - `events`
- Reuse existing internals (no shell command spawning in tool body).
- Keep tool read-only and JSON output only.

**Step 4: Run tests to verify GREEN**
- Run: `pytest -q tests/test_doctor_tool.py`
- Expected: PASS.

**Step 5: Commit**
- `git add snapagent/agent/tools/doctor.py snapagent/agent/loop.py tests/test_doctor_tool.py`
- `git commit -m "feat(agent): add doctor_check observability tool"`

## Task 3: Wire doctor UX copy and channel help text

**Files:**
- Modify: `snapagent/agent/loop.py`
- Modify: `snapagent/channels/telegram.py`
- Test: `tests/test_plan_command.py` (or dedicated command text test)

**Step 1: Write failing assertions**
- Verify `/help` includes doctor command list in core loop response.
- Verify Telegram help output includes doctor commands.

**Step 2: Run tests to verify RED**
- Run targeted tests and confirm missing text assertions fail.

**Step 3: Implement minimal copy updates**
- Add doctor command lines to help output.
- Keep copy concise and platform-neutral.

**Step 4: Run tests to verify GREEN**
- Run targeted tests and confirm pass.

**Step 5: Commit**
- `git add snapagent/agent/loop.py snapagent/channels/telegram.py tests/...`
- `git commit -m "chore(help): document /doctor commands in chat help"`

## Task 4: Verification, PR, and independent review loop

**Files:**
- Modify PR description/checklist on GitHub

**Step 1: Run verification suite**
- Run:
  - `pytest -q tests/test_doctor_command.py tests/test_doctor_tool.py tests/test_task_cancel.py tests/test_plan_command.py tests/test_commands.py`
  - optional broader smoke: `pytest -q tests/test_health_surface.py tests/test_observability_logging_surface.py tests/test_observability_event_backbone.py`

**Step 2: Push and open PR**
- Push branch and create PR to `release`.

**Step 3: Spawn external review subagent**
- Ask subagent to review PR diff and post GitHub comments.

**Step 4: Apply feedback and iterate**
- Fix issues from subagent review.
- Spawn a fresh review subagent again.
- Repeat until no blocking findings remain.

## Explicit Non-Goals (M0)
- No OTel integration.
- No auto code rewrite/restart by doctor.
- No cross-platform button workflow.

## TODO (deferred by request)
- Add hard permission boundaries for doctor actions (tool allowlist policies, role-based authorization, high-risk confirmations).
