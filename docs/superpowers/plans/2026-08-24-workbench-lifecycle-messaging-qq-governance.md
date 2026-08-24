# Workbench Lifecycle, Messaging, and QQ Governance Plan

**Goal:** Eliminate recurrent lifecycle/UI inconsistencies, make Today suggestions explainable, suppress internal Hermes reset notices on Weixin through supported configuration, and define a safe QQ-to-Workbench assistant surface.

**Architecture:** Keep Hermes upstream code untouched. Normalize legacy lifecycle values at the Workbench boundary, return one consistent domain model to every view, add bounded UI requests with retry, and make Today advice rule-backed with visible evidence. Reuse Hermes' official QQ adapter as the only QQ connection; expose Workbench actions through a thin command layer with authorization and confirmation.

**Tech Stack:** Python 3.11+, pytest, TypeScript/React, Vitest, Hermes plugin SDK, YAML user configuration.

---

## Task 1: Normalize completed lifecycle states

**Files:**
- Modify: `dashboard/auto_archive.py`
- Modify: `dashboard/plugin_api.py`
- Modify: `desktop-src/execution.ts`
- Test: `dashboard/test_plugin_api.py`
- Test: `dashboard/test_session_watch_actions.py`
- Test: `desktop-src/execution.test.ts`

1. Add failing tests for `status: done` plus `execution_result: success` in automatic reconciliation, `/complete`, and `canArchiveTask`.
2. Introduce one canonical lifecycle predicate/normalizer covering `completed` and the legacy alias `done`.
3. Make automatic archive and manual archive use that shared rule.
4. Keep failed/abandoned/running tasks protected from accidental archive.
5. Run focused Python and TypeScript tests.

## Task 2: Remove ghost rows from Table mode

**Files:**
- Modify: `dashboard/plugin_api.py`
- Test: `dashboard/test_plugin_api.py`

1. Add a failing board-contract test proving an empty aggregation file contributes neither count nor file row.
2. Filter zero-entry aggregation files before returning `section.files` while leaving physical audit files untouched.
3. Verify Board and Table consume the same returned collection.

## Task 3: Make details and history fail visibly and recoverably

**Files:**
- Modify: `desktop-src/api.ts`
- Modify: `desktop-src/drawer.tsx`
- Test: add `desktop-src/api.test.ts` or the narrowest existing Vitest suite

1. Add a failing timeout test for a plugin call that never resolves.
2. Wrap detail/history reads in a bounded timeout with one safe retry.
3. Replace indefinite `加载中` with an actionable error and retry button.
4. Preserve current successful detail/history behavior and verify the desktop build.

## Task 4: Replace opaque Agent suggestions with evidence-backed advice

**Files:**
- Modify: `dashboard/plugin_api.py`
- Modify: `desktop-src/api.ts`
- Modify: `desktop-src/board.tsx`
- Test: `dashboard/test_brief.py`

1. Add failing tests requiring every suggestion to carry a rule identifier and human-readable evidence.
2. Derive overdue/blocked/review/lifecycle suggestions from exact task fields and counts.
3. Use the model only for optional wording, never as the source of truth; suppress unsupported speculative advice.
4. Render an `依据` area containing source task, status, date, or count.
5. Keep the 30-minute cache but version its schema so stale opaque cards are invalidated.

## Task 5: Stop Weixin reset banners safely

**Files:**
- Modify: `C:\Users\Kayura\AppData\Local\hermes\config.yaml` (supported user config only)
- Verify only: installed Hermes `gateway/config.py`, `gateway/run.py`, `gateway/platforms/weixin.py`

1. Preserve the existing reset schedule.
2. Add `weixin` to `session_reset.notify_exclude_platforms`; retain API/webhook exclusions.
3. Validate YAML and reload Hermes normally.
4. Confirm a reset no longer produces the internal banner on Weixin.
5. Keep normal Weixin 2000-character chunking; constrain Workbench/love-me report templates separately to avoid unnecessary splits.

## Task 6: Audit QQ configuration and design the Workbench bot surface

**Files:**
- Verify only: `C:\Users\Kayura\AppData\Local\hermes\config.yaml`, `.env`, installed QQ adapter/onboarding code
- Modify later only after explicit product approval: Workbench command module and tests

1. Audit credentials by presence only; never print IDs, secrets, OpenIDs, or channel IDs.
2. Verify enablement, DM/group policy, allowlists, gateway restart notice, streaming, and event coverage against official QQ documentation.
3. Keep one gateway connection through Hermes; do not create a second QQ client.
4. Define read commands: `/wb today`, `/wb list`, `/wb health`, `/wb history`.
5. Define write commands: `/wb add`, `/wb done`, `/wb archive`; require authorization, idempotency keys, and confirmation for mutations.
6. Keep ordinary group-message support conditional on QQ event subscription/platform capability; mention-only remains the safe default.

## Task 7: End-to-end recovery and release gate

**Files:**
- Modify as needed: README/changelog/release notes

1. Run all Python tests, TypeScript tests, and desktop build.
2. Restart/reload Workbench and verify Today, Board, Table, detail/history, and manual archive.
3. Run one lifecycle reconciliation and confirm the real completed card moves to `已处理` with an auditable event.
4. Re-run Workbench health and QQ configuration audit with secrets redacted.
5. Review the diff for accidental Hermes-source edits and sensitive data.
6. Commit Workbench changes locally; do not push GitHub or file upstream issues without explicit approval.
