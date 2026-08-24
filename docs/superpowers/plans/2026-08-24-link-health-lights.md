# Link Health Lights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single red/yellow/green/disabled health verdict backed by explicit subsystem checks, expose it in Workbench, and include abnormal verdicts in daily reports without leaking scheduler metadata.

**Architecture:** The backend `/health` response is the source of truth and returns a stable `status`, `label`, and `checks` array. The React board renders the aggregate status as a compact control with expandable details. Daily report generation only adds a status line when the verdict is yellow or red.

**Tech Stack:** Python 3.11, FastAPI, pytest, React, TypeScript, Vitest, TanStack Query.

## Global Constraints

- Historical resolved errors must not keep the aggregate status red.
- A dropped delivery, dead scheduler, or unavailable database is red.
- Pending delivery or optional configuration gaps are yellow.
- Disabled checks are gray and do not make the aggregate unhealthy.
- Cron metadata, job ids, file paths, and management instructions must never appear in report messages.

---

### Task 1: Backend health verdict

**Files:** `dashboard/plugin_api.py`, `dashboard/test_plugin_api.py`

**Interfaces:** Produces `/health` fields `status: str`, `label: str`, `checks: list[dict]`.

- [x] Write failing tests for green, yellow pending-delivery, and red scheduler/database/error cases.
- [x] Run the focused tests and verify the assertions fail.
- [x] Implement the aggregate verdict and subsystem records.
- [x] Re-run the tests and verify they pass.

### Task 2: Workbench status control

**Files:** `desktop-src/api.ts`, `desktop-src/board.tsx`, generated `desktop/plugin.js`.

**Interfaces:** Consumes `WbHealth.status`, `WbHealth.label`, and `WbHealth.checks`.

- [x] Extend the API type with literal status values and check records.
- [x] Render the backend verdict and an expandable check panel.
- [x] Run the desktop build/typecheck and refresh the generated bundle.

### Task 3: Daily report abnormal status

**Files:** `dashboard/scheduler.py`, `dashboard/test_scheduler.py`

**Interfaces:** Produces a concise status line for yellow/red and an empty string for green.

- [x] Write a failing formatter test.
- [x] Implement the formatter and add its output to the daily report data.
- [x] Run Workbench backend tests, frontend build, and live `/health` verification.
