# Workbench runtime acceptance matrix

Recorded baseline: 2026-08-25 14:08 +08:00 (Asia/Shanghai)

Status meanings:

- `green`: source test, loaded build/runtime, and required visible or real-channel behavior are observed.
- `yellow`: implementation and automated tests pass, but a required real channel or visible UI probe is missing.
- `red`: a required behavior failed.

| Capability | Source tested | Bundle built | Runtime loaded | Real channel / visible UI observed | Status |
|---|---:|---:|---:|---:|---|
| `/wb` grammar and explicit mutation boundary | yes | n/a | QQ C2C command executed after update | QQ create receipt and durable write observed at 2026-08-25 14:12:10 +08:00 | green |
| Stable `WB-XXXXXXXX` identity and bounded source | yes | n/a | backend tests after update pass | exactly one `WB-AAD4D922`, `source: qq`, one created event | green |
| QQ-to-Weixin routing by task ID | yes, including one-task/two-ref regression | n/a | fixed module loaded after clean Gateway restart | one task with isolated QQ and Weixin refs observed | green |
| Conversation lifecycle sync across HTTP/background paths | yes, including transient SQLite lock retry | yes | fixed module loaded after clean Gateway restart | QQ-group completion archived one task and both QQ/Weixin refs are completed | green |
| Manual and automatic archive contract | yes | yes | user confirmed archived card opens | real QQ-group completion produced one archived entity with full history | green |
| Preview and run-history timeout | yes | yes, SHA-256 `ac5ea8c122b85ea08767f7bade4934dbec5d5e38301ed8c95dbe49dff0fbea6d` | user confirmed normal after reload | yes | green |
| Full history follows archive/reopen | yes | yes | user confirmed archived history is visible | yes | green |
| Original-conversation navigation/fallback | component tests pass | yes | loaded | real card `QQ · 微信` badge navigates to two completed platform rows; both truthfully expose summary fallback because no Hermes session ID is bound | green |
| Explainable Today briefing | backend evidence tests pass | yes | loaded | real Today view labels the section `规则建议`, states its deterministic basis, shows `暂无建议` for the current zero-rule dataset; cards expose `查看依据` when present | green |
| Board/Table/Today count agreement | count logic and regression tests pass | yes | loaded | real Board shows `0 Pending / 25 Total`, matching section counts `已处理 24 + 回收站 1`; current Table click was intentionally stopped when user activity was detected | yellow |
| Workbench Capture skill | inspected and boundary-consolidated with the two related Workbench skills | n/a | skill exists in active Hermes skill tree | real `/wb` create/continue/complete lifecycle passed; post-edit discovery log remains optional evidence | green |
| QQ C2C capture | automated boundary tests pass | n/a | Gateway QQ Ready | real create, cross-platform continuation and QQ-group completion lifecycle passed | green |
| Weixin DM capture | automated cross-platform test passes | n/a | Gateway Weixin connected with fixed module | real continuation, durable update, and Weixin ref observed | green |
| QQ ordinary group messages without mention | upstream boundary only | n/a | not supported by observed official delivery | no | yellow |
| Reviewed Obsidian sink | explicit intent classifier and capture/knowledge boundary tests exist; a separate reviewed/sunk state machine is not yet implemented | no | current task Markdown is durable, but knowledge ingestion remains delegated to `obsidian-zh-ingest` | no end-to-end reviewed knowledge-note probe | yellow |

## Baseline commands

- `python -m pytest dashboard -q` -> 418 passed, one Starlette/httpx deprecation warning.
- `npm test` -> 17 passed.
- `npm run typecheck` -> exit 0.
- `desktop/build-info.json` hash matches the actual `desktop/plugin.js` SHA-256.

## Next acceptance probe

1. **Passed:** QQ C2C created exactly one task with `/wb 任务 跨平台验收 2026-08-25`; receipt ID, Markdown frontmatter, SQLite task mirror, conversation reference, and one created event all agree on `WB-AAD4D922`.
2. **Passed after root fix and Gateway reload:** Weixin DM appended to `WB-AAD4D922`; one task now has isolated QQ and Weixin references.
3. **Passed:** QQ group mention completed and archived `WB-AAD4D922`; both platform references now carry `completed` after the transient-lock root fix.
4. **Passed visibly:** one archived entity, full history, QQ/Weixin completed rows, summary-fallback action, adaptive board, and task-card platform navigation were inspected in the loaded Hermes Desktop.

No channel is promoted to green from automated tests alone.
