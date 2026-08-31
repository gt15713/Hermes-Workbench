// desktop-src/workbench.css
var id = "hermes-plugin-style-workbench-view";
var node = document.getElementById(id);
if (!node) {
  node = document.createElement("style");
  node.id = id;
  document.head.appendChild(node);
}
node.textContent = `/* Workbench plugin styles */
.wb-root {
  font-size: 0.875rem;
  line-height: 1.55;
  /* P0（2026-08-27 目视二轮）：为面板内滑出抽屉提供定位上下文。
     没有它，drawer 的 absolute 会逃逸到宿主更大容器——预览/历史
     tab 因内容高度不同呈现"一个铺满一个缩条"。 */
  position: relative;
  overflow: hidden;
}

/* 用户拍板（2026-08-27 三轮复验后）：预览/运行历史两 tab 全幅覆盖——
   回到最初用户认可的"铺满会话消息区"形态。 */
.wb-drawer {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  width: 100%;
  background: var(--ui-bg-elevated);
  padding: 1.25rem;
  color: var(--ui-text-primary);
}

.wb-column {
  scrollbar-width: thin;
}

.wb-card {
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

/* Expanded columns keep a readable minimum but share spare width. Empty
   partitions compact to rails in the component unless the user overrides. */
.wb-section {
  flex: 1 0 16rem;
  min-width: 16rem;
  max-width: 28rem;
}

/* 2026-08-22 弹窗尺寸修复：宿主 Tailwind 无 w-[min(52rem,94vw)] 规则
   （已核验 dist CSS），此前弹窗落回 SDK 默认 max-w-lg(32rem) 小窗。
   宽度写在本文件，构建时内联注入，100% 生效。 */
.wb-dialog {
  width: min(52rem, 94vw);
  max-width: 94vw;
}

/* Compact rails keep inactive partitions visible without competing with the
   Bots sidebar or the right-docked Cronjobs pane. */
.wb-section--collapsed {
  min-width: 2rem;
  max-width: 2rem;
  background-color: color-mix(in srgb, var(--ui-bg-quinary) 78%, var(--ui-bg));
  border: 1px solid color-mix(in srgb, var(--ui-stroke-secondary) 82%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ui-bg) 18%, transparent);
}

/* Action menus are viewport overlays; the explicit z-index also clears the
   Cronjobs pane's right-docked surface. */
.wb-menu-overlay {
  position: fixed;
  z-index: 10020;
}

/* Health details use the same opaque elevated surface as Workbench cards and
   menus. Explicit plugin-owned styles avoid unsupported host utility tokens
   such as bg-(--ui-bg-primary), which previously fell through to transparency. */
.wb-health-popover {
  background-color: var(--ui-bg-elevated);
  border: 1px solid var(--ui-stroke-secondary);
  box-shadow: 0 12px 32px color-mix(in srgb, var(--ui-bg) 68%, transparent);
  backdrop-filter: none;
  opacity: 1;
}

/* Pending badge pulse */
@keyframes wb-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.wb-pending-badge {
  animation: wb-pulse 2s ease-in-out infinite;
}
`;

// desktop-src/plugin.tsx
import {
  cn as cn5,
  Codicon as Codicon5,
  host as host5,
  KEYBINDS_AREA,
  PALETTE_AREA,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  STATUSBAR_AREAS,
  Tip as Tip2,
  useQuery as useQuery4
} from "@hermes/plugin-sdk";

// desktop-src/api.ts
import { atom, queryClient } from "@hermes/plugin-sdk";
var rest = null;
var $collapsedSections = atom({});
var $filterText = atom("");
var $tagFilter = atom("");
var $showArchived = atom(false);
var $dueFilter = atom("all");
var $viewMode = atom("board");
var COLLAPSED_KEY = "wbCollapsedSections.v2";
var SHOW_ARCHIVED_KEY = "wbShowArchived";
var VIEW_MODE_KEY = "wbViewMode";
var TAG_FILTER_KEY = "wbTagFilter";
var DUE_FILTER_KEY = "wbDueFilter";
function bindApi(r, storage, socket) {
  rest = r;
  const unsubs = [];
  const persist = (atom2, key, fallback) => {
    atom2.set(storage.get(key, fallback));
    unsubs.push(atom2.listen((value) => storage.set(key, value)));
  };
  persist($collapsedSections, COLLAPSED_KEY, {});
  persist($showArchived, SHOW_ARCHIVED_KEY, false);
  persist($viewMode, VIEW_MODE_KEY, "board");
  persist($tagFilter, TAG_FILTER_KEY, "");
  persist($dueFilter, DUE_FILTER_KEY, "all");
  if ($viewMode.get() === "list") $viewMode.set("board");
  const closeSocket = socket("/events?since=0", (data) => onEventsFrame(data));
  unsubs.push(closeSocket);
  return () => {
    unsubs.forEach((u) => u());
    rest = null;
  };
}
function onEventsFrame(data) {
  const events = data?.events;
  if (!events?.length) {
    return;
  }
  void queryClient.invalidateQueries({ queryKey: BOARD_KEY });
  void queryClient.invalidateQueries({ queryKey: ["workbench", "events"] });
}
function call(path, opts) {
  return rest ? rest(path, opts) : Promise.reject(new Error("workbench api not ready"));
}
var BOARD_KEY = ["workbench", "board"];
var FILE_KEY = (dir, file) => ["workbench", "file", dir, file];
var RECENT_EVENTS_KEY = (dir, file) => ["workbench", "events", dir, file];
var CONTENT_ITEM_KEY = (dir, file) => ["workbench", "content-item", dir, file];
var fetchBoard = () => call("/board");
var fetchConversations = () => call("/conversations");
var fetchFile = (dir, file) => call(
  `/file?dirname=${encodeURIComponent(dir)}&filename=${encodeURIComponent(file)}`,
  { timeoutMs: 15e3 }
);
var fetchContentItem = (dir, file) => call(
  `/content/item?dir=${encodeURIComponent(dir)}&file=${encodeURIComponent(file)}`
);
var fetchRecentEvents = (dir, file) => call(
  `/recent?limit=50&dir=${encodeURIComponent(dir)}&file=${encodeURIComponent(file)}`,
  { timeoutMs: 15e3 }
);
var fetchSearch = (q, tag = "") => call(
  `/search?limit=20&q=${encodeURIComponent(q)}${tag ? `&tag=${encodeURIComponent(tag)}` : ""}`
);
var fetchBrief = () => call("/brief", { method: "POST", body: {} });
var fetchSettings = () => call("/settings");
var fetchHealth = () => call("/health");
var saveSettings = (body) => call("/settings", {
  method: "POST",
  body
});
var ingestMessage = (message_id, dir, title, opts) => call("/ingest-message", {
  method: "POST",
  body: { message_id, dir, title, ...opts }
});
var reviewContent = (dir, file, action) => call("/content/review", {
  method: "POST",
  body: { dir, file, action }
});
var retryExtraction = (dir, file) => call("/content/retry-extraction", {
  method: "POST",
  body: { dir, file }
});
var completeTask = (dir, file) => call("/complete", {
  method: "POST",
  body: { dir, file }
});
var resolveEntry = (dir, file, opts) => call("/resolve", {
  method: "POST",
  body: { dir, file, ...opts }
});
var toTask = (dir, file, opts) => call("/to-task", {
  method: "POST",
  body: { dir, file, ...opts }
});
var deferTask = (dir, file) => call("/defer", {
  method: "POST",
  body: { dir, file }
});
var executeTask = (dir, file, opts) => call("/execute", {
  method: "POST",
  body: { dir, file, source: "click", ...opts }
});
var abandonTask = (dir, file) => call("/abandon", {
  method: "POST",
  body: { dir, file }
});
var reopenTask = (dir, file) => call("/reopen", {
  method: "POST",
  body: { dir, file }
});
var trashFile = (dir, file) => call("/trash", {
  method: "POST",
  body: { dir, file }
});
var deleteFile = (dir, file) => call("/delete", {
  method: "POST",
  body: { dir, file }
});
var restoreFile = (dir, file) => call("/restore", {
  method: "POST",
  body: { file }
});
var bindSession = (dir, file, sessionId) => call("/bind-session", {
  method: "POST",
  body: { dir, file, session_id: sessionId }
});
var resetExecution = (dir, file, reason) => call("/reset-execution", {
  method: "POST",
  body: { dir, file, reason }
});
var addEntry = (body) => call("/add", {
  method: "POST",
  body
});
var invalidateBoard = () => void queryClient.invalidateQueries({ queryKey: BOARD_KEY });
var editEntry = (body) => call("/edit", {
  method: "POST",
  body
});
var batchAction = (action, items) => call("/batch", {
  method: "POST",
  body: { action, items }
});
var undoBatchTrash = (receipt) => call("/batch/undo", {
  method: "POST",
  body: receipt
});

// desktop-src/board.tsx
import {
  Button as Button2,
  cn as cn4,
  Codicon as Codicon4,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  host as host4,
  Input,
  useMutation as useMutation2,
  useQuery as useQuery3,
  useValue as useValue2
} from "@hermes/plugin-sdk";
import { Component, useCallback, useEffect as useEffect3, useMemo as useMemo3, useRef as useRef3, useState as useState4 } from "react";

// desktop-src/types.ts
var PARTITION_META = {
  thought: { label: "待验证", codicon: "inbox", tone: "var(--ui-text-tertiary)" },
  video: { label: "待回看", codicon: "eye", tone: "#60a5fa" },
  task: { label: "任务", codicon: "checklist", tone: "#a78bfa" },
  psych: { label: "心理学", codicon: "lightbulb", tone: "#34d399" },
  dream: { label: "梦中邮件", codicon: "mail", tone: "#fbbf24" },
  done: { label: "已处理", codicon: "pass", tone: "var(--ui-text-tertiary)" },
  trash: { label: "回收站", codicon: "trash", tone: "#f87171" }
};
var partitionMeta = (key) => PARTITION_META[key] ?? { label: key, codicon: "circle-outline", tone: "var(--ui-text-secondary)" };
var STATUS_TONE = {
  pending: "#fbbf24",
  todo: "#60a5fa",
  in_progress: "#34d399",
  completed: "var(--ui-text-tertiary)",
  abandoned: "#f87171",
  cleared: "var(--ui-text-quaternary)"
};
var PRIORITY_META = {
  P0: { label: "P0", bg: "rgba(248,113,113,0.16)", fg: "#f87171" },
  P1: { label: "P1", bg: "rgba(251,146,60,0.16)", fg: "#fb923c" },
  P2: { label: "P2", bg: "rgba(96,165,250,0.16)", fg: "#60a5fa" },
  P3: { label: "P3", bg: "rgba(148,163,184,0.16)", fg: "#94a3b8" }
};
var priorityMeta = (p) => PRIORITY_META[p] ?? null;
var SIZE_META = {
  S: { label: "S", fg: "#34d399" },
  M: { label: "M", fg: "#a78bfa" },
  L: { label: "L", fg: "#fbbf24" }
};
var sizeMeta = (s) => SIZE_META[s] ?? null;
var isOverdue = (due) => {
  if (!due || !/^\d{4}-\d{2}-\d{2}$/.test(due)) return false;
  const now = /* @__PURE__ */ new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  return due < today;
};

// desktop-src/execution.ts
function canArchiveTask(sectionKey, status, executionResult) {
  if (sectionKey !== "task") return false;
  if (status === "todo" || status === "completed") return true;
  if (status === "done") return executionResult === "success";
  return status === "in_progress" && executionResult === "success";
}
function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}
function taskPrompt(input, currentPath, scope) {
  const detail = input.content ? `
任务详情：${input.content}` : "";
  const scopeLine = scope === "research" ? "\n\n任务范围：research —— 默认不写 Obsidian，先给结论（可吃进形态：结论+素材结构化）；完成后询问是否需要吃进，明确同意才写入" : "";
  return `执行任务：「${input.title}」
任务文件：${currentPath}${detail}${scopeLine}

纪律（任务完成≠会话结束）：
1. 完成并验证后 → 任务文件 frontmatter 写 execution_result: success
2. 无法完成 → execution_result: failure + 正文追加「## 执行失败记录」说明原因
3. 未完成/被中断 → 保持 execution_result: pending，禁止虚假成功`;
}
async function rollback(deps, input, file, phase, path, error) {
  const reason = `${phase} 失败：${errorMessage(error)}`;
  let rollbackError;
  try {
    const result = await deps.rollback(input.dir, file, reason);
    if (!result.ok) {
      rollbackError = result.error || "恢复待办失败";
    }
  } catch (rollbackFailure) {
    rollbackError = errorMessage(rollbackFailure);
  }
  return {
    ok: false,
    phase,
    file,
    path,
    error: reason,
    ...rollbackError ? { rollbackError } : {}
  };
}
async function launchWorkbenchTask(input, deps) {
  let prepared;
  try {
    prepared = await deps.prepare(input);
  } catch (error) {
    return {
      ok: false,
      phase: "prepare",
      file: input.file,
      path: input.path,
      error: errorMessage(error)
    };
  }
  if (!prepared.ok) {
    return {
      ok: false,
      phase: "prepare",
      file: prepared.file || input.file,
      path: prepared.path || input.path,
      error: prepared.error || "任务准备失败"
    };
  }
  const file = prepared.file || input.file;
  const path = prepared.path || input.path;
  const scope = prepared.scope || "research";
  const cwd = prepared.cwd;
  let session;
  try {
    session = await deps.createSession({
      source: "workbench",
      title: `工作台｜${input.title}`,
      cwd
    });
  } catch (error) {
    return rollback(deps, input, file, "session.create", path, error);
  }
  const runtimeId = session.session_id;
  const storedId = session.stored_session_id || runtimeId;
  if (!runtimeId || !storedId) {
    return rollback(deps, input, file, "session.create", path, "会话返回缺少标识");
  }
  try {
    const bound = await deps.bind(input.dir, file, storedId);
    if (!bound.ok) {
      return rollback(deps, input, file, "bind-session", path, bound.error || "绑定被拒绝");
    }
  } catch (error) {
    return rollback(deps, input, file, "bind-session", path, error);
  }
  try {
    await deps.submit(runtimeId, taskPrompt(input, path, scope));
  } catch (error) {
    return rollback(deps, input, file, "prompt.submit", path, error);
  }
  return {
    ok: true,
    phase: "running",
    file,
    path,
    storedSessionId: storedId
  };
}

// desktop-src/tag-suggest.ts
function tagName(tag) {
  let n = tag.startsWith("#project:") ? tag.slice("#project:".length) : tag;
  if (n.startsWith("#")) n = n.slice(1);
  return n.trim();
}
function suggestTags(title, content, knownTags) {
  const hay = `${title}
${content}`.toLowerCase();
  const titleLower = title.toLowerCase();
  const high = [];
  const low = [];
  const seen = /* @__PURE__ */ new Set();
  for (const tag of knownTags) {
    const name = tagName(tag);
    if (name.length < 2) continue;
    if (seen.has(name)) continue;
    seen.add(name);
    if (!hay.includes(name.toLowerCase())) continue;
    const inTitle = titleLower.includes(name.toLowerCase());
    if (name.length >= 3 || inTitle) high.push(tag);
    else low.push(tag);
  }
  return { tags: high.slice(0, 5), low: low.slice(0, 3) };
}

// desktop-src/drawer.tsx
import { Button, cn, host, useMutation, useQuery } from "@hermes/plugin-sdk";
import { useState } from "react";

// desktop-src/api-errors.ts
var RULES = [
  {
    // 抽取钩子未注入：本会话后端没有配置抓取器（预期行为，非故障）
    test: /extraction hook unavailable/i,
    text: "这条内容目前无法自动抓取正文——本会话还没有配置抓取器。可以先「仅归档」保留原文，或重启桌面端后由 Agent 链路补抓。"
  },
  {
    // 后端还没有这个路由 = 插件前后端版本代差，需要整端重启让 Python 侧重挂
    test: /\b(40[45])\b|Method Not Allowed|Not Found/i,
    text: "后端还没有这条功能入口（本次会话的后端早于最新构建）。重启一次 Hermes 桌面端就会生效；数据不受影响。"
  },
  {
    test: /Failed to fetch|NetworkError|ERR_NETWORK|ECONNREFUSED|fetch failed/i,
    text: "连不上工作台后端——请确认 Hermes 正在运行，稍后重试。"
  },
  {
    test: /\b(40[13])\b|Unauthorized|Forbidden|permission/i,
    text: "后端拒绝了这次操作（权限或登录态问题）。稍后重试，若持续出现请反馈。"
  },
  {
    test: /\b50[0-4]\b|Internal Server Error|timeout|timed out/i,
    text: "后端处理时出错了。请稍后重试；反复出现请带上这条提示反馈。"
  }
];
function friendlyApiError(error) {
  const raw = error instanceof Error ? error.message : String(error ?? "");
  if (!raw) return "操作失败了，请稍后重试";
  const looksInternal = /Error invoking remote method|TypeError|Error:\s*\d{3}|^\d{3}:\s|^[A-Z_]{6,}$|\bE_[A-Z]+\b|^[a-z_]+(\s[a-z_]+)*$/.test(raw);
  if (!looksInternal) return raw;
  for (const rule of RULES) {
    if (rule.test.test(raw)) return rule.text;
  }
  return "操作没有成功。请稍后重试；若再次出现，请截图这条提示反馈。";
}

// desktop-src/content-review.ts
function contentReceiptSteps(item) {
  const source = item.original_url || "消息正文收录";
  const steps = [
    { label: "收进来", state: "done", detail: `${source}` }
  ];
  if (item.extraction_state === "failed") {
    steps.push({ label: "审核", state: "error", detail: `抽取失败：${item.last_error || "原因未知"}（可重试抽取）` });
  } else if (item.review_state === "pending") {
    steps.push({
      label: "审核",
      state: "active",
      detail: item.extraction_state === "pending" ? "抽取未完成——原文尚未就绪，可重试抽取" : "原文与来源已就绪"
    });
  } else {
    steps.push({ label: "审核", state: "done", detail: "已审核并作出决定" });
  }
  switch (item.review_state) {
    case "sunk":
      steps.push({ label: "沉淀", state: "done", detail: `笔记：${item.note_path || ""}` });
      break;
    case "archived":
      steps.push({ label: "沉淀", state: "skipped", detail: "仅归档——你选择不进知识库" });
      break;
    case "sink_queued":
      steps.push({ label: "沉淀", state: "active", detail: `已创建摄入任务 ${item.sink_task_id || ""}，等 Hermes 回执` });
      break;
    case "sink_failed":
      steps.push({ label: "沉淀", state: "error", detail: `沉淀失败：${item.last_error || "原因未知"}（可重试）` });
      break;
    default:
      steps.push({ label: "沉淀", state: "todo", detail: "等你审核后决定：仅归档 或 沉淀到 Obsidian" });
  }
  return steps;
}
function contentReviewModel(item) {
  const extractionFailed = item.extraction_state === "failed";
  if (item.review_state === "sunk") {
    return {
      statusText: extractionFailed ? "已沉淀（抽取历史有失败记录）" : "已沉淀到 Obsidian",
      notePath: item.note_path || null,
      error: null,
      actions: []
    };
  }
  if (item.review_state === "archived") {
    return { statusText: "已归档", notePath: null, error: null, actions: [] };
  }
  const actions = [];
  if (extractionFailed) {
    actions.push({ id: "retry_extraction", label: "重试抽取" });
  }
  if (item.review_state === "sink_queued") {
    return {
      statusText: "等待 Hermes 摄入",
      notePath: null,
      error: null,
      actions: [...actions, { id: "launch_sink_task", label: "启动 / 重试 Hermes 摄入" }]
    };
  }
  let statusText = item.review_state === "sink_failed" ? "沉淀失败，可重试" : "待审核";
  if (extractionFailed && !statusText.includes("抽取失败")) {
    statusText = `抽取失败 · ${statusText}`;
  }
  actions.push(
    { id: "archive_only", label: "仅归档" },
    { id: "sink_to_obsidian", label: item.review_state === "sink_failed" ? "重试沉淀" : "沉淀到 Obsidian" }
  );
  return {
    statusText,
    notePath: null,
    error: item.last_error || null,
    actions
  };
}
function launchQueuedContentItem(item, deps) {
  if (item.review_state !== "sink_queued" || !item.sink_task_dir || !item.sink_task_file || !item.sink_task_path) {
    return Promise.resolve({
      ok: false,
      phase: "prepare",
      file: item.sink_task_file || "",
      path: item.sink_task_path || "",
      error: "摄入任务回执不完整"
    });
  }
  return launchWorkbenchTask({
    dir: item.sink_task_dir,
    file: item.sink_task_file,
    title: `摄入：${item.title}`,
    path: item.sink_task_path
  }, deps);
}

