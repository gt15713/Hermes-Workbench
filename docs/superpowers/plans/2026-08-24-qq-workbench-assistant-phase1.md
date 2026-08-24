# QQ Workbench Assistant Phase 1 Implementation Plan

> **Status (2026-08-24): SHELVED / 封档搁置。** Workbench 侧命令解析、幂等状态机、健康证据与安全边界已经实现并通过测试；由于当前 Hermes 未提供发送者授权后的插件 Hook，QQ 命令不得接线启用。恢复条件是 Hermes 提供受支持的 post-auth dispatch 能力。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe QQ-to-Workbench phase-one integration without creating a second QQ connection or modifying Hermes core files.

**Architecture:** Hermes remains the sole transport and authorization boundary. The Workbench plugin records privacy-safe delivery evidence, uses official QQ message IDs for idempotent ingestion, and exposes a deterministic command contract that a separately authorized Hermes dispatch can invoke. Unsupported platform capabilities remain yellow until a real event proves them.

**Tech Stack:** Python 3.11+, pytest, FastAPI plugin endpoints, Hermes `pre_gateway_dispatch` hook, SQLite/FileRepo.

## Global Constraints

- Do not modify files under `hermes-agent` or Hermes credential/configuration files.
- Do not store or log AppSecret, AccessToken, OpenID, raw group messages, or attachment URLs.
- Do not execute Workbench mutation commands inside `pre_gateway_dispatch`, because that hook runs before Hermes authorization.
- Ordinary group-message support stays disabled/yellow until `GROUP_MESSAGE_CREATE` is observed end to end.
- Every behavior change follows red-green-refactor and preserves the existing plain-text fallback.

---

### Task 1: Official message identity and privacy-safe evidence

**Files:**
- Modify: `dashboard/inbound_hook.py`
- Modify: `dashboard/test_inbound_hook.py`

**Interfaces:**
- Consumes: `MessageEvent.message_id`, `MessageEvent.source.platform`.
- Produces: `build_ingest_body(text, event_message_id)` with an official-ID-first `message_id`; privacy-safe hook telemetry with no message content or identifiers.

- [ ] **Step 1: Write failing tests** proving two messages with the same title but different official IDs produce different ingest IDs, and fallback fingerprints remain stable when the adapter supplies no ID.
- [ ] **Step 2: Run** `python -m pytest dashboard/test_inbound_hook.py -q` and confirm the official-ID assertion fails.
- [ ] **Step 3: Implement** official-ID-first identity with a bounded, namespaced value and retain the current URL/title fallback.
- [ ] **Step 4: Run** the focused test and confirm it passes.

### Task 2: Evidence-based QQ capability health

**Files:**
- Modify: `dashboard/qq_health.py`
- Modify: `dashboard/test_qq_health.py`

**Interfaces:**
- Consumes: gateway state, privacy-safe gateway/plugin log shapes, installed adapter source.
- Produces: separate `group_at` and `full_group` verdicts; source support never upgrades runtime evidence to green.

- [ ] **Step 1: Write failing tests** for adapters that route only `GROUP_AT_MESSAGE_CREATE`, adapters that route both group event types, and future-dated/expired evidence.
- [ ] **Step 2: Run** `python -m pytest dashboard/test_qq_health.py -q` and confirm the new assertions fail.
- [ ] **Step 3: Implement** explicit route detection and event-evidence parsing without identifiers or message content.
- [ ] **Step 4: Run** focused tests and confirm they pass.

### Task 3: Authorized Workbench command contract

**Files:**
- Create: `dashboard/qq_commands.py`
- Create: `dashboard/test_qq_commands.py`
- Modify: `dashboard/plugin_api.py`
- Modify: `dashboard/test_plugin_api.py`

**Interfaces:**
- Consumes: normalized commands `帮助`, `今日`, `状态`, `任务 <内容>`, `完成 <唯一任务>`, `归档 <唯一任务>`, `延期 <唯一任务> <日期>` after Hermes authorization.
- Produces: `parse_qq_command(text) -> Command | None` and `POST /qq-command` returning a short pure-text reply; mutation requests require an idempotency key and ambiguity returns candidates without changing data.

- [ ] **Step 1: Write parser tests** for whitespace, Chinese aliases, missing arguments, unknown commands, and text that is not a command.
- [ ] **Step 2: Run** `python -m pytest dashboard/test_qq_commands.py -q` and confirm imports/behaviors fail.
- [ ] **Step 3: Implement** the immutable parser and pure-text formatter.
- [ ] **Step 4: Write endpoint tests** for read commands, idempotent task creation, ambiguous task mutation, and explicit archive behavior.
- [ ] **Step 5: Run** the endpoint tests and confirm they fail before adding the route.
- [ ] **Step 6: Implement** `/qq-command` by calling existing Workbench domain functions under `_WRITE_LOCK`; do not call QQ APIs or read credentials.
- [ ] **Step 7: Run** focused parser/API tests and confirm they pass.

### Task 4: Safe Hermes dispatch boundary

**Files:**
- Modify: `dashboard/inbound_hook.py`
- Modify: `dashboard/test_inbound_hook.py`
- Create: `docs/qq-workbench-command-wiring.md`

**Interfaces:**
- Consumes: authenticated Hermes dispatch or an upstream post-authorization hook.
- Produces: a documented handoff contract to `/qq-command`; `pre_gateway_dispatch` only detects/rewrites commands and never mutates Workbench state.

- [ ] **Step 1: Write failing tests** proving unauthorized/pre-auth hook execution cannot invoke a mutation.
- [ ] **Step 2: Implement** command detection as a rewrite/allow signal only; preserve normal Hermes authorization and response handling.
- [ ] **Step 3: Document** the exact upstream post-auth integration needed for deterministic replies, including official message ID and reply deadline.
- [ ] **Step 4: Run** hook tests and confirm safe behavior.

### Task 5: Release gates and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/release-gate.md`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: user-facing capability matrix and repeatable verification steps.

- [ ] **Step 1: Document** platform support, adapter support, runtime evidence, and Workbench support as separate states.
- [ ] **Step 2: Run** `python -m pytest dashboard -q`.
- [ ] **Step 3: Run** `npm test --prefix desktop-src` and `npm run build --prefix desktop-src` using repository scripts.
- [ ] **Step 4: Run** the privacy gate and `git diff --check`.
- [ ] **Step 5: Request** an independent code review and fix all critical/important findings before any GitHub push.
