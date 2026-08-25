# Multiplatform Private Capture and Task Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow authorized QQ and Weixin private chats to create, inspect, continue, and complete the same durable Workbench task without merging Hermes conversations.

**Architecture:** Hermes keeps its official per-chat session isolation. The Workbench plugin registers an authenticated gateway-wide `/wb` slash command, assigns every newly ingested task a deterministic public `task_id`, and resolves later commands by that ID or an unambiguous title. A user-level Hermes skill provides natural-language routing to the deterministic command/API boundary; no Hermes core files are changed.

**Tech Stack:** Python 3.11+, Hermes plugin API, pytest, Markdown task files, existing Workbench SQLite idempotency ledger.

## Global Constraints

- Do not remove or retire any existing Workbench feature.
- Do not modify Hermes core or updater-managed source.
- Preserve Hermes pairing and gateway authorization; mutation happens only after slash-command authorization or an authorized agent tool call.
- Capture is not execution.
- Never report success before the Workbench mutation succeeds.
- Keep QQ, QQ-group, and Weixin conversation histories isolated; share only durable task identity and state.

---

### Task 1: Cross-platform command grammar

**Files:**
- Modify: `dashboard/qq_commands.py`
- Modify: `dashboard/test_qq_commands.py`

**Interfaces:**
- Consumes: `/wb <verb> <argument>` or `工作台 <verb> <argument>`.
- Produces: `QQCommand(name, argument, extra, mutating, error)` for `add`, `review`, `verify`, `note`, `show`, `append`, `complete`, `archive`, `reopen`, and `defer`.

- [x] Write failing parser tests for the new verbs and required arguments.
- [x] Run `python -m pytest dashboard/test_qq_commands.py -q` and confirm the new cases fail because aliases are absent.
- [x] Add the minimal aliases and parsing branches.
- [x] Re-run the parser tests and confirm they pass.

### Task 2: Stable task identity and source metadata

**Files:**
- Modify: `dashboard/plugin_api.py`
- Modify: `dashboard/test_plugin_api.py`

**Interfaces:**
- Consumes: `ingest_message({message_id, platform, dir, title, content})`.
- Produces: `{ok, duplicate, file, dir, task_id}` and task frontmatter containing `task_id` plus a bounded `source` value.

- [x] Write failing API tests proving identical message IDs produce the same task ID, QQ and Weixin sources are preserved, and secrets/identifiers are not written as source values.
- [x] Run the focused tests and confirm failure because `task_id` and platform normalization are absent.
- [x] Implement `task_id_for_message(message_id)` using a deterministic SHA-256 prefix and normalize sources to `qq`, `weixin`, or `messaging`.
- [x] Return `task_id` from new and duplicate ingestion paths and run the focused tests green.

### Task 3: Task routing independent of Hermes sessions

**Files:**
- Modify: `dashboard/plugin_api.py`
- Modify: `dashboard/test_plugin_api.py`

**Interfaces:**
- Consumes: a public `WB-XXXXXXXX` ID or unambiguous task title.
- Produces: task status replies, appended execution notes, reopen transitions, and existing complete/archive behavior.

- [x] Write failing tests that create a task from QQ, inspect and append from Weixin using its task ID, then complete it from a second QQ invocation.
- [x] Confirm the tests fail because task-ID lookup and append/reopen handlers are absent.
- [x] Implement `_match_task_ref`, show, append, reopen, and task-ID-aware complete/archive resolution.
- [x] Run the cross-platform lifecycle tests green and then run all plugin API tests.

### Task 4: Authorized `/wb` plugin command

**Files:**
- Modify: `__init__.py`
- Create: `dashboard/messaging_command.py`
- Create: `dashboard/test_messaging_command.py`

**Interfaces:**
- Consumes: Hermes `ctx.register_command("wb", handler, ...)` and raw authorized slash-command arguments.
- Produces: one short plain-text Workbench receipt.

- [x] Write failing tests using a real temporary Workbench repository and a fake registration context; assert `/wb` registers and mutations receive deterministic invocation IDs.
- [x] Confirm failure because no command is registered.
- [x] Implement an async handler that delegates to `plugin_api.qq_command` with a deterministic `plugin-command:` message ID and `platform=messaging`.
- [x] Run registration/handler tests and the complete backend suite green.

### Task 5: Natural-language Workbench Capture Skill

**Files:**
- Create: `<HERMES_HOME>/skills/workbench-capture/SKILL.md`

**Interfaces:**
- Consumes: authorized QQ/Weixin requests that explicitly ask to register, review, verify, continue, complete, or archive Workbench work.
- Produces: deterministic `/wb` command use or existing Workbench script invocation; ordinary chat is not captured.

- [x] Write concise skill instructions defining capture signals, non-capture signals, task-ID continuation, and real-success receipts.
- [x] Validate frontmatter and ensure no scaffold placeholders remain.
- [ ] Confirm Hermes discovers the skill after gateway restart.

### Task 6: Runtime acceptance

**Files:**
- Modify: `README.md`
- Create: `docs/multiplatform-private-capture.md`

**Interfaces:**
- Consumes: QQ C2C and Weixin DM authorized gateway messages.
- Produces: documented operator checks and evidence-backed acceptance status.

- [x] Document `/wb` commands and the rule that Workbench task identity is shared while Hermes chat history is not.
- [x] Run `python -m pytest -q` and Ruff for modified Python files.
- [ ] Restart via `hermes gateway restart` and verify `hermes gateway status` plus plugin/skill discovery logs.
- [ ] Perform or request one real QQ and one real Weixin message test; mark only observed channels green.