// desktop-src/drawer.tsx
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
var contentExecutionDeps = {
  prepare: (input) => executeTask(input.dir, input.file, { launch: false }),
  createSession: (input) => host.request("session.create", input),
  bind: bindSession,
  submit: (sessionId, text) => host.request("prompt.submit", { session_id: sessionId, text }),
  rollback: (dir, file, reason) => resetExecution(dir, file, reason)
};
function stripFrontmatter(content) {
  return content.replace(/---\r?\n[\s\S]*?\r?\n---\r?\n?/g, "");
}
function extractEntry(content, focusTitle) {
  const lines = content.split("\n");
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim();
    if (t.startsWith("## ") && t.slice(3).trim() === focusTitle.trim()) {
      start = i;
      break;
    }
  }
  if (start === -1) return content;
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].trim().startsWith("## ")) {
      end = i;
      break;
    }
  }
  return lines.slice(start, end).join("\n");
}
function PreviewBody({ content, focusTitle }) {
  let text = stripFrontmatter(content);
  if (focusTitle) text = extractEntry(text, focusTitle);
  const lines = text.split("\n");
  return /* @__PURE__ */ jsx(Fragment, { children: lines.map((line, i) => {
    const trimmed = line.trim();
    const isFocus = !!focusTitle && trimmed.startsWith("## ") && trimmed.slice(3).trim() === focusTitle.trim();
    return /* @__PURE__ */ jsxs(
      "span",
      {
        className: isFocus ? "rounded bg-(--ui-accent)/15 font-semibold" : void 0,
        children: [
          line,
          i < lines.length - 1 ? "\n" : ""
        ]
      },
      i
    );
  }) });
}
function WbPreviewDrawer({
  card,
  onClose
}) {
  const [tab, setTab] = useState("preview");
  const [pendingSinkConfirm, setPendingSinkConfirm] = useState(false);
  const isReviewedContent = card.dir === "待验证" && card.file.startsWith("content-") && !card.entry_title;
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: FILE_KEY(card.dir, card.file),
    queryFn: () => fetchFile(card.dir, card.file),
    enabled: true,
    retry: 1
  });
  const { data: events, isLoading: evLoading, error: evError, refetch: refetchEvents } = useQuery({
    queryKey: RECENT_EVENTS_KEY(card.dir, card.file),
    queryFn: () => fetchRecentEvents(card.dir, card.file),
    enabled: tab === "history",
    retry: 1
  });
  const { data: contentResponse, refetch: refetchContent } = useQuery({
    queryKey: CONTENT_ITEM_KEY(card.dir, card.file),
    queryFn: () => fetchContentItem(card.dir, card.file),
    enabled: isReviewedContent,
    retry: 1
  });
  const contentItem = contentResponse?.ok ? contentResponse.item : void 0;
  const reviewModel = contentItem ? contentReviewModel(contentItem) : null;
  const reviewMutation = useMutation({
    mutationFn: (action) => reviewContent(contentItem.dir, contentItem.file, action),
    onSuccess: async (result) => {
      if (!result.ok) {
        host.notify({ kind: "error", message: result.error || "操作失败，可重试" });
        await refetchContent();
        return;
      }
      if (result.item?.review_state === "sink_queued") {
        const launched = await launchQueuedContentItem(result.item, contentExecutionDeps);
        if (!launched.ok) {
          host.notify({ kind: "error", message: launched.error || "摄入任务启动失败；任务已保留，可重试" });
          invalidateBoard();
          await refetchContent();
          return;
        }
        host.notify({ kind: "success", message: "已交给 Hermes 摄入；完成后自动回写笔记路径" });
        invalidateBoard();
        await refetchContent();
        return;
      }
      host.notify({ kind: "success", message: result.item?.review_state === "sunk" ? "已沉淀到 Obsidian" : "已归档" });
      invalidateBoard();
      await refetchContent();
    },
    onError: (error2) => host.notify({ kind: "error", message: friendlyApiError(error2) })
  });
  const queuedLaunchMutation = useMutation({
    mutationFn: () => launchQueuedContentItem(contentItem, contentExecutionDeps),
    onSuccess: async (launched) => {
      host.notify(launched.ok ? { kind: "success", message: "Hermes 摄入任务已启动；完成后自动回写笔记路径" } : { kind: "error", message: launched.error || "摄入任务启动失败；可再次重试" });
      invalidateBoard();
      await refetchContent();
    },
    onError: (error2) => host.notify({ kind: "error", message: friendlyApiError(error2) })
  });
  const retryExtractionMutation = useMutation({
    mutationFn: () => retryExtraction(contentItem.dir, contentItem.file),
    onSuccess: async (result) => {
      if (!result.ok) {
        host.notify({ kind: "error", message: friendlyApiError(result.error || "抽取失败，可稍后重试") });
        await refetchContent();
        return;
      }
      host.notify({ kind: "success", message: "抽取完成，原文已更新" });
      await refetchContent();
    },
    onError: (error2) => host.notify({ kind: "error", message: friendlyApiError(error2) })
  });
  const tabBtn = (active) => cn(
    "cursor-pointer rounded px-2 py-1 text-[0.8125rem] transition-colors",
    active ? "bg-(--ui-accent)/15 text-(--ui-accent)" : "text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary)"
  );
  return (
    // P0（2026-08-27 目视二轮）：视口级 fixed 居中弹窗会被宿主右栏原生
    // 表面遮挡（z-index 无法越过），且宽度压迫工作台。改为官方 kanban
    // 同款「面板内右侧滑出抽屉」：锚定在最近 positioned 祖先（Workbench
    // 面板）上，与右栏物理隔离，宽度固定不挤压内容。
    /* @__PURE__ */ jsxs(
      "div",
      {
        className: "wb-drawer",
        role: "dialog",
        "aria-modal": "false",
        "aria-label": "文件预览",
        children: [
          /* @__PURE__ */ jsxs("div", { className: "mb-3 flex items-center justify-between", children: [
            /* @__PURE__ */ jsx("span", { className: "text-base font-semibold", children: card.title || card.file }),
            /* @__PURE__ */ jsx(
              "button",
              {
                type: "button",
                "aria-label": "关闭",
                className: "cursor-pointer border-none bg-transparent text-base text-(--ui-text-tertiary) hover:text-(--ui-text-primary)",
                onClick: onClose,
                children: "✕"
              }
            )
          ] }),
          /* @__PURE__ */ jsxs("div", { className: "mb-2 flex items-center gap-1 border-b border-(--ui-stroke-secondary) pb-1", children: [
            /* @__PURE__ */ jsx("button", { type: "button", className: tabBtn(tab === "preview"), onClick: () => setTab("preview"), children: "预览" }),
            /* @__PURE__ */ jsx("button", { type: "button", className: tabBtn(tab === "history"), onClick: () => setTab("history"), children: "运行历史" }),
            /* @__PURE__ */ jsx("div", { className: "ml-auto" })
          ] }),
          tab === "preview" ? /* @__PURE__ */ jsxs("div", { className: "flex-1 overflow-y-auto text-[0.75rem] leading-relaxed", children: [
            reviewModel && contentItem && /* @__PURE__ */ jsxs("section", { className: "mb-3 rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3", children: [
              /* @__PURE__ */ jsxs("div", { className: "font-medium", children: [
                "内容审核 · ",
                reviewModel.statusText
              ] }),
              /* @__PURE__ */ jsx("ol", { className: "mt-2 space-y-1", children: contentReceiptSteps(contentItem).map((step) => /* @__PURE__ */ jsxs("li", { className: "flex items-start gap-2 text-[0.75rem]", children: [
                /* @__PURE__ */ jsx(
                  "span",
                  {
                    style: {
                      flexShrink: 0,
                      color: step.state === "error" ? "var(--ui-red)" : step.state === "done" ? "var(--ui-green, var(--ui-text-quaternary))" : step.state === "active" ? "var(--ui-accent)" : "var(--ui-text-tertiary)"
                    },
                    children: step.state === "error" ? "✖" : step.state === "done" ? "✔" : step.state === "active" ? "▶" : step.state === "skipped" ? "⊘" : "○"
                  }
                ),
                /* @__PURE__ */ jsx("span", { className: "shrink-0 font-medium text-(--ui-text-primary)", children: step.label }),
                /* @__PURE__ */ jsx(
                  "span",
                  {
                    className: "min-w-0 break-all",
                    style: step.state === "error" ? { color: "var(--ui-red)", fontWeight: 500 } : void 0,
                    children: step.detail
                  }
                )
              ] }, step.label)) }),
              contentItem.original_url && /* @__PURE__ */ jsxs("div", { className: "mt-1 break-all text-(--ui-text-tertiary)", children: [
                "来源：",
                contentItem.original_url
              ] }),
              reviewModel.error && /* @__PURE__ */ jsx("div", { className: "mt-1 text-(--ui-red)", children: reviewModel.error }),
              reviewModel.notePath && /* @__PURE__ */ jsxs("div", { className: "mt-1 break-all text-(--ui-text-secondary)", children: [
                "笔记：",
                reviewModel.notePath
              ] }),
              reviewModel.actions.length > 0 && /* @__PURE__ */ jsx("div", { className: "mt-3 flex gap-2", children: pendingSinkConfirm ? (
                // P0：自绘确认条——明确两键，替代被吞的 window.confirm
                /* @__PURE__ */ jsxs("div", { className: "flex w-full items-center gap-2 rounded-md border border-(--ui-accent)/40 bg-(--ui-accent)/10 px-2 py-1.5", children: [
                  /* @__PURE__ */ jsx("span", { className: "text-[0.75rem] text-(--ui-text-primary)", children: "确认沉淀到 Obsidian？" }),
                  /* @__PURE__ */ jsx(
                    Button,
                    {
                      size: "xs",
                      disabled: reviewMutation.isPending,
                      onClick: () => {
                        setPendingSinkConfirm(false);
                        reviewMutation.mutate("sink_to_obsidian");
                      },
                      children: "确认沉淀"
                    }
                  ),
                  /* @__PURE__ */ jsx(Button, { size: "xs", variant: "outline", onClick: () => setPendingSinkConfirm(false), children: "取消" })
                ] })
              ) : reviewModel.actions.map((action) => /* @__PURE__ */ jsx(
                Button,
                {
                  size: "xs",
                  variant: action.id === "archive_only" ? "outline" : action.id === "retry_extraction" ? "secondary" : "secondary",
                  disabled: reviewMutation.isPending || queuedLaunchMutation.isPending || retryExtractionMutation.isPending,
                  onClick: () => {
                    if (action.id === "launch_sink_task") {
                      queuedLaunchMutation.mutate();
                      return;
                    }
                    if (action.id === "retry_extraction") {
                      retryExtractionMutation.mutate();
                      return;
                    }
                    if (action.id === "sink_to_obsidian") {
                      setPendingSinkConfirm(true);
                      return;
                    }
                    reviewMutation.mutate(action.id);
                  },
                  children: action.label
                },
                action.id
              )) })
            ] }),
            /* @__PURE__ */ jsxs("div", { className: "whitespace-pre-wrap", children: [
              isLoading && /* @__PURE__ */ jsx("div", { className: "flex h-full items-center justify-center text-(--ui-text-tertiary)", children: "加载中…" }),
              error && /* @__PURE__ */ jsxs("div", { className: "flex h-full flex-col items-center justify-center gap-2 text-(--ui-red)", children: [
                /* @__PURE__ */ jsx("span", { children: String(error.message || "加载失败") }),
                /* @__PURE__ */ jsx(Button, { size: "sm", variant: "secondary", onClick: () => void refetch(), children: "重试" })
              ] }),
              data && /* @__PURE__ */ jsx(PreviewBody, { content: data.content || "（空）", focusTitle: card.entry_title || null })
            ] })
          ] }) : /* @__PURE__ */ jsxs("div", { className: "flex-1 overflow-y-auto text-[0.8125rem]", children: [
            evLoading && /* @__PURE__ */ jsx("div", { className: "flex h-full items-center justify-center text-(--ui-text-tertiary)", children: "加载中…" }),
            evError && /* @__PURE__ */ jsxs("div", { className: "flex h-full flex-col items-center justify-center gap-2 text-(--ui-red)", children: [
              /* @__PURE__ */ jsx("span", { children: String(evError.message || "运行历史加载失败") }),
              /* @__PURE__ */ jsx(Button, { size: "sm", variant: "secondary", onClick: () => void refetchEvents(), children: "重试" })
            ] }),
            !evLoading && !evError && (!events || events.entries.length === 0) && /* @__PURE__ */ jsx("div", { className: "flex h-full items-center justify-center text-(--ui-text-quaternary)", children: "暂无运行历史" }),
            !evLoading && !evError && events && events.entries.length > 0 && /* @__PURE__ */ jsx("ul", { className: "flex flex-col gap-1", children: events.entries.map((e) => /* @__PURE__ */ jsxs(
              "li",
              {
                className: "flex items-center gap-2 rounded border border-(--ui-stroke-tertiary) px-2 py-1.5",
                children: [
                  /* @__PURE__ */ jsx("span", { className: "shrink-0 font-mono text-[0.75rem] text-(--ui-text-quaternary)", children: String(e.ts).slice(0, 19) }),
                  /* @__PURE__ */ jsx("span", { className: "shrink-0 rounded bg-(--ui-accent)/10 px-1.5 py-0.5 font-medium text-(--ui-accent)", children: e.kind }),
                  e.payload && /* @__PURE__ */ jsx("span", { className: "min-w-0 flex-1 truncate text-(--ui-text-secondary)", children: e.payload })
                ]
              },
              e.id
            )) })
          ] }),
          /* @__PURE__ */ jsxs("div", { className: "mt-3 flex items-center justify-end gap-2", children: [
            /* @__PURE__ */ jsx(Button, { size: "xs", variant: "outline", onClick: onClose, children: "关闭" }),
            /* @__PURE__ */ jsx(
              Button,
              {
                size: "xs",
                onClick: async () => {
                  try {
                    await navigator.clipboard.writeText(card.path);
                    host.notify({ kind: "success", message: "路径已复制" });
                  } catch {
                    host.notify({ kind: "error", message: "复制失败" });
                  }
                },
                children: "复制路径"
              }
            )
          ] })
        ]
      }
    )
  );
}

// desktop-src/views.tsx
import { cn as cn2, Codicon, useValue } from "@hermes/plugin-sdk";
import { Fragment as Fragment2, useMemo } from "react";
import { jsx as jsx2, jsxs as jsxs2 } from "react/jsx-runtime";
var fmtTime = (mtime) => {
  if (!mtime) return "—";
  if (typeof mtime === "string") return mtime;
  const d = new Date(mtime * 1e3);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
function PriorityBadge({ value }) {
  const meta = value ? priorityMeta(value) : null;
  if (!meta) return null;
  return /* @__PURE__ */ jsx2("span", { className: "rounded px-1 text-[0.75rem] font-semibold", style: { background: meta.bg, color: meta.fg }, children: meta.label });
}
function SizeBadge({ value }) {
  const meta = value ? sizeMeta(value) : null;
  if (!meta) return null;
  return /* @__PURE__ */ jsx2("span", { className: "rounded border px-1 text-[0.75rem] font-semibold", style: { borderColor: meta.fg, color: meta.fg }, children: meta.label });
}
function StatusCell({ status }) {
  const tone = STATUS_TONE[status] || "var(--ui-text-tertiary)";
  return /* @__PURE__ */ jsxs2("span", { className: "inline-flex items-center gap-1.5", children: [
    /* @__PURE__ */ jsx2("span", { className: "size-1.5 shrink-0 rounded-full", style: { background: tone } }),
    /* @__PURE__ */ jsx2("span", { className: "text-(--ui-text-secondary)", children: status })
  ] });
}
function useVisibleSections(board) {
  const filterText = useValue($filterText).toLowerCase();
  const collapsed = useValue($collapsedSections);
  const showArchived = useValue($showArchived);
  return useMemo(() => {
    const out = [];
    for (const section of board.sections) {
      if (!showArchived && (section.key === "done" || section.key === "trash")) continue;
      if (collapsed[section.key]) continue;
      const files = filterText ? section.files.filter(
        (c) => c.title.toLowerCase().includes(filterText) || c.file.toLowerCase().includes(filterText)
      ) : section.files;
      if (files.length > 0) out.push({ ...section, files });
    }
    return out;
  }, [board.sections, filterText, collapsed, showArchived]);
}
function TableBoardView({ board, onPreview }) {
  const sections = useVisibleSections(board);
  const rows = useMemo(() => {
    const out = [];
    for (const section of sections) {
      for (const card of section.files) out.push({ section, card });
    }
    return out;
  }, [sections]);
  const projectOf = (card) => {
    const t = (card.tags || []).find((tag) => tag.startsWith("#project:"));
    return t ? t.slice("#project:".length).trim() : "";
  };
  const collapsedProj = useValue($collapsedSections);
  const groups = useMemo(() => {
    const map = /* @__PURE__ */ new Map();
    for (const row of rows) {
      const name = projectOf(row.card) || "未分组";
      const arr = map.get(name);
      if (arr) arr.push(row);
      else map.set(name, [row]);
    }
    return Array.from(map.entries()).sort((a, b) => {
      if (a[0] === "未分组") return 1;
      if (b[0] === "未分组") return -1;
      return a[0].localeCompare(b[0]);
    });
  }, [rows]);
  const toggleGroup = (name) => {
    const key = "project:" + name;
    const cur = $collapsedSections.get();
    $collapsedSections.set({ ...cur, [key]: !(cur[key] ?? false) });
  };
  if (rows.length === 0) {
    return /* @__PURE__ */ jsx2("div", { className: "flex flex-1 items-center justify-center text-[0.8125rem] text-(--ui-text-quaternary)", children: "暂无条目" });
  }
  return /* @__PURE__ */ jsx2("div", { className: "flex-1 overflow-auto px-3 pb-3", children: /* @__PURE__ */ jsxs2("table", { className: "w-full border-collapse text-[0.8125rem]", children: [
    /* @__PURE__ */ jsx2("thead", { children: /* @__PURE__ */ jsxs2("tr", { className: "sticky top-0 bg-(--ui-bg) text-left text-(--ui-text-tertiary)", children: [
      /* @__PURE__ */ jsx2("th", { className: "px-2 py-1.5 font-medium", children: "分区" }),
      /* @__PURE__ */ jsx2("th", { className: "px-2 py-1.5 font-medium", children: "标题" }),
      /* @__PURE__ */ jsx2("th", { className: "px-2 py-1.5 font-medium", children: "状态" }),
      /* @__PURE__ */ jsx2("th", { className: "px-2 py-1.5 font-medium", children: "优先级" }),
      /* @__PURE__ */ jsx2("th", { className: "px-2 py-1.5 font-medium", children: "尺寸" }),
      /* @__PURE__ */ jsx2("th", { className: "px-2 py-1.5 font-medium", children: "标签" }),
      /* @__PURE__ */ jsx2("th", { className: "px-2 py-1.5 font-medium", children: "Due" }),
      /* @__PURE__ */ jsx2("th", { className: "px-2 py-1.5 font-medium", children: "更新时间" })
    ] }) }),
    /* @__PURE__ */ jsx2("tbody", { children: groups.map(([name, groupRows]) => {
      const key = "project:" + name;
      const collapsed = collapsedProj[key] ?? false;
      return /* @__PURE__ */ jsxs2(Fragment2, { children: [
        /* @__PURE__ */ jsx2(
          "tr",
          {
            className: "cursor-pointer border-t border-(--ui-stroke-secondary) bg-(--ui-bg-quinary)/50 hover:bg-(--ui-bg-quinary)",
            onClick: () => toggleGroup(name),
            children: /* @__PURE__ */ jsx2("td", { colSpan: 7, className: "px-2 py-1.5", children: /* @__PURE__ */ jsxs2("span", { className: "inline-flex items-center gap-1.5 font-semibold text-(--ui-text-secondary)", children: [
              /* @__PURE__ */ jsx2(Codicon, { name: collapsed ? "chevron-right" : "chevron-down", size: "0.7rem" }),
              name === "未分组" ? /* @__PURE__ */ jsx2("span", { className: "text-(--ui-text-quaternary)", children: "未分组" }) : /* @__PURE__ */ jsxs2("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 py-0.5 text-(--ui-accent)", children: [
                "#project:",
                name
              ] }),
              /* @__PURE__ */ jsx2("span", { className: "text-[0.75rem] font-normal text-(--ui-text-quaternary)", children: groupRows.length })
            ] }) })
          }
        ),
        !collapsed && groupRows.map(({ section, card }) => {
          const meta = partitionMeta(section.key);
          return /* @__PURE__ */ jsxs2(
            "tr",
            {
              className: "cursor-pointer border-t border-(--ui-stroke-tertiary) transition-colors hover:bg-(--ui-bg-quinary)",
              onClick: () => onPreview(card),
              children: [
                /* @__PURE__ */ jsxs2("td", { className: "px-2 py-1.5 whitespace-nowrap text-(--ui-text-secondary)", children: [
                  /* @__PURE__ */ jsx2(Codicon, { name: meta.codicon, size: "0.7rem", style: { color: meta.tone } }),
                  /* @__PURE__ */ jsx2("span", { className: "ml-1.5", children: meta.label })
                ] }),
                /* @__PURE__ */ jsx2("td", { className: "max-w-[22rem] truncate px-2 py-1.5 font-medium text-(--ui-text-primary)", children: card.title || card.file.replace(/\.md$/, "") }),
                /* @__PURE__ */ jsx2("td", { className: "px-2 py-1.5 whitespace-nowrap", children: /* @__PURE__ */ jsx2(StatusCell, { status: card.status }) }),
                /* @__PURE__ */ jsx2("td", { className: "px-2 py-1.5 whitespace-nowrap", children: /* @__PURE__ */ jsx2(PriorityBadge, { value: card.priority }) }),
                /* @__PURE__ */ jsx2("td", { className: "px-2 py-1.5 whitespace-nowrap", children: /* @__PURE__ */ jsx2(SizeBadge, { value: card.size }) }),
                /* @__PURE__ */ jsx2("td", { className: "px-2 py-1.5", children: card.tags && card.tags.length > 0 ? /* @__PURE__ */ jsx2("span", { className: "flex flex-wrap gap-1", children: card.tags.map((t) => /* @__PURE__ */ jsx2("span", { className: "rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)", children: t }, t)) }) : /* @__PURE__ */ jsx2("span", { className: "text-(--ui-text-quaternary)", children: "—" }) }),
                /* @__PURE__ */ jsxs2("td", { className: cn2("px-2 py-1.5 whitespace-nowrap", isOverdue(card.due) ? "font-semibold text-(--ui-red)" : "text-(--ui-text-secondary)"), children: [
                  card.due || "—",
                  isOverdue(card.due) && " ⚠"
                ] }),
                /* @__PURE__ */ jsx2("td", { className: "px-2 py-1.5 whitespace-nowrap font-mono text-[0.75rem] text-(--ui-text-quaternary)", children: fmtTime(card.mtime) })
              ]
            },
            section.key + ":" + card.file + (card.entry_title || "")
          );
        })
      ] }, name);
    }) })
  ] }) });
}
var VIEW_MODES = [
  { key: "board", label: "Board" },
  { key: "table", label: "Table" }
];
function ViewSwitcher({ mode, onChange }) {
  return /* @__PURE__ */ jsx2("div", { className: "flex items-center rounded-md border border-(--ui-stroke-secondary) p-0.5", children: VIEW_MODES.map((v) => /* @__PURE__ */ jsx2(
    "button",
    {
      className: cn2(
        "rounded px-2 py-0.5 text-[0.8125rem] transition-colors",
        mode === v.key ? "bg-(--ui-accent) text-white" : "text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)"
      ),
      onClick: () => onChange(v.key),
      type: "button",
      children: v.label
    },
    v.key
  )) });
}

// desktop-src/home.tsx
import { cn as cn3, Codicon as Codicon2, host as host2, useQuery as useQuery2 } from "@hermes/plugin-sdk";
import { useEffect, useMemo as useMemo2, useReducer, useRef, useState as useState2 } from "react";

// desktop-src/batch-response.ts
function validateBatchResponse(input) {
  if (!isRecord(input)) return invalid("响应不是 object");
  if (typeof input.ok !== "boolean") return invalid("响应 ok 必须是 boolean");
  if (!Array.isArray(input.done)) return invalid("响应 done 必须是数组");
  if (!Array.isArray(input.failed)) return invalid("响应 failed 必须是数组");
  if (!isRecord(input.summary)) return invalid("响应 summary 必须是 object");
  const ok = input.summary.ok;
  const fail = input.summary.fail;
  if (!isCount(ok) || !isCount(fail)) return invalid("响应 summary.ok/fail 必须是 finite 非负整数");
  const done = parseRows(input.done, "done");
  if (!done.valid) return done;
  const failed = parseRows(input.failed, "failed");
  if (!failed.valid) return failed;
  if (input.error !== void 0 && typeof input.error !== "string") return invalid("响应 error 必须是 string");
  const undo = parseUndoReceipt(input.operation_id, input.undo_receipt);
  if (!undo.valid) return undo;
  return {
    valid: true,
    response: {
      ok: input.ok,
      done: done.rows,
      failed: failed.rows,
      summary: { ok, fail },
      ...input.error === void 0 ? {} : { error: input.error },
      ...undo.receipt === void 0 ? {} : { operation_id: undo.receipt.operation_id, undo_receipt: undo.receipt }
    }
  };
}
function isGlobalBatchRejection(response) {
  return response.ok === false && response.done.length === 0 && response.failed.length === 0 && response.summary.ok === 0 && response.summary.fail === 0 && typeof response.error === "string" && response.error.length > 0;
}
function settleLegacyBatchResponse(action, submitted, input) {
  const validation = validateBatchResponse(input);
  if (!validation.valid) return validation;
  const response = validation.response;
  if (isGlobalBatchRejection(response)) return globalRejection(response.error);
  if (response.summary.ok !== response.done.length || response.summary.fail !== response.failed.length) {
    return invalid("summary 计数与 done/failed 长度不一致");
  }
  const expectedOk = response.failed.length === 0 || response.done.length > 0;
  if (response.ok !== expectedOk) return invalid("响应 ok 与 done/failed 真值表不一致");
  const expected = /* @__PURE__ */ new Set();
  for (const item of submitted) {
    const identity = batchIdentity(action, item.dir, item.file, item.entry_title ?? "");
    if (!identity || expected.has(identity)) return invalid("submitted identity 非空且唯一");
    expected.add(identity);
  }
  const actual = /* @__PURE__ */ new Set();
  for (const row of [...response.done, ...response.failed]) {
    const identity = batchIdentity(action, row.dir, row.file, row.entry ?? "");
    if (!identity || actual.has(identity)) return invalid("done/failed identity 非空、唯一且不交叠");
    actual.add(identity);
  }
  if (actual.size !== expected.size || [...actual].some((identity) => !expected.has(identity))) {
    return invalid("done/failed identity 必须属于并精确覆盖 submitted");
  }
  const receipt = response.undo_receipt;
  if (action === "trash" && response.done.length > 0) {
    if (!receipt) return invalid("trash 成功响应必须包含 authoritative undo receipt");
    const doneIdentities = response.done.map((row) => batchIdentity("trash", row.dir, row.file, ""));
    const receiptIdentities = receipt.items.map((item) => batchIdentity("trash", item.dir, item.file, ""));
    if (receiptIdentities.length !== doneIdentities.length || receiptIdentities.some((identity, index) => identity !== doneIdentities[index])) {
      return invalid("undo receipt identities 必须精确等于 trash done identities");
    }
  } else if (receipt) {
    return invalid("undo receipt 只允许用于有成功项的 trash 响应");
  }
  return validation;
}
function consumeBatchResponse(action, submitted, input, effects) {
  const decision = settleLegacyBatchResponse(action, submitted, input);
  if (!decision.valid) {
    effects.notify({ kind: "error", message: decision.error });
    return decision;
  }
  const okN = decision.response.summary.ok;
  const failN = decision.response.summary.fail;
  const failedItems = failN > 0 ? submitted.filter((item) => decision.response.failed.some((row) => batchIdentity(action, item.dir, item.file, item.entry_title ?? "") === batchIdentity(action, row.dir, row.file, row.entry ?? ""))) : [];
  const failureDetails = decision.response.failed.map((row) => `${row.entry?.trim() || row.file}: ${row.error || "操作失败"}`).join("；");
  effects.notify({
    kind: failN > 0 ? "warning" : "success",
    message: `${action === "trash" ? "批量移入回收站" : "批量归档"} ${okN} 项${failN ? `，${failN} 项失败：${failureDetails}` : ""}`
  });
  if (okN > 0) effects.invalidate();
  if (action === "trash" && decision.response.undo_receipt) effects.offerUndo(decision.response.undo_receipt);
  if (failN > 0) {
    effects.replaceSelection(failedItems);
  } else {
    effects.clearSelection();
    effects.exitMultiMode();
  }
  return decision;
}
var consumeLegacyBatchResponse = consumeBatchResponse;
function validateBatchUndoResponse(expected, input) {
  if (!isRecord(input) || typeof input.ok !== "boolean") return invalidUndo("响应 ok 必须是 boolean");
  if (!Array.isArray(input.restored) || !Array.isArray(input.failed) || !isRecord(input.summary)) {
    return invalidUndo("restored/failed/summary 形状无效");
  }
  if (!isCount(input.summary.restored) || !isCount(input.summary.failed)) return invalidUndo("summary 计数无效");
  if (!isRecord(input.receipt) || input.receipt.schema !== "workbench.batch-trash-undo" || input.receipt.version !== 2 || input.receipt.operation_id !== expected.operation_id || input.receipt.action !== "trash" || typeof input.receipt.consumed !== "boolean") {
    return invalidUndo("receipt operation/action/consumed 不匹配");
  }
  if (input.error !== void 0 && typeof input.error !== "string") return invalidUndo("error 必须是 string");
  const restored = [];
  const failed = [];
  const actual = /* @__PURE__ */ new Set();
  for (let index = 0; index < input.restored.length; index += 1) {
    const row = input.restored[index];
    if (!isRecord(row) || Object.keys(row).sort().join(",") !== "dir,file" || typeof row.dir !== "string" || typeof row.file !== "string") {
      return invalidUndo(`restored[${index}] identity 无效`);
    }
    const identity = batchIdentity("trash", row.dir, row.file, "");
    if (!identity || actual.has(identity)) return invalidUndo("restored/failed identity 必须唯一");
    actual.add(identity);
    restored.push({ dir: row.dir, file: row.file });
  }
  for (let index = 0; index < input.failed.length; index += 1) {
    const row = input.failed[index];
    if (!isRecord(row) || Object.keys(row).sort().join(",") !== "dir,error,file" || typeof row.dir !== "string" || typeof row.file !== "string" || typeof row.error !== "string") {
      return invalidUndo(`failed[${index}] identity/error 无效`);
    }
    const identity = batchIdentity("trash", row.dir, row.file, "");
    if (!identity || actual.has(identity)) return invalidUndo("restored/failed identity 必须唯一");
    actual.add(identity);
    failed.push({ dir: row.dir, file: row.file, error: row.error });
  }
  if (input.summary.restored !== restored.length || input.summary.failed !== failed.length) {
    return invalidUndo("summary 与 restored/failed 长度不一致");
  }
  if (!input.receipt.consumed) {
    if (input.ok || actual.size !== 0 || input.summary.restored !== 0 || input.summary.failed !== 0 || typeof input.error !== "string" || !input.error) {
      return invalidUndo("未消费拒绝必须零移动并带可行动 error");
    }
  } else {
    const expectedIdentities = expected.items.map((item) => batchIdentity("trash", item.dir, item.file, ""));
    if (actual.size !== expectedIdentities.length || expectedIdentities.some((identity) => !identity || !actual.has(identity))) {
      return invalidUndo("terminal consumed 必须精确结算 receipt 全部 identities");
    }
    if (input.ok !== restored.length > 0) return invalidUndo("ok 与 restored 数量不一致");
  }
  return {
    valid: true,
    response: {
      ok: input.ok,
      restored,
      failed,
      summary: { restored: input.summary.restored, failed: input.summary.failed },
      receipt: { schema: "workbench.batch-trash-undo", version: 2, operation_id: expected.operation_id, action: "trash", consumed: input.receipt.consumed },
      ...input.error === void 0 ? {} : { error: input.error }
    }
  };
}
function consumeBatchUndoResponse(expected, input, effects) {
  const decision = validateBatchUndoResponse(expected, input);
  if (!decision.valid) {
    effects.notify({ kind: "error", message: decision.error });
    effects.retainReceipt?.();
    return decision;
  }
  const response = decision.response;
  if (!response.receipt.consumed) {
    effects.notify({ kind: "error", message: response.error || "撤销移入回收站被拒绝，receipt 已保留" });
    effects.retainReceipt?.();
    return decision;
  }
  if (response.restored.length > 0) effects.invalidate();
  effects.notify({
    kind: response.failed.length > 0 ? "warning" : "success",
    message: `撤销移入回收站：恢复 ${response.restored.length} 项${response.failed.length ? `，${response.failed.length} 项失败；本 receipt 已终结，不可再次撤销：${response.failed.map((item) => `${item.file}: ${item.error}`).join("；")}` : ""}`
  });
  effects.clearReceipt();
  return decision;
}
function batchIdentity(action, dir, file, entry) {
  const canonicalDir = canonicalPath(dir);
  const canonicalFile = canonicalPath(file);
  if (!canonicalDir || !canonicalFile) return null;
  const base = JSON.stringify([canonicalDir, canonicalFile]);
  return action === "resolve" || action === "to-task" ? `${base}:${entry.trim()}` : base;
}
function canonicalPath(value) {
  const parts = [];
  for (const part of value.trim().replaceAll("\\", "/").split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (parts.length === 0) return "";
      parts.pop();
    } else {
      parts.push(part);
    }
  }
  return parts.join("/").toLocaleLowerCase();
}
function parseRows(value, label) {
  const rows = [];
  for (let index = 0; index < value.length; index += 1) {
    const row = value[index];
    if (!isRecord(row) || typeof row.dir !== "string" || row.dir.length === 0 || typeof row.file !== "string" || row.file.length === 0) {
      return invalid(`响应 ${label}[${index}] 必须包含非空 string dir/file`);
    }
    if (row.entry !== void 0 && typeof row.entry !== "string") return invalid(`响应 ${label}[${index}].entry 必须是 string`);
    if (row.error !== void 0 && typeof row.error !== "string") return invalid(`响应 ${label}[${index}].error 必须是 string`);
    rows.push({
      dir: row.dir,
      file: row.file,
      ...row.entry === void 0 ? {} : { entry: row.entry },
      ...row.error === void 0 ? {} : { error: row.error }
    });
  }
  return { valid: true, rows };
}
function parseUndoReceipt(operationId, value) {
  if (operationId === void 0 && value === void 0) return { valid: true };
  if (typeof operationId !== "string" || !/^[0-9a-f]{32}$/.test(operationId)) return invalid("operation_id 必须是 32 位小写 hex");
  if (!isRecord(value) || value.schema !== "workbench.batch-trash-undo" || value.version !== 2) return invalid("undo_receipt schema/version 不支持");
  if (value.operation_id !== operationId || value.action !== "trash") return invalid("undo_receipt operation/action 不匹配");
  if (typeof value.expires_at !== "string" || !Number.isFinite(Date.parse(value.expires_at))) return invalid("undo_receipt expires_at 无效");
  if (!Array.isArray(value.items) || value.items.length === 0) return invalid("undo_receipt items 必须非空");
  const items = [];
  for (let index = 0; index < value.items.length; index += 1) {
    const item = value.items[index];
    if (!isRecord(item) || Object.keys(item).sort().join(",") !== "dir,file" || typeof item.dir !== "string" || typeof item.file !== "string") {
      return invalid(`undo_receipt items[${index}] 必须只有 string dir/file`);
    }
    items.push({ dir: item.dir, file: item.file });
  }
  return { valid: true, receipt: { schema: "workbench.batch-trash-undo", version: 2, operation_id: operationId, action: "trash", expires_at: value.expires_at, items } };
}
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isCount(value) {
  return typeof value === "number" && Number.isFinite(value) && Number.isInteger(value) && value >= 0;
}
function invalid(error) {
  return { valid: false, classification: "protocol-error", error: `批量响应协议错误：${error}` };
}
function globalRejection(error) {
  return { valid: false, classification: "global-rejection", error };
}
function invalidUndo(error) {
  return { valid: false, classification: "protocol-error", error: `撤销移入回收站响应协议错误：${error}` };
}

// desktop-src/home-model.ts
var HOME_VIEW_INITIAL_STATE = { showAllRegionId: null };
function pickMulti(state) {
  return { multiSelectOpen: state.multiSelectOpen, selectedIds: state.selectedIds };
}
function homeViewStateReducer(_state, action) {
  switch (action.type) {
    case "show-all":
      return { showAllRegionId: action.regionId, ...pickMulti(_state) };
    case "open-archive":
      return { showAllRegionId: null, archiveOpen: true, ...pickMulti(_state) };
    case "back":
      return { ...HOME_VIEW_INITIAL_STATE, ...pickMulti(_state) };
    case "enter-multiselect":
      return { ..._state, multiSelectOpen: true };
    case "exit-multiselect":
      return { ..._state, multiSelectOpen: false, selectedIds: [] };
    case "toggle-select": {
      const ids = _state.selectedIds ?? [];
      return {
        ..._state,
        selectedIds: ids.includes(action.id) ? ids.filter((id2) => id2 !== action.id) : [...ids, action.id]
      };
    }
    case "select-all-visible":
      return { ..._state, selectedIds: action.ids };
    case "clear-selection":
      return { ..._state, selectedIds: [] };
    case "batch-settled":
      return { ..._state, multiSelectOpen: false, selectedIds: [] };
    case "batch-settle":
      return { ..._state, multiSelectOpen: action.multiSelectOpen, selectedIds: action.selectedIds };
    default:
      return _state;
  }
}
function buildHomeViewPresentation(model, state, previewLimit = 8) {
  const regions = model.regions.map((region) => ({
    ...region,
    visibleItems: region.items.slice(0, previewLimit),
    canShowAll: region.items.length > previewLimit
  }));
  const expandedSource = state.showAllRegionId ? model.regions.find((region) => region.id === state.showAllRegionId) ?? null : null;
  const expandedRegion = expandedSource ? { ...expandedSource, visibleItems: expandedSource.items, canShowAll: false } : null;
  const archiveOpen = state.archiveOpen === true;
  const selectableIds = /* @__PURE__ */ new Set();
  for (const region of model.regions) {
    for (const item of region.items) {
      if (item.side !== "active") continue;
      selectableIds.add(homeCardSelectionId(item.card));
    }
  }
  const multiSelectActive = state.multiSelectOpen === true && !archiveOpen;
  const selectedIds = (state.selectedIds ?? []).filter((id2) => selectableIds.has(id2));
  const staleSelectionVisible = multiSelectActive ? (state.selectedIds ?? []).filter((id2) => !selectableIds.has(id2)).map((id2) => {
    const found = findCardById(model, id2);
    const reason = found === "contract-error" ? "状态未知，不可批处理" : found === null ? "条目已不在当前事实源（可能已在其他会话处理）" : found.side === "done" ? "已归档，只读不可批处理" : "状态未知，不可批处理";
    return { id: id2, reason };
  }) : [];
  const visibleIds = [];
  let readonlyVisibleCount = 0;
  if (!archiveOpen) {
    const source = expandedRegion ? [expandedRegion] : regions;
    for (const region of source) {
      for (const item of region.visibleItems) {
        if (item.side === "active") visibleIds.push(homeCardSelectionId(item.card));
        else readonlyVisibleCount += 1;
      }
    }
  }
  const batchActionEligibility = multiSelectActive && selectedIds.length > 0 ? Object.fromEntries(
    HOME_BATCH_ACTIONS.map((action) => [
      action,
      summarizeEligibility(computeBatchActionEligibility(model, selectedIds, action))
    ])
  ) : null;
  return {
    mode: archiveOpen ? "archive" : expandedRegion ? "expanded" : "home",
    regions,
    expandedRegion: archiveOpen ? null : expandedRegion,
    contractErrorBannerVisible: model.contractErrors.length > 0,
    legacyFallbackVisible: true,
    archiveEntryVisible: true,
    archive: archiveOpen ? model.archive : null,
    multiSelectOpen: multiSelectActive,
    multiSelectCount: selectedIds.length,
    multiSelectVisibleIds: visibleIds,
    selectedIds,
    canSubmitBatch: multiSelectActive && selectedIds.length > 0,
    multiSelectReadonlyCount: multiSelectActive ? readonlyVisibleCount : 0,
    batchActionEligibility,
    staleSelection: staleSelectionVisible
  };
}
function findCardById(model, id2) {
  for (const region of model.regions) {
    for (const item of region.items) {
      if (homeCardSelectionId(item.card) === id2) return { side: item.side };
    }
  }
  for (const err of model.contractErrors) {
    if (homeCardSelectionId(err.card) === id2) return "contract-error";
  }
  return null;
}
var REVIEWABLE_SECTIONS = /* @__PURE__ */ new Set(["thought", "video", "psych", "dream"]);
var COMPLETED_STATUSES = /* @__PURE__ */ new Set(["completed", "ingested", "accepted", "ignored", "done", "abandoned", "cleared"]);
var ATTENTION_STATUSES = /* @__PURE__ */ new Set(["waiting_user", "failed"]);
var ACTIVE_STATUSES = /* @__PURE__ */ new Set(["in_progress", "active", "processing"]);
var INBOX_STATUSES = /* @__PURE__ */ new Set(["pending", "queued", "todo"]);
var HOME_STATUS_VOCAB = {
  inbox: INBOX_STATUSES,
  attention: ATTENTION_STATUSES,
  active: ACTIVE_STATUSES,
  completed: COMPLETED_STATUSES
};
function isFailedExecution(card) {
  return (card.execution_result || "").trim().toLowerCase() === "failure";
}
function classifyCard(sectionKey, card) {
  if (sectionKey === "done") return "recent";
  const status = (card.status || "").trim().toLowerCase();
  if (COMPLETED_STATUSES.has(status)) return "recent";
  if (ATTENTION_STATUSES.has(status)) return "attention";
  if (ACTIVE_STATUSES.has(status)) return isFailedExecution(card) ? "attention" : "today";
  if (INBOX_STATUSES.has(status) || status === "") return isFailedExecution(card) ? "attention" : "inbox";
  return "error";
}
function keyOf(card) {
  return `${card.dir}/${card.file}`;
}
function buildHomeModel(board, _brief, _health) {
  const todayRegion = { id: "today", count: 0, items: [] };
  const inboxRegion = { id: "inbox", count: 0, items: [] };
  const attentionItems = [];
  const recentRegion = { id: "recent", count: 0, items: [] };
  const contractErrors = [];
  const skipped = [];
  for (const section of board.sections ?? []) {
    if (section.key === "trash") {
      for (const f of section.files ?? []) skipped.push({ dir: f.dir, file: f.file, why: "trash-partition" });
      continue;
    }
    const isReviewable = REVIEWABLE_SECTIONS.has(section.key);
    for (const card of section.files ?? []) {
      if (isReviewable && (card.entry_count ?? 0) === 0 && (card.entries?.length ?? 0) === 0) {
        skipped.push({ dir: card.dir, file: card.file, why: "empty-shell" });
        continue;
      }
      if (isReviewable) {
        const verdict = classifyCard(section.key, card);
        if (verdict === "error") {
          contractErrors.push({ card, reason: `未知状态 "${card.status}"（分区 ${section.key}）` });
          continue;
        }
        if (verdict === "recent") {
          recentRegion.items.push({ card, side: "active" });
        } else {
          ;
          (verdict === "attention" ? attentionItems : verdict === "today" ? todayRegion.items : inboxRegion.items).push({ card, side: "active" });
        }
        continue;
      }
      const dest = classifyCard(section.key, card);
      if (dest === "error") {
        contractErrors.push({ card, reason: `未知状态 "${card.status}"` });
        continue;
      }
      if (dest === "inbox") {
        inboxRegion.items.push({ card, side: "active" });
        continue;
      }
      if (dest === "today") {
        todayRegion.items.push({ card, side: "active" });
        continue;
      }
      if (dest === "attention") {
        attentionItems.push({ card, side: "active" });
        continue;
      }
      recentRegion.items.push({ card, side: section.key === "done" ? "done" : "active" });
    }
  }
  const promoted = [];
  for (const item of inboxRegion.items) {
    if (item.card.due && /^\d{4}-\d{2}-\d{2}$/.test(item.card.due) && item.card.due === board.today) {
      promoted.push(item.card);
    }
  }
  if (promoted.length > 0) {
    const promotedSet = new Set(promoted.map(keyOf));
    inboxRegion.items = inboxRegion.items.filter((i) => !promotedSet.has(keyOf(i.card)));
    for (const c of promoted) todayRegion.items.push({ card: c, side: "active" });
  }
  const needsDecision = attentionItems.filter(({ card }) => {
    const s = (card.status || "").trim().toLowerCase();
    return s === "waiting_user" || !ATTENTION_STATUSES.has(s) && !isFailedExecution(card);
  }).length;
  const failures = attentionItems.length - needsDecision;
  const regions = [
    todayRegion,
    inboxRegion,
    { id: "attention", count: attentionItems.length, items: attentionItems },
    recentRegion
  ];
  for (const r of regions) r.count = r.items.length;
  return {
    regions,
    contractErrors,
    skipped,
    totals: {
      today: todayRegion.count,
      inbox: inboxRegion.count,
      attention: { needsDecision, failures, total: attentionItems.length },
      recent: recentRegion.count,
      contractErrors: contractErrors.length
    },
    // WB-S1-041：完整 done/trash 只读归档模型（复用同一 /board sections，
    // 聚合所有同 key sections；不在 HomeModel 中复制数据库/新增 schema/API）。
    archive: buildArchiveModel(board)
  };
}
function buildArchiveModel(board) {
  const collect = (partition) => {
    const entries = [];
    for (const section of board.sections ?? []) {
      if (section.key !== partition) continue;
      for (const card of section.files ?? []) entries.push({ card, partition });
    }
    return { count: entries.length, entries };
  };
  return { done: collect("done"), trash: collect("trash") };
}
var HOME_BATCH_ACTIONS = ["complete", "resolve", "to-task", "trash"];
var HOME_BATCH_ACTION_LABEL = {
  complete: "完成",
  resolve: "处理",
  "to-task": "移入任务",
  trash: "回收站"
};
function homeCardSelectionId(card) {
  return `${card.dir}|${card.file}`;
}
function homeSelectionIdToParts(id2) {
  const sep = id2.indexOf("|");
  if (sep <= 0 || sep === id2.length - 1) throw new Error(`invalid selection id: ${id2}`);
  return { dir: id2.slice(0, sep), file: id2.slice(sep + 1) };
}
function buildHomeBatchSubmission(ids, action, model) {
  const selectable = /* @__PURE__ */ new Set();
  for (const region of model.regions) {
    for (const item of region.items) {
      if (item.side !== "active") continue;
      selectable.add(homeCardSelectionId(item.card));
    }
  }
  if (new Set(ids).size !== ids.length) return null;
  const items = [];
  for (const id2 of ids) {
    if (!selectable.has(id2)) continue;
    try {
      const { dir, file } = homeSelectionIdToParts(id2);
      items.push({ dir, file });
    } catch {
      continue;
    }
  }
  if (items.length === 0) return null;
  const eligibility = computeBatchActionEligibility(model, ids, action);
  if (eligibility.ineligible.length > 0 || eligibility.eligible.length !== new Set(ids).size) return null;
  return { action, items };
}
var BATCH_INBOX_DIRS = /* @__PURE__ */ new Set(["待验证", "待回看", "梦中的邮件", "心理学随想"]);
var BATCH_TRASH_DIRS = /* @__PURE__ */ new Set(["待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站"]);
function computeBatchActionEligibility(model, ids, action) {
  const byId = /* @__PURE__ */ new Map();
  for (const region of model.regions) {
    for (const item of region.items) byId.set(homeCardSelectionId(item.card), { card: item.card, side: item.side });
  }
  const eligible = [];
  const ineligible = [];
  for (const id2 of new Set(ids)) {
    const found = byId.get(id2);
    if (!found || found.side !== "active") {
      const parts = safeIdParts(id2);
      ineligible.push({ id: id2, dir: parts.dir, file: parts.file, reason: "已归档 / 未知状态 / 已不在当前事实源，批处理不适用" });
      continue;
    }
    const card = found.card;
    const status = (card.status || "").trim();
    const execResult = (card.execution_result || "").trim().toLowerCase();
    let reason = null;
    if (action === "complete") {
      const isTodo = status === "todo";
      const isInProgressSuccess = status === "in_progress" && execResult === "success";
      const isDoneSuccess = status.toLowerCase() === "done" && execResult === "success";
      const isCompleted = status === "completed";
      if (!isTodo && !isInProgressSuccess && !isDoneSuccess && !isCompleted) {
        reason = `状态 ${status || "（空）"}——仅 todo、执行中(execution_result=success)、done+success、completed 可「完成」`;
      }
    } else if (action === "trash") {
      if (!BATCH_TRASH_DIRS.has(card.dir)) reason = `分区 ${card.dir || "（空）"} 不在当前事实源分区白名单`;
    } else if (action === "resolve" || action === "to-task") {
      if (!BATCH_INBOX_DIRS.has(card.dir)) reason = `仅收件箱分区（待验证/待回看/梦中的邮件/心理学随想）可${action === "resolve" ? "确认处理" : "转任务"}`;
    }
    if (reason) ineligible.push({ id: id2, dir: card.dir, file: card.file, reason });
    else eligible.push(id2);
  }
  return { eligible, ineligible };
}
function safeIdParts(id2) {
  try {
    return homeSelectionIdToParts(id2);
  } catch {
    return { dir: "", file: id2 };
  }
}
function summarizeEligibility(r) {
  return { eligibleCount: r.eligible.length, ineligibleCount: r.ineligible.length, ineligible: r.ineligible };
}
var BatchGate = class {
  held = false;
  tryAcquire() {
    if (this.held) return false;
    this.held = true;
    return true;
  }
  release() {
    this.held = false;
  }
};
async function guardedSubmit(gate, transport) {
  if (!gate.tryAcquire()) return null;
  try {
    return await transport();
  } finally {
    gate.release();
  }
}
function settleBatchResponse(_state, input, submittedIds) {
  const submitted = uniq(submittedIds);
  const submittedSet = new Set(submitted);
  const originalSelected = uniq(_state.selectedIds ?? submitted);
  const staleIds = originalSelected.filter((id2) => !submittedSet.has(id2));
  const preserveWithStale = (ids) => uniq([...ids, ...staleIds]);
  if ("transportError" in input) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: input.transportError };
  }
  const { ok, done, failed, summary, error } = input;
  const wire = validateBatchResponse(input);
  if (!wire.valid) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: protocolFailedDetails(failed), overallError: `${wire.error}${error ? `；后端错误：${error}` : ""}。未移除任何条目，保留全部所选` };
  }
  if (isGlobalBatchRejection(wire.response)) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: wire.response.error };
  }
  const doneItems = Array.isArray(done) ? done : null;
  const failedItems = Array.isArray(failed) ? failed : null;
  const summaryRequired = summary !== void 0 && summary !== null && typeof summary.ok === "number" && typeof summary.fail === "number" && Number.isFinite(summary.ok) && Number.isFinite(summary.fail) && Number.isInteger(summary.ok) && Number.isInteger(summary.fail) && summary.ok >= 0 && summary.fail >= 0;
  if (!summaryRequired) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: `批量响应协议错误：summary 缺失或畸形（必须为 finite 非负整数 ok/fail）${error ? `；后端错误：${error}` : ""}。未移除任何条目，保留全部所选` };
  }
  if (doneItems === null || failedItems === null) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: "批量响应协议错误：done 或 failed 数组缺失（二者均为必需字段），未移除任何条目，保留全部所选" };
  }
  const doneParsed = [];
  const failedParsed = [];
  const problems = [];
  for (const raw of doneItems ?? []) {
    const p = ident(raw);
    if (!p) {
      problems.push("done 含空 identity");
      continue;
    }
    doneParsed.push(p.id);
    if (!submittedSet.has(p.id)) problems.push(`done 含外来 identity「${p.id}」`);
  }
  for (const raw of failedItems ?? []) {
    const p = ident(raw);
    if (!p) {
      problems.push("failed 含空 identity");
      failedParsed.push({ id: "", dir: raw?.dir ?? "", file: raw?.file ?? "", reason: raw?.error ?? "（无 dir/file 的畸形行）" });
      continue;
    }
    failedParsed.push({ id: p.id, dir: p.dir, file: p.file, reason: raw?.error ?? "failed" });
    if (!submittedSet.has(p.id)) problems.push(`failed 含外来 identity「${p.id}」`);
  }
  if (new Set(doneParsed).size !== doneParsed.length) problems.push("done 含重复 identity");
  const failedIds = failedParsed.filter((f) => f.id !== "").map((f) => f.id);
  if (new Set(failedIds).size !== failedIds.length) problems.push("failed 含重复 identity");
  const doneSet = new Set(doneParsed);
  const failedSet = new Set(failedIds);
  const overlap = [...doneSet].filter((id2) => failedSet.has(id2));
  if (overlap.length > 0) problems.push(`done/failed 交集「${overlap.join("、")}」`);
  const union = /* @__PURE__ */ new Set([...doneSet, ...failedSet]);
  if (union.size !== submitted.length || !submitted.every((id2) => union.has(id2))) {
    problems.push("done∪failed 与 submitted 不完全相等（缺项或多余）");
  }
  if (summaryRequired) {
    const okCount = summary.ok;
    const failCount = summary.fail;
    if (okCount !== doneParsed.length || failCount !== failedIds.length) {
      problems.push(`summary 计数与数组不一致（ok=${okCount}≠done=${doneParsed.length}；fail=${failCount}≠failed=${failedIds.length}）`);
    }
  }
  const backendOkFormula = failedIds.length === 0 || doneParsed.length > 0;
  if (ok !== backendOkFormula) {
    problems.push(`顶层 ok=${ok} 与后端真值表矛盾（failed=${failedIds.length} 项、done=${doneParsed.length} 项；后端公式 ok=(failed空)或(done非空) → 期望 ${backendOkFormula}）`);
  }
  if (problems.length > 0) {
    return {
      settledCleanly: false,
      keepOpen: true,
      selectedIds: preserveWithStale(submitted),
      removedCount: 0,
      failedDetail: failedParsed,
      overallError: `批量响应协议错误：${problems.join("；")}。未移除任何条目、不推断成功，保留全部所选可重试`
    };
  }
  if (failedIds.length > 0 || ok === false) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(failedIds), removedCount: doneParsed.length, failedDetail: failedParsed, overallError: staleIds.length > 0 ? "仍有未提交的失效选择；请逐项取消选择、点击 Clear 或退出多选以明确清理" : null };
  }
  if (doneParsed.length > 0) {
    if (staleIds.length > 0) {
      return { settledCleanly: false, keepOpen: true, selectedIds: staleIds, removedCount: doneParsed.length, failedDetail: [], overallError: "可提交项已成功；仍有未提交的失效选择，请逐项取消选择、点击 Clear 或退出多选以明确清理" };
    }
    return { settledCleanly: true, keepOpen: false, selectedIds: [], removedCount: doneParsed.length, failedDetail: [], overallError: null };
  }
  return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: "批量结果无法判定（无成功项），选择保留，可重试" };
}
function protocolFailedDetails(value) {
  if (!Array.isArray(value)) return [];
  return value.map((raw) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return { id: "", dir: "", file: "", reason: "（畸形 failed 行）" };
    }
    const row = raw;
    const dir = typeof row.dir === "string" ? row.dir : "";
    const file = typeof row.file === "string" ? row.file : "";
    const reason = typeof row.error === "string" && row.error.length > 0 ? row.error : "（畸形 failed 行）";
    return { id: dir && file ? `${dir}|${file}` : "", dir, file, reason };
  });
}
function ident(raw) {
  if (!raw || !raw.dir || !raw.file) return null;
  return { id: `${raw.dir}|${raw.file}`, dir: raw.dir, file: raw.file };
}
function uniq(xs) {
  return [...new Set(xs)];
}

// desktop-src/card-action.ts
var STATUS_PRIMARY = {
  inbox: { kind: "start", label: "开始处理", reason: "新进件还没有开过工——从这一步启动它" },
  active: { kind: "progress", label: "查看进度", reason: "正在执行中，看最新进展" },
  attention: { kind: "confirm", label: "确认处理", reason: "需要你拍板或修复后才能继续" },
  completed: { kind: "evidence", label: "查看证据", reason: "已完结，可核对产物与沉淀记录" }
};
function homeCardPrimaryAction(card) {
  const status = (card.status || "").trim().toLowerCase();
  if (isFailedExecution({ execution_result: card.execution_result })) {
    return { ...STATUS_PRIMARY.attention, enabled: true };
  }
  if (HOME_STATUS_VOCAB.inbox.has(status) || status === "") {
    return { ...STATUS_PRIMARY.inbox, enabled: true };
  }
  if (HOME_STATUS_VOCAB.active.has(status)) {
    return { ...STATUS_PRIMARY.active, enabled: true };
  }
  if (HOME_STATUS_VOCAB.attention.has(status)) {
    return { ...STATUS_PRIMARY.attention, enabled: true };
  }
  if (status === "completed" || status === "ingested" || status === "accepted" || status === "ignored" || status === "done") {
    return { ...STATUS_PRIMARY.completed, enabled: true };
  }
  return null;
}
function conversationPrimaryAction(ref) {
  const sessionId = (ref.session_id || "").trim();
  if (ref.resume_mode === "original" && sessionId) {
    return { kind: "open_original", label: "打开原会话", enabled: true, reason: `官方会话 ${sessionId.slice(0, 12)}… 可直达` };
  }
  return { kind: "resume_summary", label: "摘要续接", enabled: true, reason: "无稳定原会话引用，用摘要继续最稳" };
}

// desktop-src/home-search.ts
function searchResultToCard(r, root) {
  return {
    dir: r.dir,
    file: r.file,
    path: `${root.replace(/\/+$/, "")}/${r.dir}/${r.file}`,
    title: r.title,
    status: r.status,
    entries: [],
    entry_count: r.entry_count,
    priority: r.priority,
    size: r.size,
    tags: r.tags
  };
}
function homeSearchFeedback(input) {
  if (!input.hasQuery) return { kind: "idle", text: "" };
  const err = input.error;
  const msg = err instanceof Error ? err.message : typeof err === "string" ? err : "";
  if (err === "unreachable") {
    return {
      kind: "unreachable",
      text: "后端暂时不可达——请稍候重试；若持续出现请检查 Gateway 状态。",
      retry: true
    };
  }
  if (err) {
    if (msg.includes("超时")) {
      return { kind: "timeout", text: `搜索超时：${msg}。可再试一次或缩短关键词。`, retry: true };
    }
    return { kind: "failure", text: `搜索失败：${msg || "未知错误"}。可重试。`, retry: true };
  }
  if (input.isLoading) return { kind: "loading", text: "正在搜索…" };
  if (input.data && input.data.results.length === 0) {
    return { kind: "empty", text: "没有匹配的结果。换个关键词，或用「旧版数据」里的筛选器试试。" };
  }
  return { kind: "results", text: "" };
}

// desktop-src/home.tsx
import { Fragment as Fragment3, jsx as jsx3, jsxs as jsxs3 } from "react/jsx-runtime";
var BRIEF_TYPE_META = {
  new_task: { icon: "lightbulb", label: "新任务" },
  duplicate: { icon: "warning", label: "重复" },
  blocked: { icon: "stop", label: "阻塞" },
  overdue: { icon: "calendar", label: "过期重估" },
  decision: { icon: "question", label: "需决策" }
};
function TodayCardRow({ card, onPreview, multiSelectOpen = false, selected = false, selectable = true, onToggleSelect }) {
  const tone = STATUS_TONE[card.status] || "var(--ui-text-tertiary)";
  const prio = priorityMeta(card.priority || "");
  const primary = homeCardPrimaryAction(card);
  const selectId = homeCardSelectionId(card);
  return /* @__PURE__ */ jsxs3(
    "div",
    {
      className: cn3(
        "flex w-full items-center gap-2 rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1.5 transition-colors hover:border-(--ui-accent)",
        multiSelectOpen && "cursor-default",
        multiSelectOpen && !selectable && "cursor-not-allowed opacity-60",
        selected && "border-(--ui-accent) bg-[color-mix(in_srgb,var(--ui-accent)_10%,transparent)]"
      ),
      onClick: () => {
        if (multiSelectOpen) {
          if (selectable) onToggleSelect?.(selectId);
        } else {
          onPreview(card);
        }
      },
      role: "button",
      tabIndex: 0,
      onKeyDown: (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          if (multiSelectOpen) {
            if (selectable) onToggleSelect?.(selectId);
          } else {
            onPreview(card);
          }
        }
      },
      children: [
        multiSelectOpen && selectable && /* @__PURE__ */ jsx3(
          "span",
          {
            "data-wb-select-indicator": true,
            className: cn3(
              "flex size-4 shrink-0 items-center justify-center rounded-full border text-[0.6875rem]",
              selected ? "border-(--ui-accent) bg-(--ui-accent) text-(--ui-bg-elevated)" : "border-(--ui-stroke-tertiary)"
            ),
            children: selected ? "✓" : ""
          }
        ),
        multiSelectOpen && !selectable && /* @__PURE__ */ jsx3(
          "span",
          {
            "data-wb-readonly-badge": true,
            className: "shrink-0 rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.625rem] text-(--ui-text-quaternary)",
            children: "已归档只读"
          }
        ),
        /* @__PURE__ */ jsx3("span", { className: "size-1.5 shrink-0 rounded-full", style: { background: tone } }),
        prio && /* @__PURE__ */ jsx3("span", { className: "h-3 w-0.5 shrink-0 rounded", style: { background: prio.fg } }),
        /* @__PURE__ */ jsx3("span", { className: "min-w-0 flex-1 truncate text-[0.75rem] font-medium text-(--ui-text-primary)", children: card.title || card.file.replace(/\.md$/, "") }),
        card.due && /* @__PURE__ */ jsx3("span", { className: cn3("shrink-0 text-[0.75rem]", isOverdue(card.due) ? "font-semibold text-(--ui-red)" : "text-(--ui-text-tertiary)"), children: card.due }),
        !multiSelectOpen && primary && /* @__PURE__ */ jsxs3(
          "button",
          {
            type: "button",
            "data-wb-primary": primary.kind,
            title: primary.reason,
            className: "shrink-0 rounded border border-(--ui-accent)/40 bg-(--ui-accent)/10 px-2 py-0.5 text-[0.75rem] font-medium text-(--ui-accent) hover:bg-(--ui-accent)/20",
            onClick: (e) => {
              e.stopPropagation();
              onPreview(card);
            },
            children: [
              primary.label,
              /* @__PURE__ */ jsx3("span", { className: "ml-1 hidden text-[0.6875rem] font-normal text-(--ui-text-quaternary) sm:inline", children: "为什么" })
            ]
          }
        )
      ]
    }
  );
}
function BriefCardView({ card, onAccept, onIgnore }) {
  const meta = BRIEF_TYPE_META[card.type] ?? { icon: "info", label: card.type };
  return /* @__PURE__ */ jsxs3("div", { className: "flex items-start gap-2 rounded-md border border-(--ui-stroke-secondary) px-2.5 py-2", children: [
    /* @__PURE__ */ jsx3(Codicon2, { name: meta.icon, size: "0.8rem", className: "mt-0.5 shrink-0", style: { color: "var(--ui-accent)" } }),
    /* @__PURE__ */ jsxs3("div", { className: "min-w-0 flex-1", children: [
      /* @__PURE__ */ jsx3("div", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: card.title }),
      /* @__PURE__ */ jsx3("div", { className: "mt-0.5 text-[0.75rem] text-(--ui-text-tertiary)", children: card.reason }),
      /* @__PURE__ */ jsx3("div", { className: "mt-0.5 text-[0.6875rem] font-medium text-(--ui-accent)", children: "建议动作：查看右侧主按钮；其余操作在详情抽屉" }),
      /* @__PURE__ */ jsxs3("details", { className: "mt-1 text-[0.75rem] text-(--ui-text-quaternary)", children: [
        /* @__PURE__ */ jsx3("summary", { className: "cursor-pointer", children: "查看依据" }),
        /* @__PURE__ */ jsx3("ul", { className: "mt-1 list-disc pl-4", children: card.evidence.map((item) => /* @__PURE__ */ jsx3("li", { children: item }, item)) })
      ] }),
      /* @__PURE__ */ jsxs3("div", { className: "mt-1 flex items-center gap-1", children: [
        onAccept && /* @__PURE__ */ jsx3(
          "button",
          {
            className: "rounded bg-(--ui-accent)/15 px-2 py-1 text-[0.75rem] text-(--ui-accent) hover:bg-(--ui-accent)/25",
            onClick: onAccept,
            type: "button",
            children: "采纳"
          }
        ),
        /* @__PURE__ */ jsx3(
          "button",
          {
            className: "rounded px-2 py-1 text-[0.75rem] text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary)",
            onClick: onIgnore,
            type: "button",
            children: "忽略"
          }
        )
      ] })
    ] }),
    /* @__PURE__ */ jsx3("span", { className: "shrink-0 rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.75rem] text-(--ui-text-quaternary)", children: "规则建议" })
  ] });
}
function HomeRegionCardList({ items, totalCount, canShowAll, onPreview, onShowAll, multiSelectOpen = false, selectedIds, onToggleSelect }) {
  return /* @__PURE__ */ jsxs3(Fragment3, { children: [
    items.map(({ card, side }) => /* @__PURE__ */ jsx3(
      TodayCardRow,
      {
        card,
        onPreview,
        multiSelectOpen,
        selectable: side !== "done",
        selected: multiSelectOpen && (selectedIds?.has(homeCardSelectionId(card)) ?? false),
        onToggleSelect
      },
      `${card.dir}/${card.file}`
    )),
    canShowAll && /* @__PURE__ */ jsxs3(
      "button",
      {
        type: "button",
        "data-wb-show-all": true,
        className: "self-start rounded border border-(--ui-accent)/40 bg-(--ui-accent)/10 px-2 py-1 text-[0.75rem] font-medium text-(--ui-accent) hover:bg-(--ui-accent)/20",
        onClick: onShowAll,
        children: [
          "查看全部 ",
          totalCount,
          " 项 →"
        ]
      }
    )
  ] });
}
function HomeAllRegionList({ region, onBack, onPreview, multiSelectOpen = false, selectedIds, onToggleSelect }) {
  const title = region.id === "today" ? "今日" : region.id === "inbox" ? "待审核" : region.id === "attention" ? "需要注意" : "最近完成";
  const archivedCount = region.id === "recent" ? region.visibleItems.filter((i) => i.side === "done").length : 0;
  const activeDoneCount = region.id === "recent" ? region.visibleItems.filter((i) => i.side === "active").length : 0;
  return /* @__PURE__ */ jsxs3("div", { className: "flex flex-1 flex-col gap-2 overflow-y-auto px-3 pb-3", children: [
    /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-2 pt-2", children: [
      /* @__PURE__ */ jsx3(
        "button",
        {
          type: "button",
          "data-wb-show-all-back": true,
          className: "rounded border border-(--ui-stroke-secondary) px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)",
          onClick: onBack,
          children: "← 返回首页"
        }
      ),
      /* @__PURE__ */ jsxs3("span", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: [
        title,
        " · 全部"
      ] }),
      /* @__PURE__ */ jsxs3("span", { className: "text-[0.75rem] tabular-nums text-(--ui-text-quaternary)", children: [
        region.count,
        " 项"
      ] }),
      /* @__PURE__ */ jsx3("span", { className: "rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.6875rem] text-(--ui-text-quaternary)", children: region.id === "recent" ? region.visibleItems.length === 0 ? "最近完成（混合投影）" : `已归档 ${archivedCount} · 已完成未归档 ${activeDoneCount}` : "活动任务（active 侧投影）" })
    ] }),
    /* @__PURE__ */ jsx3("div", { className: "flex flex-col gap-1.5", children: region.visibleItems.map(({ card, side }) => /* @__PURE__ */ jsx3(
      TodayCardRow,
      {
        card,
        onPreview,
        multiSelectOpen,
        selectable: side !== "done",
        selected: multiSelectOpen && (selectedIds?.has(homeCardSelectionId(card)) ?? false),
        onToggleSelect
      },
      `${card.dir}/${card.file}`
    )) })
  ] });
}
function HomeArchiveView({ archive, onBack, onPreview }) {
  return /* @__PURE__ */ jsxs3("div", { className: "flex flex-1 flex-col gap-2 overflow-y-auto px-3 pb-3", children: [
    /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-2 pt-2", children: [
      /* @__PURE__ */ jsx3(
        "button",
        {
          type: "button",
          "data-wb-archive-back": true,
          className: "rounded border border-(--ui-stroke-secondary) px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)",
          onClick: onBack,
          children: "← 返回首页"
        }
      ),
      /* @__PURE__ */ jsx3("span", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "归档 / 回收站 · 全部" }),
      /* @__PURE__ */ jsxs3("span", { className: "text-[0.75rem] tabular-nums text-(--ui-text-quaternary)", children: [
        "已归档 ",
        archive.done.count,
        " · 回收站 ",
        archive.trash.count
      ] })
    ] }),
    /* @__PURE__ */ jsxs3("section", { className: "flex min-w-0 flex-col gap-1.5 rounded-lg border border-(--ui-stroke-secondary) p-2.5", children: [
      /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-1.5", children: [
        /* @__PURE__ */ jsx3("span", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "已完成归档" }),
        /* @__PURE__ */ jsx3("span", { className: "rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.6875rem] text-(--ui-text-quaternary)", children: "done 分区 · 完整列表" }),
        /* @__PURE__ */ jsxs3("span", { className: "text-[0.75rem] tabular-nums text-(--ui-text-quaternary)", children: [
          archive.done.count,
          " 项"
        ] })
      ] }),
      archive.done.entries.length === 0 ? /* @__PURE__ */ jsx3("div", { className: "rounded-md border border-dashed border-(--ui-stroke-tertiary) px-3 py-4 text-center text-[0.75rem] text-(--ui-text-quaternary)", children: "暂无已完成归档 —— 处理完的条目归档后会出现在这里" }) : /* @__PURE__ */ jsx3("div", { className: "flex flex-col gap-1.5", children: archive.done.entries.map(({ card }) => /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-1", children: [
        /* @__PURE__ */ jsx3(TodayCardRow, { card, onPreview }),
        /* @__PURE__ */ jsx3("span", { className: "shrink-0 rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.6875rem] text-(--ui-text-quaternary)", children: card.dir })
      ] }, `${card.dir}/${card.file}`)) })
    ] }),
    /* @__PURE__ */ jsxs3("section", { className: "flex min-w-0 flex-col gap-1.5 rounded-lg border border-(--ui-stroke-secondary) p-2.5", children: [
      /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-1.5", children: [
        /* @__PURE__ */ jsx3("span", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "回收站" }),
        /* @__PURE__ */ jsx3("span", { className: "rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.6875rem] text-(--ui-text-quaternary)", children: "trash 分区 · 完整列表" }),
        /* @__PURE__ */ jsxs3("span", { className: "text-[0.75rem] tabular-nums text-(--ui-text-quaternary)", children: [
          archive.trash.count,
          " 项"
        ] })
      ] }),
      archive.trash.entries.length === 0 ? /* @__PURE__ */ jsx3("div", { className: "rounded-md border border-dashed border-(--ui-stroke-tertiary) px-3 py-4 text-center text-[0.75rem] text-(--ui-text-quaternary)", children: "回收站是空的" }) : /* @__PURE__ */ jsx3("div", { className: "flex flex-col gap-1.5", children: archive.trash.entries.map(({ card }) => /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-1", children: [
        /* @__PURE__ */ jsx3(TodayCardRow, { card, onPreview }),
        /* @__PURE__ */ jsx3("span", { className: "shrink-0 rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.6875rem] text-(--ui-text-quaternary)", children: card.dir })
      ] }, `${card.dir}/${card.file}`)) })
    ] })
  ] });
}
function HomeMultiSelectActionBar({ presentation, busy, onSelectAll, onClear, onExit, onAction, failedDetail = [], overallError = null, staleSelection = [] }) {
  const mixedActions = presentation.batchActionEligibility ? HOME_BATCH_ACTIONS.filter((a) => (presentation.batchActionEligibility?.[a]?.ineligibleCount ?? 0) > 0) : [];
  return /* @__PURE__ */ jsxs3(
    "div",
    {
      "data-wb-multiselect-bar": true,
      className: "sticky bottom-0 z-30 mt-2 shrink-0 rounded-lg border border-(--ui-accent)/40 bg-(--ui-bg-elevated) px-2.5 py-2 shadow-lg",
      children: [
        /* @__PURE__ */ jsxs3("div", { className: "flex flex-wrap items-center gap-1.5 text-[0.75rem]", children: [
          /* @__PURE__ */ jsxs3("span", { className: "font-semibold tabular-nums text-(--ui-text-primary)", children: [
            "已选 ",
            presentation.multiSelectCount,
            " 项"
          ] }),
          presentation.multiSelectReadonlyCount > 0 && /* @__PURE__ */ jsxs3("span", { "data-wb-readonly-notice": true, className: "rounded bg-(--ui-bg-quinary) px-1.5 py-0.5 text-[0.6875rem] text-(--ui-text-quaternary)", children: [
            "已归档 ",
            presentation.multiSelectReadonlyCount,
            " 项只读，不可批处理"
          ] }),
          /* @__PURE__ */ jsx3("button", { type: "button", "data-wb-select-all-visible": true, disabled: busy, className: "rounded border border-(--ui-stroke-secondary) px-1.5 py-0.5 text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) disabled:opacity-40", onClick: onSelectAll, children: "全选当前可见" }),
          /* @__PURE__ */ jsx3("button", { type: "button", "data-wb-clear-selection": true, disabled: busy, className: "rounded border border-(--ui-stroke-secondary) px-1.5 py-0.5 text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) disabled:opacity-40", onClick: onClear, children: "清空" }),
          /* @__PURE__ */ jsx3("button", { type: "button", "data-wb-exit-multiselect": true, disabled: busy, className: "rounded border border-(--ui-stroke-secondary) px-1.5 py-0.5 text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) disabled:opacity-40", onClick: onExit, children: "退出多选" })
        ] }),
        /* @__PURE__ */ jsxs3("div", { className: "mt-1.5 flex flex-wrap items-center gap-1.5", children: [
          HOME_BATCH_ACTIONS.map((action) => {
            const elig = presentation.batchActionEligibility?.[action];
            const canSubmit = !!elig && elig.eligibleCount > 0 && elig.ineligibleCount === 0;
            return /* @__PURE__ */ jsxs3(
              "button",
              {
                type: "button",
                "data-wb-batch-action": action,
                disabled: !presentation.canSubmitBatch || busy || !canSubmit,
                onClick: () => onAction(action),
                className: "rounded border border-(--ui-accent)/40 bg-(--ui-accent)/10 px-2 py-1 text-[0.75rem] font-medium text-(--ui-accent) hover:bg-(--ui-accent)/20 disabled:opacity-40",
                children: [
                  HOME_BATCH_ACTION_LABEL[action],
                  " · ",
                  elig ? elig.eligibleCount : 0,
                  " 项",
                  elig && elig.ineligibleCount > 0 && /* @__PURE__ */ jsxs3("span", { "data-wb-ineligible-badge": true, className: "ml-1 rounded bg-(--ui-bg-quinary) px-1 text-[0.6875rem] text-[#f87171]", children: [
                    "不适用 ",
                    elig.ineligibleCount,
                    " 项"
                  ] })
                ]
              },
              action
            );
          }),
          busy && /* @__PURE__ */ jsx3("span", { className: "text-[0.75rem] text-(--ui-text-tertiary)", children: "提交中…" })
        ] }),
        mixedActions.length > 0 && /* @__PURE__ */ jsxs3("details", { "data-wb-ineligible-detail": true, className: "mt-1 text-[0.75rem] text-(--ui-text-tertiary)", children: [
          /* @__PURE__ */ jsxs3("summary", { className: "cursor-pointer", children: [
            "查看不适用项与原因（",
            mixedActions.length,
            " 个动作）"
          ] }),
          /* @__PURE__ */ jsx3("ul", { className: "mt-1 max-h-40 overflow-y-auto pl-4 text-[0.6875rem] text-(--ui-text-quaternary)", children: mixedActions.map((action) => {
            const elig = presentation.batchActionEligibility?.[action];
            if (!elig) return null;
            return /* @__PURE__ */ jsxs3("li", { className: "mt-0.5", children: [
              /* @__PURE__ */ jsx3("span", { className: "font-medium text-(--ui-text-secondary)", children: HOME_BATCH_ACTION_LABEL[action] }),
              " 不适用 ",
              elig.ineligibleCount,
              " 项：",
              /* @__PURE__ */ jsx3("ul", { className: "pl-3", children: elig.ineligible.slice(0, 12).map((i) => /* @__PURE__ */ jsxs3("li", { className: "mt-0.5", children: [
                i.dir,
                "/",
                i.file,
                " — ",
                i.reason
              ] }, i.id)) })
            ] }, action);
          }) })
        ] }),
        (failedDetail.length > 0 || overallError || staleSelection.length > 0) && /* @__PURE__ */ jsxs3("div", { "data-wb-batch-feedback": true, className: "mt-1.5 rounded-md border border-[#f87171]/40 bg-[#f87171]/10 px-2 py-1.5 text-[0.75rem] text-[#f87171]", children: [
          overallError && /* @__PURE__ */ jsx3("p", { className: "font-medium", children: overallError }),
          staleSelection.length > 0 && /* @__PURE__ */ jsx3("ul", { className: "mt-0.5 list-disc pl-4 text-[0.6875rem]", children: staleSelection.map((s) => /* @__PURE__ */ jsxs3("li", { className: "mt-0.5", children: [
            s.id,
            " — ",
            s.reason
          ] }, s.id)) }),
          failedDetail.length > 0 && /* @__PURE__ */ jsx3("ul", { className: "mt-0.5 list-disc pl-4 text-[0.6875rem]", children: failedDetail.map((f) => /* @__PURE__ */ jsxs3("li", { className: "mt-0.5", children: [
            f.dir,
            "/",
            f.file,
            " — ",
            f.reason
          ] }, f.id)) }),
          /* @__PURE__ */ jsx3("p", { className: "mt-0.5 text-[0.6875rem] opacity-80", children: "失败项仍保留在选中集，可修正选择后重试或退出。" })
        ] })
      ]
    }
  );
}
var HOME_EMPTY_HINTS = {
  today: "今天没有安排 🎉 手机转发到 QQ 群会自动收录进工作台",
  inbox: "待审核是空的——手机收进来的内容会先出现在这里等你过目",
  attention: "没有需要你拍板或修复的事情",
  recent: "还没有完成记录——处理完的第一件事会出现在这里"
};
function HomeView({ board, onPreview, onOpenLegacy }) {
  const [ignored, setIgnored] = useState2(/* @__PURE__ */ new Set());
  const [viewState, dispatchView] = useReducer(homeViewStateReducer, HOME_VIEW_INITIAL_STATE);
  const { data: brief } = useQuery2({
    queryKey: ["workbench", "brief"],
    queryFn: fetchBrief,
    staleTime: 30 * 60 * 1e3
  });
  const health = useQuery2({ queryKey: ["workbench", "health"], queryFn: fetchHealth, refetchInterval: 3e4 });
  const model = useMemo2(() => buildHomeModel(board), [board]);
  const presentation = useMemo2(() => buildHomeViewPresentation(model, viewState), [model, viewState]);
  const acceptBrief = async (card) => {
    if (card.type !== "new_task") return;
    try {
      const res = await ingestMessage(`brief-${Date.now()}`, "待验证", card.title);
      if (res.ok) {
        host2.notify({ kind: "success", message: "已加入待验证" });
        invalidateBoard();
        setIgnored((prev) => new Set(prev).add(card.title));
      } else {
        host2.notify({ kind: "warning", message: res.error || "采纳失败" });
      }
    } catch (err) {
      host2.notify({ kind: "error", message: String(err) });
    }
  };
  const visibleCards = (brief?.cards ?? []).filter((c) => !ignored.has(c.title)).slice(0, 5);
  const [searchQ, setSearchQ] = useState2("");
  const [debouncedQ, setDebouncedQ] = useState2("");
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(searchQ.trim()), 250);
    return () => window.clearTimeout(t);
  }, [searchQ]);
  const { data: searchData, isLoading: searchLoading, error: searchError } = useQuery2({
    queryKey: ["workbench", "home-search", debouncedQ],
    queryFn: () => fetchSearch(debouncedQ),
    enabled: debouncedQ.length > 0,
    retry: 1
  });
  const searchFeedback = homeSearchFeedback({
    hasQuery: debouncedQ.length > 0,
    isLoading: searchLoading,
    error: searchError,
    data: searchData ?? null
  });
  const openResult = (r) => {
    onPreview(r);
    setSearchQ("");
    setDebouncedQ("");
  };
  const todayRegion = presentation.regions.find((r) => r.id === "today");
  const inboxRegion = presentation.regions.find((r) => r.id === "inbox");
  const attentionRegion = presentation.regions.find((r) => r.id === "attention");
  const recentRegion = presentation.regions.find((r) => r.id === "recent");
  const mainRegions = [todayRegion, inboxRegion, attentionRegion];
  const showAllRegion = presentation.expandedRegion;
  const openShowAll = (regionId) => dispatchView({ type: "show-all", regionId });
  const [batchBusy, setBatchBusy] = useState2(false);
  const [pendingTrashUndo, setPendingTrashUndo] = useState2(null);
  const batchGateRef = useRef(new BatchGate());
  const [batchFeedback, setBatchFeedback] = useState2(null);
  const runBatch = async (action) => {
    if (!presentation.canSubmitBatch || batchBusy) return;
    const submission = buildHomeBatchSubmission(presentation.selectedIds, action, model);
    if (!submission) {
      const eligibility = computeBatchActionEligibility(model, presentation.selectedIds, action);
      const failed = presentation.selectedIds.map((id2) => {
        const hit = eligibility.ineligible.find((i) => i.id === id2);
        return { id: id2, dir: hit?.dir ?? "", file: hit?.file ?? id2, reason: hit?.reason ?? "该选择不可批处理（重复/未知/已移除），已保留" };
      });
      dispatchView({ type: "batch-settle", multiSelectOpen: true, selectedIds: presentation.selectedIds });
      setBatchFeedback({ failed, overall: "当前选择包含不可批处理的条目，未发送任何请求；选择已全部保留，可逐项处理" });
      return;
    }
    setBatchBusy(true);
    try {
      const outcome = await guardedSubmit(batchGateRef.current, async () => {
        try {
          const res = await batchAction(action, submission.items);
          return { transportError: void 0, response: res };
        } catch (err) {
          return { transportError: String(err), response: void 0 };
        }
      });
      if (outcome === null) return;
      if (outcome.transportError === void 0) {
        const decision = consumeBatchResponse(action, submission.items, outcome.response, {
          notify: (notice) => host2.notify(notice),
          invalidate: invalidateBoard,
          offerUndo: (receipt) => setPendingTrashUndo(receipt),
          replaceSelection: () => void 0,
          clearSelection: () => void 0,
          exitMultiMode: () => void 0
        });
        if (!decision.valid) {
          dispatchView({ type: "batch-settle", multiSelectOpen: true, selectedIds: presentation.selectedIds });
          setBatchFeedback({ failed: [], overall: decision.error });
          return;
        }
      }
      const settlement = settleBatchResponse(
        viewState,
        outcome.transportError !== void 0 ? { transportError: outcome.transportError } : outcome.response,
        presentation.selectedIds
      );
      if (settlement.settledCleanly) {
        dispatchView({ type: "batch-settled" });
        setBatchFeedback(null);
      } else {
        dispatchView({ type: "batch-settle", multiSelectOpen: settlement.keepOpen, selectedIds: settlement.selectedIds });
        setBatchFeedback(
          settlement.failedDetail.length > 0 || settlement.overallError ? { failed: settlement.failedDetail, overall: settlement.overallError } : null
        );
      }
    } finally {
      setBatchBusy(false);
    }
  };
  const runTrashUndo = async () => {
    if (!pendingTrashUndo || batchBusy) return;
    setBatchBusy(true);
    try {
      const result = await undoBatchTrash(pendingTrashUndo);
      consumeBatchUndoResponse(pendingTrashUndo, result, {
        notify: (notice) => host2.notify(notice),
        invalidate: invalidateBoard,
        clearReceipt: () => setPendingTrashUndo(null),
        retainReceipt: () => void 0
      });
    } catch (err) {
      host2.notify({ kind: "error", message: `撤销移入回收站失败，receipt 已保留：${String(err)}` });
    } finally {
      setBatchBusy(false);
    }
  };
  const selectedSet = useMemo2(() => new Set(presentation.selectedIds), [presentation.selectedIds]);
  const healthState = health.isLoading ? "loading" : health.error ? "unreachable" : !health.data || health.data.status === "green" || health.data.status === "disabled" ? "ok" : "degraded";
  return /* @__PURE__ */ jsxs3("div", { className: "flex flex-1 flex-col overflow-y-auto px-3 pb-3", children: [
    /* @__PURE__ */ jsx3("p", { className: "mt-2 px-1 text-[0.8125rem] text-(--ui-text-tertiary)", children: "手机收进来的东西，在这里审核、继续、沉淀。" }),
    pendingTrashUndo && /* @__PURE__ */ jsxs3("div", { "data-wb-home-trash-undo": true, className: "mt-2 flex items-center justify-between gap-2 rounded-lg border border-(--ui-accent)/40 bg-(--ui-bg-elevated) px-3 py-2", children: [
      /* @__PURE__ */ jsxs3("span", { className: "text-[0.8125rem] text-(--ui-text-secondary)", children: [
        "已批量移入回收站 ",
        pendingTrashUndo.items.length,
        " 项"
      ] }),
      /* @__PURE__ */ jsx3("button", { type: "button", disabled: batchBusy, onClick: runTrashUndo, className: "rounded border border-(--ui-accent)/50 px-2 py-1 text-[0.75rem] text-(--ui-text-primary) disabled:opacity-50", children: "撤销移入回收站" })
    ] }),
    /* @__PURE__ */ jsxs3("div", { className: "relative mt-1 px-1", children: [
      /* @__PURE__ */ jsx3(
        "input",
        {
          type: "text",
          "data-wb-home-search": true,
          value: searchQ,
          onChange: (e) => setSearchQ(e.target.value),
          onKeyDown: (e) => {
            if (e.key === "Escape") {
              setSearchQ("");
              setDebouncedQ("");
            }
          },
          placeholder: "搜索任务、内容、标签…",
          className: "h-8 w-full rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-3 text-[0.8125rem] text-(--ui-text-primary) placeholder:text-(--ui-text-quaternary) focus:border-(--ui-accent) focus:outline-none"
        }
      ),
      debouncedQ.length > 0 && searchFeedback.kind !== "idle" && /* @__PURE__ */ jsx3("div", { className: "absolute left-1 right-1 top-full z-40 mt-1 max-h-80 overflow-y-auto rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-1 text-[0.8125rem] shadow-lg", children: searchFeedback.kind === "results" && searchData ? searchData.results.map((r) => /* @__PURE__ */ jsxs3(
        "button",
        {
          type: "button",
          className: "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-(--ui-stroke-secondary)",
          onClick: () => openResult(searchResultToCard(r, board.root)),
          children: [
            /* @__PURE__ */ jsx3("span", { className: "shrink-0 text-[0.75rem] text-(--ui-text-tertiary)", children: r.dir }),
            /* @__PURE__ */ jsx3("span", { className: "min-w-0 flex-1 truncate font-medium text-(--ui-text-primary)", children: r.title }),
            r.tags.slice(0, 2).map((t) => /* @__PURE__ */ jsx3("span", { className: "shrink-0 rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)", children: t }, t))
          ]
        },
        `${r.dir}:${r.file}`
      )) : /* @__PURE__ */ jsxs3("div", { className: cn3(
        "px-2 py-2 text-[0.8125rem]",
        searchFeedback.kind === "unreachable" || searchFeedback.kind === "failure" || searchFeedback.kind === "timeout" ? "text-[#f87171]" : "text-(--ui-text-tertiary)"
      ), children: [
        searchFeedback.text,
        searchFeedback.retry && /* @__PURE__ */ jsx3(
          "button",
          {
            type: "button",
            className: "ml-2 rounded border border-(--ui-stroke-secondary) px-1.5 py-0.5 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)",
            onClick: () => setSearchQ((q) => q),
            children: "重试"
          }
        )
      ] }) })
    ] }),
    presentation.contractErrorBannerVisible && /* @__PURE__ */ jsxs3("div", { className: "mt-1 rounded-md border border-[#f87171]/40 bg-[#f87171]/10 px-3 py-1.5 text-[0.75rem] text-[#f87171]", children: [
      /* @__PURE__ */ jsx3(Codicon2, { name: "warning", size: "0.75rem", className: "mr-1 inline" }),
      "有 ",
      model.contractErrors.length,
      " 个条目的状态无法识别，已按契约隔离未显示在任何区。 请通过「旧版数据」查看原始状态并修正 frontmatter status 字段。"
    ] }),
    presentation.legacyFallbackVisible && /* @__PURE__ */ jsx3("div", { className: "mt-1 flex justify-end px-1", children: /* @__PURE__ */ jsx3("button", { "data-wb-legacy-fallback": true, className: "text-[0.75rem] text-(--ui-accent) hover:underline", onClick: onOpenLegacy, type: "button", children: "旧版数据 →" }) }),
    presentation.archiveEntryVisible && presentation.mode !== "archive" && !presentation.multiSelectOpen && /* @__PURE__ */ jsxs3("div", { className: "mt-1 flex items-center justify-end gap-2 px-1", children: [
      /* @__PURE__ */ jsx3(
        "button",
        {
          type: "button",
          "data-wb-multiselect-entry": true,
          className: "rounded border border-(--ui-accent)/40 bg-(--ui-accent)/10 px-2 py-0.5 text-[0.75rem] text-(--ui-accent) hover:bg-(--ui-accent)/20",
          onClick: () => dispatchView({ type: "enter-multiselect" }),
          children: "多选 / 批量处理"
        }
      ),
      /* @__PURE__ */ jsx3(
        "button",
        {
          type: "button",
          "data-wb-archive-entry": true,
          className: "text-[0.75rem] text-(--ui-accent) hover:underline",
          onClick: () => dispatchView({ type: "open-archive" }),
          children: "归档 / 回收站 →"
        }
      )
    ] }),
    presentation.mode === "expanded" && showAllRegion ? /* @__PURE__ */ jsx3(
      HomeAllRegionList,
      {
        region: showAllRegion,
        onBack: () => dispatchView({ type: "back" }),
        onPreview,
        multiSelectOpen: presentation.multiSelectOpen,
        selectedIds: selectedSet,
        onToggleSelect: (id2) => dispatchView({ type: "toggle-select", id: id2 })
      }
    ) : presentation.mode === "archive" && presentation.archive ? /* @__PURE__ */ jsx3(HomeArchiveView, { archive: presentation.archive, onBack: () => dispatchView({ type: "back" }), onPreview }) : /* @__PURE__ */ jsxs3("div", { className: "grid grid-cols-1 gap-3 py-3 lg:grid-cols-3", children: [
      mainRegions.map((region) => /* @__PURE__ */ jsxs3("section", { className: "flex min-w-0 flex-col gap-1.5 rounded-lg border border-(--ui-stroke-secondary) p-2.5", children: [
        /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-1.5", children: [
          /* @__PURE__ */ jsx3("span", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: region.id === "today" ? "今日" : region.id === "inbox" ? "待审核" : "需要注意" }),
          /* @__PURE__ */ jsx3("span", { className: "text-[0.75rem] tabular-nums text-(--ui-text-quaternary)", children: region.count }),
          region.id === "attention" && model.totals.attention.failures > 0 && /* @__PURE__ */ jsxs3("span", { className: "rounded bg-[#f87171]/15 px-1 text-[0.6875rem] text-[#f87171]", children: [
            "失败 ",
            model.totals.attention.failures
          ] })
        ] }),
        region.visibleItems.length === 0 ? /* @__PURE__ */ jsx3("div", { className: "rounded-md border border-dashed border-(--ui-stroke-tertiary) px-3 py-4 text-center text-[0.75rem] text-(--ui-text-quaternary)", children: HOME_EMPTY_HINTS[region.id] }) : /* @__PURE__ */ jsx3(
          HomeRegionCardList,
          {
            items: region.visibleItems,
            totalCount: region.items.length,
            canShowAll: region.canShowAll,
            onPreview,
            onShowAll: () => openShowAll(region.id),
            multiSelectOpen: presentation.multiSelectOpen,
            selectedIds: selectedSet,
            onToggleSelect: (id2) => dispatchView({ type: "toggle-select", id: id2 })
          }
        )
      ] }, region.id)),
      healthState !== "ok" && /* @__PURE__ */ jsxs3(
        "div",
        {
          className: healthState === "unreachable" ? "rounded-md border border-[#f87171]/40 bg-[#f87171]/10 px-3 py-1.5 text-[0.75rem] text-[#f87171]" : "rounded-md border border-[#fbbf24]/40 bg-[#fbbf24]/10 px-3 py-1.5 text-[0.75rem] text-[#fbbf24]",
          children: [
            healthState === "loading" && "链路健康检查中…",
            healthState === "unreachable" && "后端暂时不可达，健康状态与数据可能不是最新（稍后自动重试）。",
            healthState === "degraded" && `链路有点状况：${health.data?.label ?? "部分检查未通过"}${health.data?.last_error ? ` · 最近错误：${health.data.last_error.reason}` : ""}`
          ]
        }
      ),
      /* @__PURE__ */ jsxs3("section", { className: "flex min-w-0 flex-col gap-1.5 rounded-lg border border-(--ui-stroke-secondary) p-2.5 lg:col-span-3", children: [
        /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-1.5", children: [
          /* @__PURE__ */ jsx3("span", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "最近完成" }),
          /* @__PURE__ */ jsx3("span", { className: "text-[0.75rem] tabular-nums text-(--ui-text-quaternary)", children: recentRegion.count })
        ] }),
        recentRegion.visibleItems.length === 0 ? /* @__PURE__ */ jsx3("div", { className: "rounded-md border border-dashed border-(--ui-stroke-tertiary) px-3 py-4 text-center text-[0.75rem] text-(--ui-text-quaternary)", children: HOME_EMPTY_HINTS.recent }) : /* @__PURE__ */ jsx3(
          HomeRegionCardList,
          {
            items: recentRegion.visibleItems,
            totalCount: recentRegion.items.length,
            canShowAll: recentRegion.canShowAll,
            onPreview,
            onShowAll: () => openShowAll("recent"),
            multiSelectOpen: presentation.multiSelectOpen,
            selectedIds: selectedSet,
            onToggleSelect: (id2) => dispatchView({ type: "toggle-select", id: id2 })
          }
        )
      ] }),
      /* @__PURE__ */ jsxs3("section", { className: "flex flex-col gap-1.5 lg:col-span-3", children: [
        /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-1.5", children: [
          /* @__PURE__ */ jsx3("span", { className: "text-[0.8125rem] font-semibold text-(--ui-text-secondary)", children: "✨ 规则建议" }),
          /* @__PURE__ */ jsx3("span", { className: "text-[0.75rem] text-(--ui-text-quaternary)", children: "依据任务状态、截止日期和最近结果生成" })
        ] }),
        brief?.degraded ? /* @__PURE__ */ jsx3("div", { className: "rounded-md border border-(--ui-stroke-tertiary) px-2.5 py-2 text-[0.75rem] text-(--ui-text-quaternary)", children: "规则建议暂不可用，请稍后重试" }) : visibleCards.length === 0 ? /* @__PURE__ */ jsx3("div", { className: "px-1 text-[0.75rem] text-(--ui-text-quaternary)", children: "暂无建议" }) : visibleCards.map((c) => /* @__PURE__ */ jsx3(
          BriefCardView,
          {
            card: c,
            onAccept: c.type === "new_task" ? () => void acceptBrief(c) : void 0,
            onIgnore: () => setIgnored((prev) => new Set(prev).add(c.title))
          },
          c.title
        ))
      ] })
    ] }),
    presentation.mode !== "archive" && presentation.multiSelectOpen && /* @__PURE__ */ jsx3(
      HomeMultiSelectActionBar,
      {
        presentation,
        busy: batchBusy,
        failedDetail: batchFeedback?.failed ?? [],
        overallError: batchFeedback?.overall ?? null,
        staleSelection: presentation.staleSelection,
        onSelectAll: () => dispatchView({ type: "select-all-visible", ids: presentation.multiSelectVisibleIds }),
        onClear: () => dispatchView({ type: "clear-selection" }),
        onExit: () => dispatchView({ type: "exit-multiselect" }),
        onAction: runBatch
      }
    )
  ] });
}

// desktop-src/conversations.tsx
import { Codicon as Codicon3, host as host3 } from "@hermes/plugin-sdk";
import { useEffect as useEffect2, useRef as useRef2, useState as useState3 } from "react";

// desktop-src/clipboard.ts
function runtimeWriters() {
  const nativeWrite = window.hermesDesktop?.writeClipboard;
  const webWrite = navigator.clipboard?.writeText?.bind(navigator.clipboard);
  return { nativeWrite, webWrite };
}
async function writeWorkbenchClipboard(text, writers = runtimeWriters()) {
  if (!text) throw new Error("Clipboard text is empty");
  if (writers.nativeWrite) {
    await writers.nativeWrite(text);
    return;
  }
  if (writers.webWrite) {
    await writers.webWrite(text);
    return;
  }
  throw new Error("Clipboard API is unavailable");
}

// desktop-src/conversations.tsx
import { jsx as jsx4, jsxs as jsxs4 } from "react/jsx-runtime";
var platformLabel = (platform) => ({ qq: "QQ", weixin: "微信", messaging: "消息平台" })[platform] ?? platform;
function ConversationActionButton({ item }) {
  const primary = conversationPrimaryAction(item);
  const canOpen = primary.kind === "open_original";
  const [copyStatus, setCopyStatus] = useState3("idle");
  const resetTimer = useRef2(null);
  useEffect2(() => () => {
    if (resetTimer.current !== null) window.clearTimeout(resetTimer.current);
  }, []);
  const handleClick = async () => {
    if (canOpen) {
      host3.navigate("/" + encodeURIComponent(item.session_id));
      return;
    }
    try {
      await writeWorkbenchClipboard(`继续处理任务 ${item.task_id}：${item.summary}`);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("error");
    }
    if (resetTimer.current !== null) window.clearTimeout(resetTimer.current);
    resetTimer.current = window.setTimeout(() => setCopyStatus("idle"), 1800);
  };
  const label = canOpen ? primary.label : copyStatus === "copied" ? "已复制" : copyStatus === "error" ? "复制失败" : primary.label;
  return /* @__PURE__ */ jsx4("button", { type: "button", className: "rounded border border-(--ui-stroke-secondary) px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)", onClick: () => {
    void handleClick();
  }, title: canOpen ? "跳转到 Hermes 原会话" : copyStatus === "error" ? "剪贴板不可用，请稍后重试" : "复制续接摘要，可粘贴到任意新会话", children: label });
}
function ConversationIndexView({ items, loading, error }) {
  if (loading) return /* @__PURE__ */ jsx4("div", { className: "p-6 text-sm text-(--ui-text-tertiary)", children: "正在加载消息任务…" });
  if (error) return /* @__PURE__ */ jsx4("div", { className: "p-6 text-sm text-red-400", children: "消息任务加载失败，请稍后重试。" });
  if (!items.length) return /* @__PURE__ */ jsxs4("div", { className: "flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center", children: [
    /* @__PURE__ */ jsx4(Codicon3, { name: "comment-discussion", size: "1.5rem" }),
    /* @__PURE__ */ jsx4("div", { className: "text-sm font-medium", children: "暂无消息任务" }),
    /* @__PURE__ */ jsx4("div", { className: "max-w-lg text-[0.8125rem] text-(--ui-text-tertiary)", children: "从已授权的 QQ 或微信发送 /wb 任务后，会在这里生成脱敏索引。" })
  ] });
  return /* @__PURE__ */ jsxs4("div", { className: "flex flex-1 flex-col gap-2 overflow-y-auto p-3", children: [
    /* @__PURE__ */ jsx4("div", { className: "mb-1 text-[0.75rem] text-(--ui-text-tertiary)", children: "仅记录授权后创建的任务；原始用户与消息标识不会写入 Workbench。" }),
    items.map((item) => {
      return /* @__PURE__ */ jsx4("article", { className: "rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3", children: /* @__PURE__ */ jsxs4("div", { className: "flex items-start gap-3", children: [
        /* @__PURE__ */ jsx4("span", { className: "rounded bg-(--ui-stroke-secondary) px-2 py-0.5 text-[0.75rem] text-(--ui-text-secondary)", children: platformLabel(item.platform) }),
        /* @__PURE__ */ jsxs4("div", { className: "min-w-0 flex-1", children: [
          /* @__PURE__ */ jsx4("div", { className: "truncate text-sm font-medium", children: item.summary || "未命名消息任务" }),
          /* @__PURE__ */ jsxs4("div", { className: "mt-1 flex flex-wrap gap-x-3 text-[0.75rem] text-(--ui-text-tertiary)", children: [
            /* @__PURE__ */ jsxs4("span", { children: [
              "任务 ",
              item.task_id
            ] }),
            /* @__PURE__ */ jsx4("span", { children: item.status }),
            /* @__PURE__ */ jsx4("span", { children: item.updated_at.replace("T", " ") })
          ] })
        ] }),
        /* @__PURE__ */ jsx4(ConversationActionButton, { item })
      ] }) }, item.ref_id);
    })
  ] });
}

// desktop-src/board.tsx
import { Fragment as Fragment4, jsx as jsx5, jsxs as jsxs5 } from "react/jsx-runtime";
var executionDeps = {
  prepare: async (input) => {
    const result = await executeTask(input.dir, input.file, {
      title: input.title,
      content: input.content,
      due: input.due,
      launch: false
    });
    invalidateBoard();
    return result;
  },
  createSession: (input) => host4.request("session.create", input),
  bind: bindSession,
  submit: (runtimeSessionId, text) => host4.request("prompt.submit", {
    session_id: runtimeSessionId,
    text
  }),
  rollback: async (dir, file, reason) => {
    const result = await resetExecution(dir, file, reason);
    invalidateBoard();
    return result;
  }
};
function notifyExecutionFailure(result) {
  const rollbackNote = result.rollbackError ? `；自动恢复失败：${result.rollbackError}，请人工检查任务状态` : "；任务已恢复为待办";
  host4.notify({ kind: "error", message: `${result.error || "执行启动失败"}${rollbackNote}` });
}
var CardErrorBoundary = class extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return /* @__PURE__ */ jsx5("div", { className: "mb-1.5 rounded-md border border-(--ui-red) bg-(--ui-bg-elevated) p-2.5 text-[0.75rem] text-(--ui-red)", children: "卡片渲染失败（数据异常）" });
    }
    return this.props.children;
  }
};
function WbCardView({ card, sectionKey, onPreview, openMenuKey, onMenuOpenChange, multiMode, selected, onToggleSelect, conversationPlatforms, onOpenConversations }) {
  const meta = partitionMeta(sectionKey);
  const tone = STATUS_TONE[card.status] || "var(--ui-text-tertiary)";
  const tagFilter = useValue2($tagFilter);
  const menuKey = JSON.stringify([sectionKey, card.file, card.entry_title || ""]);
  const menuOpen = openMenuKey === menuKey;
  const menuTriggerRef = useRef3(null);
  const [menuPosition, setMenuPosition] = useState4(null);
  useEffect3(() => {
    if (!menuOpen || !menuTriggerRef.current) {
      setMenuPosition(null);
      return;
    }
    const updatePosition = () => {
      const rect = menuTriggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      if (rect.width === 0 || rect.height === 0) {
        setMenuPosition(null);
        return;
      }
      const menuWidth = 176;
      const gutter = 8;
      const placeRight = window.innerWidth - rect.right >= menuWidth + gutter;
      const left = placeRight ? rect.right + gutter : Math.max(gutter, rect.left - menuWidth - gutter);
      const top = Math.max(gutter, Math.min(rect.top, window.innerHeight - 420 - gutter));
      setMenuPosition({ left, top });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [menuOpen]);
  const [execOpen, setExecOpen] = useState4(false);
  const cardKey = JSON.stringify([card.dir, card.file, card.entry_title || ""]);
  const isSelected = selected.has(cardKey);
  const canArchive = canArchiveTask(sectionKey, card.status, card.execution_result || void 0);
  const mutOpts = {
    onError: (err) => host4.notify({ kind: "error", message: String(err) }),
    onSuccess: () => invalidateBoard()
  };
  const doComplete = useMutation2({ mutationFn: () => completeTask(card.dir, card.file), ...mutOpts });
  const doDefer = useMutation2({ mutationFn: () => deferTask(card.dir, card.file), ...mutOpts });
  const doAbandon = useMutation2({ mutationFn: () => abandonTask(card.dir, card.file), ...mutOpts });
  const doReopen = useMutation2({ mutationFn: () => reopenTask(card.dir, card.file), ...mutOpts });
  const doTrash = useMutation2({ mutationFn: () => trashFile(card.dir, card.file), ...mutOpts });
  const doDelete = useMutation2({ mutationFn: () => deleteFile(card.dir, card.file), ...mutOpts });
  const doRestore = useMutation2({ mutationFn: () => restoreFile(card.dir, card.file), ...mutOpts });
  const doResolve = useMutation2({
    mutationFn: () => resolveEntry(card.dir, card.file, card.entry_title ? { entry_title: card.entry_title } : void 0),
    ...mutOpts
  });
  const doToTask = useMutation2({
    mutationFn: () => toTask(card.dir, card.file, card.entry_title ? { entry_title: card.entry_title } : void 0),
    ...mutOpts
  });
  const [editOpen, setEditOpen] = useState4(false);
  const execTask = useCallback(async (overrides) => {
    const title = overrides?.title || card.title || card.file.replace(/\.md$/, "");
    if (!title) return;
    const result = await launchWorkbenchTask({
      dir: card.dir,
      file: card.file,
      title,
      path: card.path,
      ...overrides
    }, executionDeps);
    if (!result.ok || !result.storedSessionId) {
      notifyExecutionFailure(result);
      return;
    }
    host4.navigate("/" + encodeURIComponent(result.storedSessionId));
  }, [card]);
  const execAggregate = useCallback(async (overrides) => {
    const entryTitle = card.entry_title || "";
    if (!entryTitle) return;
    try {
      const converted = await toTask(card.dir, card.file, { entry_title: entryTitle });
      if (!converted.ok) {
        host4.notify({ kind: "error", message: converted.error || "转任务失败" });
        return;
      }
      const taskFile = converted.task_file || "";
      const taskTitle = overrides?.title || converted.task || entryTitle;
      if (!taskFile) {
        host4.notify({ kind: "error", message: "转任务失败：无任务文件" });
        return;
      }
      const result = await launchWorkbenchTask({
        dir: "任务",
        file: taskFile,
        title: taskTitle,
        path: card.path,
        ...overrides
      }, executionDeps);
      if (!result.ok || !result.storedSessionId) {
        notifyExecutionFailure(result);
        return;
      }
      host4.navigate("/" + encodeURIComponent(result.storedSessionId));
    } catch (err) {
      host4.notify({ kind: "error", message: String(err) });
    }
  }, [card]);
  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(card.path);
      host4.notify({ kind: "success", message: "路径已复制" });
    } catch {
      host4.notify({ kind: "error", message: "复制失败" });
    }
  };
  return /* @__PURE__ */ jsxs5(Fragment4, { children: [
    /* @__PURE__ */ jsxs5(
      "div",
      {
        className: cn4(
          "group relative mb-1.5 flex flex-col gap-1.5 rounded-md border border-(--ui-stroke-tertiary) border-l-2 bg-(--ui-bg-elevated) p-2.5 text-[0.75rem] transition-colors",
          multiMode ? "cursor-default" : "cursor-pointer hover:bg-primary/[0.06]",
          isSelected && "border-(--ui-accent) bg-[color-mix(in_srgb,var(--ui-accent)_10%,transparent)]"
        ),
        style: { borderLeftColor: meta.tone },
        onClick: () => {
          onMenuOpenChange(null);
          multiMode ? onToggleSelect(cardKey) : onPreview(card);
        },
        children: [
          multiMode && /* @__PURE__ */ jsx5(
            "span",
            {
              className: "absolute top-1 left-1 z-10 flex size-4 items-center justify-center rounded-full border text-[0.75rem]",
              style: isSelected ? { background: "var(--ui-accent)", borderColor: "var(--ui-accent)", color: "var(--ui-bg)" } : { borderColor: "var(--ui-stroke-secondary)", color: "transparent" },
              children: "✓"
            }
          ),
          /* @__PURE__ */ jsxs5("div", { className: "flex items-start justify-between gap-1", children: [
            /* @__PURE__ */ jsx5("span", { className: "line-clamp-2 flex-1 break-words font-medium leading-snug text-[0.9375rem]", children: card.title || card.file.replace(/\.md$/, "") }),
            /* @__PURE__ */ jsxs5("span", { className: "flex shrink-0 items-center gap-1 pr-5", children: [
              card.priority && priorityMeta(card.priority) && /* @__PURE__ */ jsx5(
                "span",
                {
                  className: "rounded px-1 text-[0.75rem] font-semibold",
                  style: {
                    backgroundColor: priorityMeta(card.priority).bg,
                    color: priorityMeta(card.priority).fg
                  },
                  children: card.priority
                }
              ),
              card.size && sizeMeta(card.size) && /* @__PURE__ */ jsx5(
                "span",
                {
                  className: "rounded border px-1 text-[0.75rem] font-medium",
                  style: { color: sizeMeta(card.size).fg, borderColor: sizeMeta(card.size).fg },
                  children: card.size
                }
              ),
              card.entry_count > 0 && /* @__PURE__ */ jsx5("span", { className: "rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)", children: card.entry_count })
            ] })
          ] }),
          card.tags && card.tags.length > 0 && /* @__PURE__ */ jsx5("div", { className: "mt-1 flex flex-wrap gap-1", children: card.tags.map((t) => /* @__PURE__ */ jsx5(
            "button",
            {
              type: "button",
              onClick: (e) => {
                e.stopPropagation();
                $tagFilter.set(tagFilter === t ? "" : t);
              },
              className: cn4(
                "rounded px-1 text-[0.75rem] leading-4 transition-colors",
                tagFilter === t ? "bg-(--ui-accent) text-(--ui-bg)" : "bg-(--ui-bg-elevated) text-(--ui-text-tertiary) hover:text-(--ui-accent)"
              ),
              children: t
            },
            t
          )) }),
          /* @__PURE__ */ jsxs5("div", { className: "mt-1 flex items-center gap-1.5 text-[0.75rem] text-(--ui-text-quaternary)", children: [
            /* @__PURE__ */ jsx5("span", { className: "inline-block h-1.5 w-1.5 rounded-full", style: { backgroundColor: tone } }),
            /* @__PURE__ */ jsx5("span", { children: card.status }),
            card.due && /* @__PURE__ */ jsxs5("span", { className: isOverdue(card.due) ? "font-semibold text-(--ui-red)" : void 0, children: [
              "· 截止 ",
              card.due,
              isOverdue(card.due) && " ⚠"
            ] }),
            card.status === "in_progress" && card.session_id && /* @__PURE__ */ jsx5("span", { children: "· ▶ 执行中" }),
            conversationPlatforms.length > 0 && /* @__PURE__ */ jsx5(
              "button",
              {
                type: "button",
                className: "ml-auto rounded bg-(--ui-accent)/10 px-1.5 py-0.5 text-(--ui-accent) hover:bg-(--ui-accent)/20",
                title: "查看消息任务",
                onClick: (event) => {
                  event.stopPropagation();
                  onOpenConversations();
                },
                children: conversationPlatforms.map((platform) => platform === "qq" ? "QQ" : platform === "weixin" ? "微信" : "消息").join(" · ")
              }
            )
          ] }),
          !multiMode && /* @__PURE__ */ jsx5("div", { className: "mt-1 flex items-center gap-1", children: sectionKey === "task" && card.status === "todo" ? /* @__PURE__ */ jsxs5(Fragment4, { children: [
            /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doComplete.mutate();
            }, type: "button", "aria-label": "归档", children: [
              /* @__PURE__ */ jsx5(Codicon4, { name: "check", size: "0.7rem" }),
              "归档"
            ] }),
            /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              setExecOpen(true);
            }, type: "button", "aria-label": "执行", children: [
              /* @__PURE__ */ jsx5(Codicon4, { name: "play", size: "0.7rem" }),
              "执行"
            ] })
          ] }) : canArchive ? /* @__PURE__ */ jsxs5(Fragment4, { children: [
            /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doComplete.mutate();
            }, type: "button", "aria-label": "归档", children: [
              /* @__PURE__ */ jsx5(Codicon4, { name: "check", size: "0.7rem" }),
              "归档"
            ] }),
            card.status === "in_progress" && card.session_id && /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              host4.navigate("/" + encodeURIComponent(card.session_id));
            }, type: "button", "aria-label": "打开会话", children: [
              /* @__PURE__ */ jsx5(Codicon4, { name: "link-external", size: "0.7rem" }),
              "打开会话"
            ] })
          ] }) : sectionKey === "task" && card.status === "abandoned" ? /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
            e.stopPropagation();
            doReopen.mutate();
          }, type: "button", "aria-label": "重新打开", children: [
            /* @__PURE__ */ jsx5(Codicon4, { name: "refresh", size: "0.7rem" }),
            "重新打开"
          ] }) : sectionKey === "done" && card.entry_count > 0 ? /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
            e.stopPropagation();
            doResolve.mutate();
          }, type: "button", "aria-label": "确认处理", children: [
            /* @__PURE__ */ jsx5(Codicon4, { name: "check", size: "0.7rem" }),
            "确认处理"
          ] }) : sectionKey === "done" ? /* @__PURE__ */ jsxs5(Fragment4, { children: [
            card.session_id && /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              host4.navigate("/" + encodeURIComponent(card.session_id));
            }, type: "button", "aria-label": "打开会话", children: [
              /* @__PURE__ */ jsx5(Codicon4, { name: "link-external", size: "0.7rem" }),
              "打开会话"
            ] }),
            /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doReopen.mutate();
            }, type: "button", "aria-label": "回到任务列表", children: [
              /* @__PURE__ */ jsx5(Codicon4, { name: "refresh", size: "0.7rem" }),
              "回到任务列表"
            ] })
          ] }) : sectionKey === "trash" ? /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
            e.stopPropagation();
            doRestore.mutate();
          }, type: "button", "aria-label": "还原", children: [
            /* @__PURE__ */ jsx5(Codicon4, { name: "refresh", size: "0.7rem" }),
            "还原"
          ] }) : card.entry_count > 0 ? /* @__PURE__ */ jsxs5(Fragment4, { children: [
            /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doResolve.mutate();
            }, type: "button", "aria-label": "确认处理", children: [
              /* @__PURE__ */ jsx5(Codicon4, { name: "check", size: "0.7rem" }),
              "确认处理"
            ] }),
            /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              setExecOpen(true);
            }, type: "button", "aria-label": "执行", children: [
              /* @__PURE__ */ jsx5(Codicon4, { name: "play", size: "0.7rem" }),
              "执行"
            ] }),
            /* @__PURE__ */ jsxs5("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doToTask.mutate();
            }, type: "button", "aria-label": "转任务", children: [
              /* @__PURE__ */ jsx5(Codicon4, { name: "arrow-right", size: "0.7rem" }),
              "转任务"
            ] })
          ] }) : null }),
          /* @__PURE__ */ jsx5(
            "button",
            {
              "data-wb-menu": true,
              ref: menuTriggerRef,
              className: cn4(
                "absolute right-1 top-1 block rounded p-0.5 text-(--ui-text-tertiary)",
                "hover:bg-(--ui-stroke-secondary)"
              ),
              onClick: (e) => {
                e.stopPropagation();
                onMenuOpenChange(menuOpen ? null : menuKey);
              },
              type: "button",
              "aria-label": "Actions",
              children: /* @__PURE__ */ jsx5(Codicon4, { name: "kebab-vertical", size: "0.75rem" })
            }
          ),
          menuOpen && menuPosition && /* @__PURE__ */ jsxs5(
            "div",
            {
              "data-wb-menu": true,
              "data-wb-menu-overlay": true,
              className: "wb-menu-overlay fixed z-[10020] max-w-[calc(100vw-1rem)] min-w-[10rem] rounded-lg border border-(--ui-stroke-secondary)\n                     bg-(--ui-bg-elevated) p-1 text-[0.8125rem] shadow-lg backdrop-blur-md",
              style: { left: menuPosition.left, top: menuPosition.top },
              onClick: (e) => e.stopPropagation(),
              children: [
                sectionKey === "task" && card.status === "todo" && /* @__PURE__ */ jsxs5(Fragment4, { children: [
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "check", label: "✓ 归档", onClick: () => {
                    doComplete.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "play", label: "▶ 执行", onClick: () => {
                    setExecOpen(true);
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "history", label: "↻ 顺延", onClick: () => {
                    doDefer.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "edit", label: "✎ 编辑", onClick: () => {
                    setEditOpen(true);
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "trash", label: "✖ 放弃", onClick: () => {
                    doAbandon.mutate();
                    onMenuOpenChange(null);
                  } })
                ] }),
                canArchive && card.status !== "todo" && /* @__PURE__ */ jsxs5(Fragment4, { children: [
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "check", label: "✓ 归档", onClick: () => {
                    doComplete.mutate();
                    onMenuOpenChange(null);
                  } }),
                  card.session_id && /* @__PURE__ */ jsx5(MenuBtn, { icon: "link-external", label: "▶ 打开会话", onClick: () => {
                    host4.navigate("/" + encodeURIComponent(card.session_id));
                    onMenuOpenChange(null);
                  } })
                ] }),
                sectionKey === "task" && card.status === "abandoned" && /* @__PURE__ */ jsx5(MenuBtn, { icon: "refresh", label: "↩ 重新打开", onClick: () => {
                  doReopen.mutate();
                  onMenuOpenChange(null);
                } }),
                sectionKey === "done" && /* @__PURE__ */ jsxs5(Fragment4, { children: [
                  card.session_id && /* @__PURE__ */ jsx5(MenuBtn, { icon: "link-external", label: "▶ 打开会话", onClick: () => {
                    host4.navigate("/" + encodeURIComponent(card.session_id));
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "refresh", label: "↩ 回到任务列表", onClick: () => {
                    doReopen.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "trash", label: "🗑 移到回收站", onClick: () => {
                    doTrash.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "trash", label: "🗑 永久删除", onClick: () => {
                    if (confirm("确定永久删除？不可恢复。")) {
                      doDelete.mutate();
                      onMenuOpenChange(null);
                    }
                  } })
                ] }),
                sectionKey === "trash" && /* @__PURE__ */ jsxs5(Fragment4, { children: [
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "refresh", label: "↩ 还原", onClick: () => {
                    doRestore.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "trash", label: "🗑 永久删除", onClick: () => {
                    if (confirm("确定永久删除？不可恢复。")) {
                      doDelete.mutate();
                      onMenuOpenChange(null);
                    }
                  } })
                ] }),
                sectionKey !== "task" && sectionKey !== "done" && sectionKey !== "trash" && card.entry_count > 0 && /* @__PURE__ */ jsxs5(Fragment4, { children: [
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "check", label: "✓ 确认处理", onClick: () => {
                    doResolve.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "play", label: "▶ 执行", onClick: () => {
                    setExecOpen(true);
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "arrow-right", label: "↻ 转任务", onClick: () => {
                    doToTask.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx5(MenuBtn, { icon: "edit", label: "✎ 编辑", onClick: () => {
                    setEditOpen(true);
                    onMenuOpenChange(null);
                  } })
                ] }),
                /* @__PURE__ */ jsx5(MenuBtn, { icon: "eye", label: "👁 预览", onClick: () => {
                  onPreview(card);
                  onMenuOpenChange(null);
                } }),
                /* @__PURE__ */ jsx5(MenuBtn, { icon: "file", label: "📂 复制路径", onClick: () => {
                  copyPath();
                  onMenuOpenChange(null);
                } })
              ]
            }
          )
        ]
      }
    ),
    execOpen && /* @__PURE__ */ jsx5(
      ExecEditDialog,
      {
        card,
        onClose: () => setExecOpen(false),
        onConfirm: (o) => {
          setExecOpen(false);
          card.entry_title ? execAggregate(o) : execTask(o);
        }
      }
    ),
    editOpen && /* @__PURE__ */ jsx5(
      EditDialog,
      {
        card,
        onClose: () => setEditOpen(false),
        onConfirm: async (o) => {
          setEditOpen(false);
          try {
            const res = await editEntry({ dir: card.dir, file: card.file, entry_title: card.entry_title || void 0, title: o.title, content: o.content, due: o.due });
            if (!res.ok) {
              host4.notify({ kind: "error", message: res.error || "保存失败" });
              return;
            }
            invalidateBoard();
            host4.notify({ kind: "success", message: "已保存" });
          } catch (err) {
            host4.notify({ kind: "error", message: String(err) });
          }
        }
      }
    )
  ] });
}
function MenuBtn({ icon, label, onClick }) {
  return /* @__PURE__ */ jsx5(
    "button",
    {
      className: "flex w-full items-center gap-2 rounded px-2 py-1 text-left text-(--ui-text-primary)\n                 hover:bg-(--ui-stroke-secondary)",
      onClick,
      type: "button",
      children: label
    }
  );
}
function WbSectionView({ section, onPreview, openMenuKey, onMenuOpenChange, multiMode, selected, onToggleSelect, conversationPlatformsByTask, onOpenConversations }) {
  const meta = partitionMeta(section.key);
  const label = section.label ?? meta.label;
  const collapsedOverride = useValue2($collapsedSections)[section.key];
  const [showAllArchived, setShowAllArchived] = useState4(true);
  const filterText = useValue2($filterText).toLowerCase();
  const tagFilter = useValue2($tagFilter);
  const showArchived = useValue2($showArchived);
  const dueFilter = useValue2($dueFilter);
  const todayLocal = useMemo3(() => {
    const n = /* @__PURE__ */ new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }, []);
  const expanded = useMemo3(() => {
    const out = [];
    for (const card of section.files) {
      if (card.entry_count > 0 && card.entries.length > 0) {
        for (const entry of card.entries) {
          out.push({ ...card, title: entry, entry_title: entry });
        }
      } else if (card.entry_count === 0 && section.key !== "task" && section.key !== "done" && section.key !== "trash") {
        continue;
      } else {
        out.push(card);
      }
    }
    return out;
  }, [section.files, section.key]);
  const filtered = useMemo3(() => {
    if (!filterText && (section.key === "done" || section.key === "trash") && !showArchived) {
      return [];
    }
    return expanded.filter(
      (c) => (tagFilter ? c.tags?.includes(tagFilter) ?? false : true) && (dueFilter === "all" ? true : c.due ? dueFilter === "today" ? c.due === todayLocal : c.due < todayLocal : false) && (!filterText || c.title.toLowerCase().includes(filterText) || c.file.toLowerCase().includes(filterText))
    );
  }, [expanded, filterText, tagFilter, dueFilter, todayLocal, showArchived, section.key]);
  const ARCHIVED_PREVIEW_LIMIT = 10;
  const archivedPreview = section.key === "done" || section.key === "trash";
  const visible = archivedPreview && !showAllArchived ? filtered.slice(0, ARCHIVED_PREVIEW_LIMIT) : filtered;
  const collapsed = collapsedOverride ?? filtered.length === 0;
  const toggleCollapse = () => {
    const current = $collapsedSections.get();
    $collapsedSections.set({ ...current, [section.key]: !collapsed });
  };
  const isAggregate = section.key === "thought" || section.key === "video" || section.key === "psych" || section.key === "dream";
  const cardCount = section.files.reduce(
    (n, f) => n + (isAggregate ? f.entry_count || 0 : f.entry_count > 0 ? f.entry_count : 1),
    0
  );
  if (!showArchived && (section.key === "done" || section.key === "trash") && filtered.length === 0) {
    return null;
  }
  if (collapsed) {
    return /* @__PURE__ */ jsxs5(
      "button",
      {
        type: "button",
        className: "wb-section--collapsed flex h-full w-8 shrink-0 flex-col items-center gap-1.5 rounded-lg p-2 transition-colors hover:bg-(--ui-stroke-secondary)",
        onClick: toggleCollapse,
        "aria-label": `展开${label}`,
        title: `展开${label}`,
        children: [
          /* @__PURE__ */ jsx5("span", { className: "grid h-5 shrink-0 place-items-center", children: /* @__PURE__ */ jsx5("span", { className: "size-1.5 rounded-full", style: { backgroundColor: meta.tone } }) }),
          /* @__PURE__ */ jsx5("span", { className: "text-[0.6875rem] font-medium uppercase tracking-wide text-(--ui-text-tertiary) [writing-mode:vertical-rl]", children: meta.label }),
          cardCount > 0 && /* @__PURE__ */ jsx5("span", { className: "text-[0.6875rem] tabular-nums text-(--ui-text-quaternary)", children: cardCount })
        ]
      }
    );
  }
  return /* @__PURE__ */ jsxs5("div", { className: "wb-section flex min-h-0 max-h-full shrink-0 flex-col rounded-lg p-2 transition-colors bg-[color-mix(in_srgb,var(--ui-bg-quinary)_50%,transparent)]", children: [
    /* @__PURE__ */ jsxs5(
      "button",
      {
        className: cn4(
          "flex h-6 items-center gap-1.5 rounded px-1 text-left",
          "text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)"
        ),
        onClick: toggleCollapse,
        type: "button",
        children: [
          /* @__PURE__ */ jsx5(Codicon4, { name: collapsed ? "chevron-right" : "chevron-down", size: "0.7rem" }),
          /* @__PURE__ */ jsx5("span", { className: "size-1.5 rounded-full", style: { backgroundColor: meta.tone } }),
          /* @__PURE__ */ jsx5("span", { className: "text-[0.8125rem] font-semibold", children: label }),
          /* @__PURE__ */ jsx5("span", { className: "ml-auto text-[0.75rem] tabular-nums text-(--ui-text-quaternary)", children: cardCount })
        ]
      }
    ),
    !collapsed && /* @__PURE__ */ jsxs5("div", { className: "flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto", children: [
      filtered.length === 0 && /* @__PURE__ */ jsx5("span", { className: "px-2 py-3 text-center text-[0.75rem] text-(--ui-text-quaternary)", children: "暂无条目" }),
      visible.map((card) => /* @__PURE__ */ jsx5(CardErrorBoundary, { children: /* @__PURE__ */ jsx5(
        WbCardView,
        {
          card,
          sectionKey: section.key,
          onPreview,
          openMenuKey,
          onMenuOpenChange,
          multiMode,
          selected,
          onToggleSelect,
          conversationPlatforms: card.task_id ? conversationPlatformsByTask.get(card.task_id) ?? [] : [],
          onOpenConversations
        }
      ) }, card.file + (card.entry_title || ""))),
      archivedPreview && filtered.length > ARCHIVED_PREVIEW_LIMIT && !showAllArchived && /* @__PURE__ */ jsxs5(
        "button",
        {
          type: "button",
          className: "rounded border border-(--ui-stroke-secondary) px-2 py-1 text-[0.6875rem] text-(--ui-text-secondary) hover:border-(--ui-accent) hover:text-(--ui-accent)",
          onClick: () => setShowAllArchived(true),
          children: [
            "显示全部（",
            filtered.length,
            " 条）"
          ]
        }
      )
    ] })
  ] });
}
function extractTaskBody(md) {
  const text = md.replace(/\r\n/g, "\n");
  const title = (text.match(/^#\s+(.+)$/m)?.[1] ?? "").trim();
  const esc = title ? title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") : "";
  let cleaned = text.replace(/^---[\s\S]*?^---\s*\n?/m, "");
  cleaned = cleaned.replace(/^---\n((?:[ \t]*[\w-]+:[^\n]*\n)+?)^---\s*$/gm, "");
  const SYS = /^##\s*(完成记录|处理记录|重新打开记录|执行记录|执行失败记录|原始消息)[\s\S]*?(?=^##\s|(?![\s\S]))/gm;
  cleaned = cleaned.replace(SYS, "").trim();
  cleaned = cleaned.replace(/^#\s+.+\n?/, "").trim();
  const MSG = /^##\s+[^\n]+\s*$[\s\S]*?(?=^##\s|(?![\s\S]))/gm;
  cleaned = cleaned.replace(MSG, (whole) => {
    const heading = whole.slice(0, whole.indexOf("\n")).trim();
    if (esc && heading === `## ${title}`) return "";
    if (/b23\.tv|(?:youtube\.com|youtu\.be)/i.test(heading)) return "";
    if (/(?:^|\n)[ \t]*(?:[-•*][ \t]*)?(?:URL|链接|来源)[ \t]*[:：]/.test(whole)) return "";
    return whole;
  }).trim();
  cleaned = cleaned.replace(/^---\s*$/gm, "").trim();
  cleaned = cleaned.replace(/^##\s+[^\n]*\n*(?=##\s|(?![\s\S]))/gm, "").trim();
  return cleaned;
}
function extractEntrySection(md, entryTitle) {
  const text = md.replace(/\r\n/g, "\n");
  const esc = entryTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = text.match(new RegExp(`^##\\s*${esc}\\s*$[\\s\\S]*?(?=^##\\s|(?![\\s\\S]))`, "m"));
  if (!m) return "";
  let sec = m[0];
  sec = sec.replace(/^---\n((?:[ \t]*[\w-]+:[^\n]*\n)+?)^---\s*$/gm, "");
  sec = sec.replace(/^---\s*$/gm, "");
  sec = sec.replace(/^[ \t]*(?:[-•*][ \t]*)?(?:原始消息|URL|链接|来源)[ \t]*[:：].*$/gm, "");
  sec = sec.trim();
  return /^##\s+[^\n]+$/.test(sec) ? "" : sec;
}
function ExecEditDialog({ card, onClose, onConfirm }) {
  const [title, setTitle] = useState4(card.title || card.file.replace(/\.md$/, ""));
  const [content, setContent] = useState4("");
  const [due, setDue] = useState4(card.due || "");
  const [rawBody, setRawBody] = useState4("");
  const [rawOriginal, setRawOriginal] = useState4("");
  const [editingRaw, setEditingRaw] = useState4(false);
  const [busy, setBusy] = useState4(false);
  useEffect3(() => {
    let cancelled = false;
    void fetchFile(card.dir, card.file).then((res) => {
      if (cancelled) return;
      const body = card.entry_title ? extractEntrySection(res?.content || "", card.entry_title) : extractTaskBody(res?.content || "");
      if (body) {
        setRawBody(body);
        setRawOriginal(body);
      }
    }).catch(() => {
    });
    return () => {
      cancelled = true;
    };
  }, [card.dir, card.file, card.entry_title]);
  const submit = async () => {
    const t = title.trim();
    if (!t) {
      host4.notify({ kind: "error", message: "标题不能为空" });
      return;
    }
    setBusy(true);
    try {
      if (!card.entry_title && editingRaw && rawBody.trim() !== rawOriginal.trim()) {
        const amendRes = await editEntry({ dir: card.dir, file: card.file, amend: true, content: rawBody.trim() });
        if (!amendRes.ok) {
          host4.notify({ kind: "error", message: `修正原文失败：${amendRes.error || "未知错误"}` });
          return;
        }
      }
      await onConfirm({ title: t, content: content.trim() || void 0, due: due.trim() || void 0 });
    } finally {
      setBusy(false);
    }
  };
  const field = "w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)";
  return /* @__PURE__ */ jsx5(Dialog, { open: true, onOpenChange: (o) => {
    if (!o) onClose();
  }, children: /* @__PURE__ */ jsxs5(
    DialogContent,
    {
      className: "wb-dialog",
      style: { width: "min(52rem, 94vw)", maxWidth: "94vw" },
      children: [
        /* @__PURE__ */ jsx5(DialogHeader, { children: /* @__PURE__ */ jsx5(DialogTitle, { children: "▶ 执行前编辑" }) }),
        /* @__PURE__ */ jsxs5("div", { className: "flex flex-col gap-2", children: [
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "标题",
            /* @__PURE__ */ jsx5("input", { className: field, value: title, onChange: (e) => setTitle(e.target.value) })
          ] }),
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "内容（执行前补充）",
            /* @__PURE__ */ jsx5("textarea", { className: field + " min-h-[5rem] resize-y", value: content, onChange: (e) => setContent(e.target.value), placeholder: "可选：补充执行要求（如「只研究，不摄入 Obsidian」）" })
          ] }),
          /* @__PURE__ */ jsx5("div", { className: "my-1 border-t border-(--ui-stroke-secondary)", "aria-hidden": "true" }),
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            /* @__PURE__ */ jsxs5("span", { className: "flex items-center justify-between", children: [
              "原始内容",
              editingRaw ? "（修正模式）" : "（只读）",
              card.entry_title ? /* @__PURE__ */ jsx5("span", { className: "text-[0.6875rem] text-(--ui-text-quaternary)", children: "条目内容（修正请用 ✎ 编辑）" }) : /* @__PURE__ */ jsx5(
                "button",
                {
                  type: "button",
                  className: "rounded border border-(--ui-stroke-secondary) px-2 py-0.5 text-[0.6875rem] text-(--ui-text-secondary) hover:border-(--ui-accent) hover:text-(--ui-accent)",
                  onClick: () => setEditingRaw((v) => !v),
                  children: editingRaw ? "完成修正" : "修正原文"
                }
              )
            ] }),
            editingRaw ? /* @__PURE__ */ jsx5(
              "textarea",
              {
                className: field + " min-h-[8rem] resize-y",
                value: rawBody,
                onChange: (e) => setRawBody(e.target.value)
              }
            ) : /* @__PURE__ */ jsx5("div", { className: field + " max-h-[12rem] overflow-y-auto whitespace-pre-wrap break-words", children: rawBody || "（无额外内容）" })
          ] }),
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "Due",
            /* @__PURE__ */ jsx5("input", { className: field, type: "date", value: due, onChange: (e) => setDue(e.target.value) })
          ] })
        ] }),
        /* @__PURE__ */ jsxs5(DialogFooter, { children: [
          /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", onClick: onClose, children: "取消" }),
          /* @__PURE__ */ jsx5(Button2, { size: "sm", onClick: submit, disabled: busy, children: busy ? "执行中…" : "确认执行" })
        ] })
      ]
    }
  ) });
}
function EditDialog({ card, onClose, onConfirm }) {
  const [title, setTitle] = useState4(card.title || card.file.replace(/\.md$/, ""));
  const [content, setContent] = useState4("");
  const [due, setDue] = useState4(card.due || "");
  const [busy, setBusy] = useState4(false);
  const submit = async () => {
    const t = title.trim();
    if (!t) {
      host4.notify({ kind: "error", message: "标题不能为空" });
      return;
    }
    setBusy(true);
    try {
      await onConfirm({ title: t, content: content.trim() || void 0, due: due.trim() || void 0 });
    } finally {
      setBusy(false);
    }
  };
  const field = "w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)";
  return /* @__PURE__ */ jsx5(Dialog, { open: true, onOpenChange: (o) => {
    if (!o) onClose();
  }, children: /* @__PURE__ */ jsxs5(
    DialogContent,
    {
      className: "wb-dialog",
      style: { width: "min(52rem, 94vw)", maxWidth: "94vw" },
      children: [
        /* @__PURE__ */ jsx5(DialogHeader, { children: /* @__PURE__ */ jsx5(DialogTitle, { children: "✎ 编辑" }) }),
        /* @__PURE__ */ jsxs5("div", { className: "flex flex-col gap-2", children: [
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "标题",
            /* @__PURE__ */ jsx5("input", { className: field, value: title, onChange: (e) => setTitle(e.target.value) })
          ] }),
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "内容（备注/补充）",
            /* @__PURE__ */ jsx5("textarea", { className: field + " min-h-[6rem] resize-y", value: content, onChange: (e) => setContent(e.target.value) })
          ] }),
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "Due",
            /* @__PURE__ */ jsx5("input", { className: field, type: "date", value: due, onChange: (e) => setDue(e.target.value) })
          ] })
        ] }),
        /* @__PURE__ */ jsxs5(DialogFooter, { children: [
          /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", onClick: onClose, children: "取消" }),
          /* @__PURE__ */ jsx5(Button2, { size: "sm", onClick: submit, disabled: busy, children: busy ? "保存中…" : "保存" })
        ] })
      ]
    }
  ) });
}
function DialogSelect({ value, onChange, options, placeholder }) {
  const [open, setOpen] = useState4(false);
  const ref = useRef3(null);
  useEffect3(() => {
    if (!open) return;
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  useEffect3(() => {
    setOpen(false);
  }, [value]);
  const current = options.find((o) => o.value === value);
  return /* @__PURE__ */ jsxs5("div", { className: "relative", ref, children: [
    /* @__PURE__ */ jsxs5(
      "button",
      {
        className: "flex w-full items-center justify-between rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none hover:border-(--ui-accent)",
        onClick: () => setOpen(!open),
        type: "button",
        "aria-haspopup": "listbox",
        "aria-expanded": open,
        children: [
          /* @__PURE__ */ jsx5("span", { className: "truncate", children: current ? current.label : placeholder || "" }),
          /* @__PURE__ */ jsx5(Codicon4, { name: open ? "chevron-up" : "chevron-down", size: "0.7rem" })
        ]
      }
    ),
    open && /* @__PURE__ */ jsx5(
      "div",
      {
        className: "absolute top-full left-0 z-50 mt-1 max-h-48 w-full overflow-y-auto rounded border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-1 shadow-lg",
        role: "listbox",
        children: options.map((o) => /* @__PURE__ */ jsx5(
          "button",
          {
            className: cn4(
              "flex w-full items-center rounded px-2 py-1 text-left text-[0.75rem]",
              o.value === value ? "bg-(--ui-accent)/10 text-(--ui-accent)" : "text-(--ui-text-primary) hover:bg-(--ui-stroke-secondary)"
            ),
            onPointerDown: (e) => {
              e.preventDefault();
              setOpen(false);
              onChange(o.value);
            },
            onClick: () => {
              setOpen(false);
              onChange(o.value);
            },
            type: "button",
            role: "option",
            "aria-selected": o.value === value,
            children: o.label
          },
          o.value
        ))
      }
    )
  ] });
}
var NEW_TASK_DIRS = [
  { value: "任务", label: "任务" },
  { value: "待验证", label: "待验证" },
  { value: "待回看", label: "待回看" },
  { value: "心理学随想", label: "心理学随想" },
  { value: "梦中的邮件", label: "梦中的邮件" }
];
function NewTaskDialog({ board, onClose }) {
  const [dir, setDir] = useState4("任务");
  const [title, setTitle] = useState4("");
  const [due, setDue] = useState4("");
  const [content, setContent] = useState4("");
  const [busy, setBusy] = useState4(false);
  const [suggestion, setSuggestion] = useState4(null);
  const [picked, setPicked] = useState4(/* @__PURE__ */ new Set());
  const knownTags = useMemo3(() => {
    const set = /* @__PURE__ */ new Set();
    for (const s of board.sections) for (const c of s.files) for (const t of c.tags || []) set.add(t);
    return Array.from(set);
  }, [board]);
  useEffect3(() => {
    if (!title.trim() && !content.trim()) {
      setSuggestion(null);
      return;
    }
    const timer = window.setTimeout(() => {
      setSuggestion(suggestTags(title, content, knownTags));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [title, content, knownTags]);
  const submit = async () => {
    const t = title.trim();
    if (!t) {
      host4.notify({ kind: "error", message: "标题不能为空" });
      return;
    }
    setBusy(true);
    try {
      const res = await addEntry({ dir, title: t, due: due || void 0, content: content.trim() || void 0 });
      if (!res.ok) {
        host4.notify({ kind: "error", message: res.error || "创建失败" });
        return;
      }
      if (picked.size > 0 && res.file) {
        const tags = Array.from(picked);
        const ed = await editEntry({ dir, file: res.file, tags });
        if (!ed.ok) host4.notify({ kind: "warning", message: "标签写入失败：" + (ed.error || "") });
      }
      invalidateBoard();
      onClose();
    } catch (err) {
      host4.notify({ kind: "error", message: String(err) });
    } finally {
      setBusy(false);
    }
  };
  const field = "w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)";
  return /* @__PURE__ */ jsx5(Dialog, { open: true, onOpenChange: (o) => {
    if (!o) onClose();
  }, children: /* @__PURE__ */ jsxs5(
    DialogContent,
    {
      className: "wb-dialog",
      style: { width: "min(52rem, 94vw)", maxWidth: "94vw" },
      children: [
        /* @__PURE__ */ jsx5(DialogHeader, { children: /* @__PURE__ */ jsx5(DialogTitle, { children: "＋ 新建任务" }) }),
        /* @__PURE__ */ jsxs5("div", { className: "flex flex-col gap-3", children: [
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "标题（必填）",
            /* @__PURE__ */ jsx5("input", { className: field, value: title, onChange: (e) => setTitle(e.target.value), placeholder: "任务标题", autoFocus: true })
          ] }),
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "分区",
            /* @__PURE__ */ jsx5(DialogSelect, { value: dir, onChange: setDir, options: NEW_TASK_DIRS, placeholder: "选择分区" })
          ] }),
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "Due（截止日期）",
            /* @__PURE__ */ jsx5("input", { className: field, type: "date", value: due, onChange: (e) => setDue(e.target.value) })
          ] }),
          /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "内容（可选）",
            /* @__PURE__ */ jsx5("textarea", { className: field + " min-h-24 resize-y", value: content, onChange: (e) => setContent(e.target.value), placeholder: "备注/要求…" })
          ] }),
          suggestion && (suggestion.tags.length > 0 || suggestion.low.length > 0) && /* @__PURE__ */ jsxs5("div", { className: "flex flex-wrap items-center gap-1.5", children: [
            /* @__PURE__ */ jsx5("span", { className: "text-[0.8125rem] text-(--ui-text-tertiary)", children: "✨ 建议标签：" }),
            suggestion.tags.map((tag) => {
              const active = picked.has(tag);
              return /* @__PURE__ */ jsx5(
                "button",
                {
                  className: cn4(
                    "rounded px-1.5 py-0.5 text-[0.8125rem] transition-colors",
                    active ? "bg-(--ui-accent) text-(--ui-bg)" : "bg-(--ui-bg-quinary) text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)"
                  ),
                  onClick: () => {
                    setPicked((prev) => {
                      const n = new Set(prev);
                      if (n.has(tag)) n.delete(tag);
                      else n.add(tag);
                      return n;
                    });
                  },
                  type: "button",
                  children: tag
                },
                tag
              );
            }),
            suggestion.low.length > 0 && /* @__PURE__ */ jsxs5("span", { className: "text-[0.8125rem] text-(--ui-text-quaternary)", children: [
              "建议标签：",
              suggestion.low.join(" "),
              "（可确认）"
            ] })
          ] })
        ] }),
        /* @__PURE__ */ jsxs5(DialogFooter, { children: [
          /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", onClick: onClose, children: "取消" }),
          /* @__PURE__ */ jsx5(Button2, { size: "sm", onClick: () => void submit(), disabled: busy, children: busy ? "创建中…" : "创建" })
        ] })
      ]
    }
  ) });
}
function WorkbenchBoardPage() {
  const { data: board, isLoading, error } = useQuery3({
    queryKey: BOARD_KEY,
    queryFn: () => fetchBoard(),
    refetchInterval: 3e4
  });
  const [previewCard, setPreviewCard] = useState4(null);
  const [openMenuKey, setOpenMenuKey] = useState4(null);
  useEffect3(() => {
    if (!openMenuKey) return;
    const onDown = (e) => {
      if (e.target instanceof Element && e.target.closest("[data-wb-menu]")) return;
      setOpenMenuKey(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [openMenuKey]);
  const [showNewTask, setShowNewTask] = useState4(false);
  const [showSettings, setShowSettings] = useState4(false);
  const [showHealthDetails, setShowHealthDetails] = useState4(false);
  useEffect3(() => {
    if (!showHealthDetails) return;
    const onPointerDown = (event) => {
      if (event.target instanceof Element && event.target.closest("[data-wb-health]")) return;
      setShowHealthDetails(false);
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") setShowHealthDetails(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [showHealthDetails]);
  const health = useQuery3({ queryKey: ["workbench", "health"], queryFn: fetchHealth, refetchInterval: 3e4 });
  const conversations = useQuery3({ queryKey: ["workbench", "conversations"], queryFn: fetchConversations, refetchInterval: 3e4 });
  const conversationPlatformsByTask = useMemo3(() => {
    const grouped = /* @__PURE__ */ new Map();
    for (const item of conversations.data?.items ?? []) {
      const platforms = grouped.get(item.task_id) ?? /* @__PURE__ */ new Set();
      platforms.add(item.platform);
      grouped.set(item.task_id, platforms);
    }
    return new Map(Array.from(grouped, ([taskId, platforms]) => [taskId, Array.from(platforms).sort()]));
  }, [conversations.data?.items]);
  const settings = useQuery3({ queryKey: ["workbench", "settings"], queryFn: fetchSettings });
  const dueFilter = useValue2($dueFilter);
  const [bannerDismissedDate, setBannerDismissedDate] = useState4(
    () => typeof localStorage === "undefined" ? "" : localStorage.getItem("wbDeliveryBannerDismissedDate") || ""
  );
  const [showLegacy, setShowLegacy] = useState4(false);
  const [showConversations, setShowConversations] = useState4(false);
  const viewMode = useValue2($viewMode);
  const setViewMode = (m) => $viewMode.set(m);
  const [multiMode, setMultiMode] = useState4(false);
  const [selected, setSelected] = useState4(/* @__PURE__ */ new Set());
  const [batchBusy, setBatchBusy] = useState4(false);
  const [pendingTrashUndo, setPendingTrashUndo] = useState4(null);
  const [searchQ, setSearchQ] = useState4("");
  const [debouncedQ, setDebouncedQ] = useState4("");
  const [searchOpen, setSearchOpen] = useState4(false);
  const searchRef = useRef3(null);
  useEffect3(() => {
    const t = setTimeout(() => setDebouncedQ(searchQ.trim()), 250);
    return () => clearTimeout(t);
  }, [searchQ]);
  useEffect3(() => {
    if (!searchOpen) return;
    const onDown = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) setSearchOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [searchOpen]);
  const { data: searchData } = useQuery3({
    queryKey: ["workbench", "search", debouncedQ],
    queryFn: () => fetchSearch(debouncedQ),
    enabled: debouncedQ.length > 0
  });
  const tagFilter = useValue2($tagFilter);
  const filterText = useValue2($filterText);
  const showArchived = useValue2($showArchived);
  const toCard = (r, root) => ({
    dir: r.dir,
    file: r.file,
    path: `${root.replace(/\/+$/, "")}/${r.dir}/${r.file}`,
    title: r.title,
    status: r.status,
    entries: [],
    entry_count: r.entry_count,
    priority: r.priority,
    size: r.size,
    tags: r.tags
  });
  const toggleSelect = (key) => setSelected((prev) => {
    const n = new Set(prev);
    if (n.has(key)) n.delete(key);
    else n.add(key);
    return n;
  });
  const runBatch = async (action) => {
    if (selected.size === 0) return;
    setBatchBusy(true);
    try {
      const items = Array.from(selected).map((k) => {
        const [dir, file, entry_title] = JSON.parse(k);
        return { dir, file, ...entry_title ? { entry_title } : {} };
      });
      const res = await batchAction(action, items);
      consumeLegacyBatchResponse(action, items, res, {
        notify: (notice) => host4.notify(notice),
        invalidate: invalidateBoard,
        offerUndo: (receipt) => setPendingTrashUndo(receipt),
        replaceSelection: (failedItems) => setSelected(new Set(failedItems.map((item) => JSON.stringify([
          item.dir,
          item.file,
          item.entry_title ?? ""
        ])))),
        clearSelection: () => setSelected(/* @__PURE__ */ new Set()),
        exitMultiMode: () => setMultiMode(false)
      });
    } catch (err) {
      host4.notify({ kind: "error", message: String(err) });
    } finally {
      setBatchBusy(false);
    }
  };
  const runTrashUndo = async () => {
    if (!pendingTrashUndo || batchBusy) return;
    setBatchBusy(true);
    try {
      const result = await undoBatchTrash(pendingTrashUndo);
      consumeBatchUndoResponse(pendingTrashUndo, result, {
        notify: (notice) => host4.notify(notice),
        invalidate: invalidateBoard,
        clearReceipt: () => setPendingTrashUndo(null),
        retainReceipt: () => void 0
      });
    } catch (err) {
      host4.notify({ kind: "error", message: String(err) });
    } finally {
      setBatchBusy(false);
    }
  };
  if (isLoading) {
    return /* @__PURE__ */ jsx5("div", { className: "flex h-full items-center justify-center text-sm text-(--ui-text-tertiary)", children: "加载中…" });
  }
  if (error) {
    return /* @__PURE__ */ jsx5("div", { className: "flex h-full items-center justify-center text-sm text-(--ui-red)", children: "后端不可达" });
  }
  if (!board) return null;
  const deliverMissing = settings.data?.ok === true && !settings.data.config.deliver_target;
  const showDeliveryBanner = !!deliverMissing && bannerDismissedDate !== board.today;
  const healthData = health.data;
  const healthDot = health.isLoading ? "bg-(--ui-stroke-secondary)" : healthData && (healthData.status === "green" || healthData.status === "yellow" || healthData.status === "red") ? { green: "bg-[#34d399]", yellow: "bg-[#fbbf24]", red: "bg-[#f87171]" }[healthData.status] : "bg-(--ui-stroke-secondary)";
  const checkTone = (status) => ({
    green: "bg-[#34d399]",
    yellow: "bg-[#fbbf24]",
    red: "bg-[#f87171]",
    disabled: "bg-[#94a3b8]"
  })[status];
  const healthLabel = health.isLoading ? "健康检查…" : health.error ? "暂时不可用" : { green: "一切正常", yellow: "有点状况", red: "暂时不可用", disabled: "健康检查…" }[healthData?.status ?? "disabled"];
  return /* @__PURE__ */ jsxs5("div", { className: "wb-root flex h-full flex-col", children: [
    showDeliveryBanner && /* @__PURE__ */ jsxs5("div", { className: "flex items-center gap-2 border-b border-[#fbbf24]/30 bg-[#fbbf24]/10 px-3 py-1.5 text-[0.75rem] text-[#fbbf24]", children: [
      /* @__PURE__ */ jsx5(Codicon4, { name: "warning", size: "0.8rem" }),
      /* @__PURE__ */ jsx5("span", { children: "投递目标未配置，日报/提醒不会发送到 QQ。" }),
      /* @__PURE__ */ jsx5(
        "button",
        {
          type: "button",
          className: "rounded border border-[#fbbf24]/40 px-1.5 py-0.5 hover:bg-[#fbbf24]/20",
          onClick: () => setShowSettings(true),
          children: "去设置"
        }
      ),
      /* @__PURE__ */ jsx5(
        "button",
        {
          type: "button",
          className: "text-[0.6875rem] text-[#fbbf24]/70 hover:text-[#fbbf24]",
          onClick: () => {
            setBannerDismissedDate(board.today);
            localStorage.setItem("wbDeliveryBannerDismissedDate", board.today);
          },
          children: "今日忽略"
        }
      )
    ] }),
    /* @__PURE__ */ jsxs5("div", { className: "flex items-center gap-2 border-b border-(--ui-stroke-secondary) px-3 py-2", children: [
      /* @__PURE__ */ jsx5(Codicon4, { name: "checklist", size: "1rem" }),
      /* @__PURE__ */ jsx5("span", { className: "text-sm font-semibold", children: "工作台" }),
      /* @__PURE__ */ jsxs5("div", { "data-wb-primary-nav": true, className: "flex items-center rounded-md border border-(--ui-stroke-secondary) p-0.5", children: [
        /* @__PURE__ */ jsx5(
          "button",
          {
            type: "button",
            className: cn4(
              "rounded px-2 py-0.5 text-[0.8125rem] transition-colors",
              !showLegacy && !showConversations ? "bg-(--ui-accent) text-white" : "text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)"
            ),
            onClick: () => {
              setShowLegacy(false);
              setShowConversations(false);
            },
            children: "首页"
          }
        ),
        /* @__PURE__ */ jsx5(
          "button",
          {
            type: "button",
            className: cn4(
              "rounded px-2 py-0.5 text-[0.8125rem] transition-colors",
              showConversations ? "bg-(--ui-accent) text-white" : "text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)"
            ),
            onClick: () => {
              setShowLegacy(false);
              setShowConversations(true);
            },
            children: "消息任务"
          }
        )
      ] }),
      /* @__PURE__ */ jsxs5(
        "button",
        {
          "data-wb-legacy-entry": true,
          type: "button",
          title: "兼容入口：保留完整列表、项目分组、批量操作与异常状态修复",
          "aria-pressed": showLegacy && !showConversations,
          className: cn4(
            "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[0.75rem] transition-colors",
            showLegacy && !showConversations ? "bg-(--ui-stroke-secondary) text-(--ui-text-primary)" : "text-(--ui-text-quaternary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-secondary)"
          ),
          onClick: () => {
            setShowLegacy(true);
            setShowConversations(false);
          },
          children: [
            /* @__PURE__ */ jsx5(Codicon4, { name: "archive", size: "0.65rem" }),
            "完整数据（兼容）"
          ]
        }
      ),
      /* @__PURE__ */ jsxs5("span", { className: "text-[0.75rem] text-(--ui-text-quaternary)", children: [
        board.totals.pending,
        " Pending / ",
        board.totals.total,
        " Total"
      ] }),
      /* @__PURE__ */ jsxs5("div", { className: "ml-auto flex items-center gap-2", children: [
        !multiMode && /* @__PURE__ */ jsxs5(Button2, { size: "sm", variant: "outline", onClick: () => {
          setSelected(/* @__PURE__ */ new Set());
          setMultiMode(true);
        }, children: [
          /* @__PURE__ */ jsx5(Codicon4, { name: "checklist", size: "0.7rem" }),
          /* @__PURE__ */ jsx5("span", { className: "ml-1", children: "批量" })
        ] }),
        /* @__PURE__ */ jsxs5(Button2, { size: "sm", onClick: () => setShowNewTask(true), children: [
          /* @__PURE__ */ jsx5(Codicon4, { name: "add", size: "0.7rem" }),
          /* @__PURE__ */ jsx5("span", { className: "ml-1", children: "新建任务" })
        ] }),
        /* @__PURE__ */ jsxs5("div", { className: "relative", ref: searchRef, children: [
          /* @__PURE__ */ jsx5(
            Input,
            {
              className: "h-7 w-52 text-[0.8125rem]",
              placeholder: "搜索…",
              value: searchQ,
              onChange: (e) => {
                setSearchQ(e.target.value);
                setSearchOpen(true);
              },
              onFocus: () => setSearchOpen(true),
              onKeyDown: (e) => {
                if (e.key === "Escape") {
                  setSearchQ("");
                  setSearchOpen(false);
                }
              }
            }
          ),
          searchOpen && debouncedQ && searchData && /* @__PURE__ */ jsx5("div", { className: "absolute right-0 top-full z-50 mt-1 max-h-80 w-72 overflow-y-auto rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-1 text-[0.8125rem] shadow-lg", children: searchData.results.length === 0 ? /* @__PURE__ */ jsx5("div", { className: "px-2 py-2 text-(--ui-text-tertiary)", children: "无匹配结果" }) : searchData.results.map((r) => /* @__PURE__ */ jsxs5(
            "button",
            {
              type: "button",
              className: "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-(--ui-stroke-secondary)",
              onPointerDown: () => {
                setPreviewCard(toCard(r, board.root));
                setSearchOpen(false);
              },
              children: [
                /* @__PURE__ */ jsx5("span", { className: "shrink-0 text-[0.75rem] text-(--ui-text-tertiary)", children: partitionMeta(r.key).label }),
                /* @__PURE__ */ jsx5("span", { className: "min-w-0 flex-1 truncate font-medium text-(--ui-text-primary)", children: r.title }),
                r.tags.slice(0, 2).map((t) => /* @__PURE__ */ jsx5("span", { className: "shrink-0 rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)", children: t }, t))
              ]
            },
            `${r.dir}:${r.file}`
          )) })
        ] }),
        tagFilter && /* @__PURE__ */ jsxs5(
          "button",
          {
            type: "button",
            className: "flex items-center gap-1 rounded-full bg-(--ui-accent)/15 px-2 py-0.5 text-[0.8125rem] text-(--ui-accent)",
            onClick: () => $tagFilter.set(""),
            children: [
              "#",
              tagFilter,
              /* @__PURE__ */ jsx5(Codicon4, { name: "close", size: "0.6rem" })
            ]
          }
        ),
        /* @__PURE__ */ jsx5(
          Input,
          {
            className: "h-7 w-44 text-[0.8125rem]",
            placeholder: "筛选…",
            value: filterText,
            onChange: (e) => $filterText.set(e.target.value)
          }
        ),
        /* @__PURE__ */ jsx5(
          Button2,
          {
            size: "sm",
            variant: "outline",
            onClick: () => $showArchived.set(!$showArchived.get()),
            children: showArchived ? "隐藏已归档" : "显示已归档"
          }
        ),
        /* @__PURE__ */ jsx5("div", { className: "flex items-center rounded-md border border-(--ui-stroke-secondary) p-0.5", children: [
          ["all", "全部"],
          ["today", "今天到期"],
          ["overdue", "已超期"]
        ].map(([key, label]) => /* @__PURE__ */ jsx5(
          "button",
          {
            type: "button",
            className: cn4(
              "rounded px-2 py-0.5 text-[0.75rem] transition-colors",
              dueFilter === key ? "bg-(--ui-accent) text-white" : "text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)"
            ),
            onClick: () => $dueFilter.set(key),
            children: label
          },
          key
        )) }),
        /* @__PURE__ */ jsxs5("div", { className: "relative", "data-wb-health": true, children: [
          /* @__PURE__ */ jsxs5(
            "button",
            {
              type: "button",
              className: "flex items-center gap-1 rounded px-1.5 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)",
              onClick: () => setShowHealthDetails((v) => !v),
              "aria-expanded": showHealthDetails,
              title: "查看链路健康详情",
              children: [
                /* @__PURE__ */ jsx5("span", { className: `size-2 rounded-full ${healthDot}` }),
                /* @__PURE__ */ jsx5("span", { children: healthLabel }),
                /* @__PURE__ */ jsx5(Codicon4, { name: showHealthDetails ? "chevron-up" : "chevron-down", size: "0.65rem" })
              ]
            }
          ),
          showHealthDetails && healthData && /* @__PURE__ */ jsxs5("div", { className: "wb-health-popover absolute right-0 top-full z-30 mt-1 w-72 rounded-md p-2 text-(--ui-text-primary)", children: [
            /* @__PURE__ */ jsxs5("div", { className: "mb-1.5 flex items-center justify-between text-[0.75rem] font-semibold text-(--ui-text-primary)", children: [
              /* @__PURE__ */ jsx5("span", { children: "链路健康详情" }),
              /* @__PURE__ */ jsx5("span", { className: "font-normal text-(--ui-text-quaternary)", children: healthData.ts })
            ] }),
            /* @__PURE__ */ jsx5("div", { className: "space-y-1", children: healthData.checks.map((check) => /* @__PURE__ */ jsxs5("div", { className: "flex items-start gap-2 rounded px-1.5 py-1 hover:bg-(--ui-bg-quaternary)", children: [
              /* @__PURE__ */ jsx5("span", { className: `mt-1 size-2 shrink-0 rounded-full ${checkTone(check.status)}` }),
              /* @__PURE__ */ jsxs5("div", { className: "min-w-0 flex-1", children: [
                /* @__PURE__ */ jsx5("div", { className: "text-[0.75rem] text-(--ui-text-primary)", children: check.label }),
                /* @__PURE__ */ jsx5("div", { className: "text-[0.6875rem] text-(--ui-text-tertiary)", children: check.detail })
              ] })
            ] }, check.id)) }),
            healthData.last_updated && /* @__PURE__ */ jsxs5("div", { className: "mt-1.5 border-t border-(--ui-stroke-secondary) pt-1.5 text-[0.6875rem] text-(--ui-text-quaternary)", children: [
              "最近状态更新：",
              healthData.last_updated.replace("T", " ")
            ] })
          ] })
        ] }),
        /* @__PURE__ */ jsxs5(Button2, { size: "sm", variant: "outline", onClick: () => setShowSettings(true), title: "工作台设置", children: [
          /* @__PURE__ */ jsx5(Codicon4, { name: "gear", size: "0.7rem" }),
          /* @__PURE__ */ jsx5("span", { className: "ml-1", children: "设置" })
        ] }),
        /* @__PURE__ */ jsx5(ViewSwitcher, { mode: viewMode, onChange: setViewMode })
      ] })
    ] }),
    multiMode && /* @__PURE__ */ jsxs5("div", { className: "flex items-center gap-2 border-b border-(--ui-stroke-secondary) bg-(--ui-accent)/5 px-3 py-1.5", children: [
      /* @__PURE__ */ jsxs5("span", { className: "text-[0.8125rem] text-(--ui-text-secondary)", children: [
        "已选 ",
        selected.size,
        " 项"
      ] }),
      /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", disabled: batchBusy || selected.size === 0, onClick: () => runBatch("complete"), children: "批量归档" }),
      /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", disabled: batchBusy || selected.size === 0, onClick: () => runBatch("resolve"), children: "批量归档" }),
      /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", disabled: batchBusy || selected.size === 0, onClick: () => runBatch("trash"), children: "批量移入回收站" }),
      /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", onClick: () => {
        setSelected(/* @__PURE__ */ new Set());
        setMultiMode(false);
      }, children: "取消" })
    ] }),
    pendingTrashUndo && /* @__PURE__ */ jsxs5("div", { className: "flex items-center gap-2 border-b border-(--ui-stroke-secondary) bg-(--ui-accent)/5 px-3 py-1.5", children: [
      /* @__PURE__ */ jsxs5("span", { className: "text-[0.8125rem] text-(--ui-text-secondary)", children: [
        "已移入回收站 ",
        pendingTrashUndo.items.length,
        " 项"
      ] }),
      /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", disabled: batchBusy, onClick: runTrashUndo, children: "撤销移入回收站" })
    ] }),
    showConversations ? /* @__PURE__ */ jsx5(
      ConversationIndexView,
      {
        items: conversations.data?.items ?? [],
        loading: conversations.isLoading,
        error: conversations.error
      }
    ) : !showLegacy ? /* @__PURE__ */ jsx5(HomeView, { board, onPreview: setPreviewCard, onOpenLegacy: () => setShowLegacy(true) }) : /* @__PURE__ */ jsxs5(Fragment4, { children: [
      viewMode === "table" && /* @__PURE__ */ jsx5(TableBoardView, { board, onPreview: setPreviewCard }),
      viewMode === "board" && /* @__PURE__ */ jsx5("div", { className: "flex flex-1 gap-3 overflow-x-auto p-3", children: board.sections.map((section) => /* @__PURE__ */ jsx5(
        WbSectionView,
        {
          section,
          onPreview: setPreviewCard,
          openMenuKey,
          onMenuOpenChange: setOpenMenuKey,
          multiMode,
          selected,
          onToggleSelect: toggleSelect,
          conversationPlatformsByTask,
          onOpenConversations: () => {
            setShowLegacy(false);
            setShowConversations(true);
          }
        },
        section.key
      )) })
    ] }),
    previewCard && /* @__PURE__ */ jsx5(WbPreviewDrawer, { card: previewCard, onClose: () => setPreviewCard(null) }),
    showNewTask && /* @__PURE__ */ jsx5(NewTaskDialog, { board, onClose: () => setShowNewTask(false) }),
    showSettings && /* @__PURE__ */ jsx5(SettingsDialog, { onClose: () => setShowSettings(false) })
  ] });
}
var PARTITION_TYPE_OPTIONS = [
  { value: "thought", label: "待验证类（聚合条目）" },
  { value: "video", label: "待回看类（聚合条目）" },
  { value: "task", label: "任务类（单卡）" },
  { value: "done", label: "归档类（单卡）" }
];
var SCHEDULE_ROWS = [
  { key: "daily_report", label: "每日日报", note: "数据 → 生成 → 工作日志 → QQ" },
  { key: "nudge", label: "超期提醒", note: "无内容不发送" },
  { key: "maintenance", label: "每日维护", note: "归档巡检 + DB 收敛 + 回收站 TTL" },
  { key: "lifecycle", label: "生命周期协调", note: "每 10 分钟" }
];
function SettingsDialog({ onClose }) {
  const field = "w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)";
  const { data, isLoading, error } = useQuery3({
    queryKey: ["workbench", "settings"],
    queryFn: () => fetchSettings()
  });
  const [form, setForm] = useState4(null);
  const [busy, setBusy] = useState4(false);
  const [newName, setNewName] = useState4("");
  const [newType, setNewType] = useState4("thought");
  const [restartHint, setRestartHint] = useState4([]);
  const [errMsg, setErrMsg] = useState4("");
  useEffect3(() => {
    if (data?.ok && data.config) {
      setForm(JSON.parse(JSON.stringify(data.config)));
    }
  }, [data]);
  if (!form) {
    return /* @__PURE__ */ jsx5(Dialog, { open: true, onOpenChange: (o) => {
      if (!o) onClose();
    }, children: /* @__PURE__ */ jsxs5(DialogContent, { className: "wb-dialog", style: { width: "min(52rem, 94vw)", maxWidth: "94vw" }, children: [
      /* @__PURE__ */ jsx5(DialogHeader, { children: /* @__PURE__ */ jsx5(DialogTitle, { children: "⚙ 工作台设置" }) }),
      /* @__PURE__ */ jsx5("div", { className: "flex items-center justify-center py-10 text-sm text-(--ui-text-tertiary)", children: isLoading ? "加载中…" : error ? "设置加载失败" : "" })
    ] }) });
  }
  const set = (k, v) => setForm((f) => f ? { ...f, [k]: v } : f);
  const setScheduler = (k, v) => setForm((f) => f ? { ...f, scheduler: { ...f.scheduler, [k]: { ...f.scheduler[k], ...v } } } : f);
  const addPartition = () => {
    const name = newName.trim();
    if (!name) return;
    if (form.partitions.some((p) => p.name === name)) {
      setErrMsg("分区名已存在");
      return;
    }
    setForm((f) => f ? { ...f, partitions: [...f.partitions, { name, type: newType, fixed: false, count: 0 }] } : f);
    setNewName("");
    setErrMsg("");
  };
  const removePartition = (name) => {
    setForm((f) => f ? { ...f, partitions: f.partitions.filter((p) => p.name !== name) } : f);
  };
  const save = async () => {
    if (!form) return;
    setBusy(true);
    setErrMsg("");
    try {
      const res = await saveSettings(form);
      if (!res.ok) {
        setErrMsg(res.error || "保存失败");
        return;
      }
      invalidateBoard();
      host4.notify({ kind: "success", message: "设置已保存" });
      if (res.restart_required?.length) {
        setRestartHint(res.restart_required);
      } else {
        onClose();
      }
    } catch (err) {
      setErrMsg(String(err));
    } finally {
      setBusy(false);
    }
  };
  return /* @__PURE__ */ jsx5(Dialog, { open: true, onOpenChange: (o) => {
    if (!o) onClose();
  }, children: /* @__PURE__ */ jsxs5(DialogContent, { className: "wb-dialog", style: { width: "min(52rem, 94vw)", maxWidth: "94vw" }, children: [
    /* @__PURE__ */ jsx5(DialogHeader, { children: /* @__PURE__ */ jsx5(DialogTitle, { children: "⚙ 工作台设置" }) }),
    /* @__PURE__ */ jsxs5("div", { className: "flex max-h-[70vh] flex-col gap-4 overflow-y-auto pr-1 text-[0.8125rem]", children: [
      /* @__PURE__ */ jsxs5("section", { children: [
        /* @__PURE__ */ jsxs5("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx5("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "路径" }),
          /* @__PURE__ */ jsx5("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "重启后生效" })
        ] }),
        /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-(--ui-text-secondary)", children: [
          "工作台文件夹",
          /* @__PURE__ */ jsx5("input", { className: field, value: form.root, onChange: (e) => set("root", e.target.value), placeholder: "~/Workbench" })
        ] }),
        /* @__PURE__ */ jsxs5("label", { className: "mt-2 flex flex-col gap-1 text-(--ui-text-secondary)", children: [
          "Obsidian 知识库（日报工作日志位置）",
          /* @__PURE__ */ jsx5("input", { className: field, value: form.vault, onChange: (e) => set("vault", e.target.value), placeholder: "Obsidian 库路径（可留空）" })
        ] })
      ] }),
      /* @__PURE__ */ jsxs5("section", { children: [
        /* @__PURE__ */ jsxs5("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx5("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "分区" }),
          /* @__PURE__ */ jsx5("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "新增即时生效" }),
          /* @__PURE__ */ jsx5("span", { className: "text-[0.6875rem] text-(--ui-text-quaternary)", children: "删除仅限空分区" })
        ] }),
        /* @__PURE__ */ jsx5("div", { className: "flex flex-col gap-1", children: form.partitions.map((p) => /* @__PURE__ */ jsxs5("div", { className: "flex items-center gap-2 rounded border border-(--ui-stroke-secondary) px-2 py-1", children: [
          /* @__PURE__ */ jsx5(Codicon4, { name: partitionMeta(p.type).codicon, size: "0.8rem" }),
          /* @__PURE__ */ jsx5("span", { className: "min-w-0 flex-1 truncate font-medium text-(--ui-text-primary)", children: p.name }),
          /* @__PURE__ */ jsx5("span", { className: "text-[0.6875rem] text-(--ui-text-quaternary)", children: partitionMeta(p.type).label }),
          p.fixed ? /* @__PURE__ */ jsx5("span", { className: "text-[0.6875rem] text-(--ui-text-quaternary)", children: "固定" }) : /* @__PURE__ */ jsx5(
            "button",
            {
              type: "button",
              disabled: p.count > 0,
              title: p.count > 0 ? `非空（${p.count} 个文件）不能删除` : "删除分区",
              className: "text-(--ui-text-tertiary) hover:text-(--ui-red) disabled:cursor-not-allowed disabled:opacity-40",
              onClick: () => removePartition(p.name),
              children: /* @__PURE__ */ jsx5(Codicon4, { name: "trash", size: "0.8rem" })
            }
          )
        ] }, p.name)) }),
        /* @__PURE__ */ jsxs5("div", { className: "mt-2 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx5("input", { className: field + " flex-1", value: newName, onChange: (e) => setNewName(e.target.value), placeholder: "新分区名（≤20 字）" }),
          /* @__PURE__ */ jsx5(DialogSelect, { value: newType, onChange: setNewType, options: PARTITION_TYPE_OPTIONS }),
          /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", onClick: addPartition, children: "＋ 添加" })
        ] })
      ] }),
      /* @__PURE__ */ jsxs5("section", { children: [
        /* @__PURE__ */ jsxs5("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx5("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "定时任务" }),
          /* @__PURE__ */ jsx5("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "立即生效" })
        ] }),
        /* @__PURE__ */ jsx5("div", { className: "flex flex-col gap-1.5", children: SCHEDULE_ROWS.map((row) => /* @__PURE__ */ jsxs5("div", { className: "flex items-center gap-2", children: [
          /* @__PURE__ */ jsx5(
            "input",
            {
              type: "checkbox",
              className: "size-3.5",
              checked: form.scheduler[row.key]?.enabled ?? true,
              onChange: (e) => setScheduler(row.key, { enabled: e.target.checked })
            }
          ),
          /* @__PURE__ */ jsx5("span", { className: "w-24 shrink-0 text-(--ui-text-primary)", children: row.label }),
          row.key !== "lifecycle" ? /* @__PURE__ */ jsx5(
            "input",
            {
              className: field + " w-24",
              type: "time",
              value: form.scheduler[row.key]?.time ?? "20:00",
              onChange: (e) => setScheduler(row.key, { time: e.target.value })
            }
          ) : /* @__PURE__ */ jsx5("span", { className: "w-24 text-[0.6875rem] text-(--ui-text-quaternary)", children: "每 10 分钟" }),
          /* @__PURE__ */ jsx5("span", { className: "min-w-0 truncate text-[0.6875rem] text-(--ui-text-quaternary)", children: row.note })
        ] }, row.key)) }),
        /* @__PURE__ */ jsxs5("label", { className: "mt-2 flex items-center gap-2 text-(--ui-text-secondary)", children: [
          /* @__PURE__ */ jsx5("input", { type: "checkbox", className: "size-3.5", checked: form.write_worklog, onChange: (e) => set("write_worklog", e.target.checked) }),
          "日报写入 Obsidian 工作日志"
        ] })
      ] }),
      /* @__PURE__ */ jsxs5("section", { children: [
        /* @__PURE__ */ jsxs5("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx5("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "QQ 投递" }),
          /* @__PURE__ */ jsx5("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "立即生效" })
        ] }),
        /* @__PURE__ */ jsxs5("label", { className: "flex flex-col gap-1 text-(--ui-text-secondary)", children: [
          "投递目标（qqbot:群 openid）",
          /* @__PURE__ */ jsx5("input", { className: field, value: form.deliver_target, onChange: (e) => set("deliver_target", e.target.value), placeholder: "qqbot:..." })
        ] })
      ] }),
      /* @__PURE__ */ jsxs5("section", { children: [
        /* @__PURE__ */ jsxs5("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx5("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "回收站保留" }),
          /* @__PURE__ */ jsx5("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "下次维护生效" })
        ] }),
        /* @__PURE__ */ jsxs5("div", { className: "flex items-center gap-2", children: [
          /* @__PURE__ */ jsx5(
            "input",
            {
              className: field + " w-24",
              type: "number",
              min: 1,
              max: 365,
              value: form.ttl.days,
              onChange: (e) => set("ttl", { ...form.ttl, days: Number(e.target.value) })
            }
          ),
          /* @__PURE__ */ jsx5("span", { className: "text-(--ui-text-secondary)", children: "天" }),
          /* @__PURE__ */ jsx5(
            DialogSelect,
            {
              value: form.ttl.mode,
              onChange: (m) => set("ttl", { ...form.ttl, mode: m }),
              options: [
                { value: "archive", label: "归档保留（移入已处理）" },
                { value: "delete", label: "物理删除" }
              ]
            }
          )
        ] })
      ] }),
      errMsg && /* @__PURE__ */ jsx5("div", { className: "rounded border border-(--ui-red) bg-(--ui-bg-elevated) px-2 py-1.5 text-[0.75rem] text-(--ui-red)", children: errMsg }),
      restartHint.length > 0 && /* @__PURE__ */ jsxs5("div", { className: "rounded border border-(--ui-accent)/30 bg-(--ui-accent)/5 px-2 py-1.5 text-[0.75rem] text-(--ui-text-secondary)", children: [
        "已保存。以下设置重启 Hermes 后生效：",
        restartHint.join("、"),
        "（路径 / 分区白名单）"
      ] })
    ] }),
    /* @__PURE__ */ jsxs5(DialogFooter, { children: [
      /* @__PURE__ */ jsx5(Button2, { size: "sm", variant: "outline", onClick: onClose, children: "取消" }),
      /* @__PURE__ */ jsx5(Button2, { size: "sm", onClick: save, disabled: busy, children: busy ? "保存中…" : "保存" })
    ] })
  ] }) });
}

// desktop-src/i18n.ts
var WB_LOCALES = {
  zh: {
    workbench: "工作台",
    pending: "待处理",
    total: "总计",
    sectionThought: "待验证",
    sectionVideo: "待回看",
    sectionTask: "任务",
    sectionPsych: "心理学随想",
    sectionDream: "梦中的邮件",
    sectionDone: "已处理",
    sectionTrash: "回收站",
    filter: "筛选…",
    showArchived: "显示已归档",
    hideArchived: "隐藏已归档",
    complete: "✓ 完成",
    resolve: "✓ 确认处理",
    toTask: "→ 转任务",
    defer: "↻ 顺延一天",
    abandon: "✖ 放弃",
    reopen: "↩ 重新打开",
    trash: "🗑 移入回收站",
    delete: "🗑 永久删除",
    restore: "↩ 还原",
    execute: "▶ 执行",
    preview: "预览",
    openFile: "📂 打开文件",
    noEntries: "暂无条目",
    loading: "加载中…",
    error: "后端不可达"
  },
  en: {
    workbench: "Workbench",
    pending: "Pending",
    total: "Total",
    sectionThought: "Inbox",
    sectionVideo: "Watch Later",
    sectionTask: "Tasks",
    sectionPsych: "Psychology",
    sectionDream: "Dream Mail",
    sectionDone: "Done",
    sectionTrash: "Trash",
    filter: "Filter…",
    showArchived: "Show archived",
    hideArchived: "Hide archived",
    complete: "✓ Complete",
    resolve: "✓ Resolve",
    toTask: "→ To Task",
    defer: "↻ Defer 1d",
    abandon: "✖ Abandon",
    reopen: "↩ Reopen",
    trash: "🗑 Move to Trash",
    delete: "🗑 Delete Permanently",
    restore: "↩ Restore",
    execute: "▶ Execute",
    preview: "Preview",
    openFile: "📂 Open File",
    noEntries: "No entries",
    loading: "Loading…",
    error: "Backend unreachable"
  }
};

// desktop-src/plugin.tsx
import { jsx as jsx6, jsxs as jsxs6 } from "react/jsx-runtime";
function WbStatusCount() {
  const { data: board } = useQuery4({
    queryFn: () => fetchBoard(),
    queryKey: BOARD_KEY,
    refetchInterval: 3e4
  });
  if (!board || board.totals.pending === 0) {
    return null;
  }
  return /* @__PURE__ */ jsx6(Tip2, { label: `${board.totals.pending} pending / ${board.totals.total} total`, children: /* @__PURE__ */ jsxs6(
    "button",
    {
      className: cn5(
        "inline-flex h-full items-center gap-1 rounded-none px-1.5 text-[0.6875rem] tabular-nums transition-colors",
        "text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground"
      ),
      onClick: () => host5.navigate("/workbench"),
      type: "button",
      children: [
        /* @__PURE__ */ jsx6(Codicon5, { name: "checklist", size: "0.7rem" }),
        /* @__PURE__ */ jsx6("span", { children: board.totals.pending })
      ]
    }
  ) });
}
var plugin = {
  id: "workbench-view",
  name: "Workbench",
  description: "7-partition task/file board — inbox, tasks, psychology, dreams, done, trash.",
  defaultEnabled: false,
  register(ctx) {
    ctx.i18n.register(WB_LOCALES);
    ctx.onDispose(bindApi(ctx.rest, ctx.storage, ctx.socket));
    ctx.registerMany([
      {
        id: "page",
        area: ROUTES_AREA,
        data: { path: "/workbench" },
        render: () => /* @__PURE__ */ jsx6(WorkbenchBoardPage, {})
      },
      {
        id: "nav",
        area: SIDEBAR_NAV_AREA,
        order: 45,
        data: { codicon: "checklist", label: "Workbench", path: "/workbench" }
      },
      {
        id: "count",
        area: STATUSBAR_AREAS.right,
        order: 80,
        render: () => /* @__PURE__ */ jsx6(WbStatusCount, {})
      },
      {
        id: "open",
        area: PALETTE_AREA,
        data: {
          id: "workbench.open",
          label: "Workbench: Open board",
          keywords: ["workbench", "board", "tasks", "inbox"],
          run: () => host5.navigate("/workbench")
        }
      },
      {
        id: "toggle-archived",
        area: PALETTE_AREA,
        data: {
          id: "workbench.toggleArchived",
          label: "Workbench: Toggle archived sections",
          keywords: ["workbench", "archived", "done", "trash"],
          run: () => $showArchived.set(!$showArchived.get())
        }
      },
      {
        id: "filter",
        area: PALETTE_AREA,
        data: {
          id: "workbench.filter",
          label: "Workbench: Filter cards...",
          keywords: ["workbench", "filter", "search"],
          run: () => {
            const input = prompt("Filter workbench cards:");
            if (input !== null) $filterText.set(input);
          }
        }
      },
      {
        id: "new-task",
        area: KEYBINDS_AREA,
        data: {
          id: "workbench.openBoard",
          category: "view",
          // Task 5.2 批次 1: aligned to official kanban (Ctrl+Alt+N on Win / Cmd+Alt+N on Mac).
          // Note: previous binding was mod+alt+w; changed per kanban convention.
          defaults: ["mod+alt+n"],
          label: "Workbench: Open board",
          run: () => host5.navigate("/workbench")
        }
      }
    ]);
  }
};
var plugin_default = plugin;
export {
  plugin_default as default
};
