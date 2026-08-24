// desktop-src/workbench.css
var id = "hermes-plugin-style-workbench-view";
var node = document.getElementById(id);
if (!node) {
  node = document.createElement("style");
  node.id = id;
  document.head.appendChild(node);
}
node.textContent = "/* Workbench plugin styles */\n.wb-root {\n  font-size: 0.875rem;\n  line-height: 1.55;\n}\n\n.wb-column {\n  scrollbar-width: thin;\n}\n\n.wb-card {\n  transition: border-color 0.15s ease, box-shadow 0.15s ease;\n}\n\n/* 2026-08-22 等宽看板（已拍板）：展开列固定 16rem。\n   宿主 Tailwind 不含 w-[16rem]/min-w-[14rem]/max-w-[18rem] 等任意值规则\n   （已核验 dist CSS 无此类），此前列宽实为内容自适应 → 待验证区内容多被撑宽。\n   宽度写在本文件（构建时内联注入，100% 生效），不依赖宿主工具类。 */\n.wb-section {\n  width: 16rem;\n  min-width: 16rem;\n  max-width: 16rem;\n}\n\n/* 2026-08-22 弹窗尺寸修复：宿主 Tailwind 无 w-[min(52rem,94vw)] 规则\n   （已核验 dist CSS），此前弹窗落回 SDK 默认 max-w-lg(32rem) 小窗。\n   宽度写在本文件，构建时内联注入，100% 生效。 */\n.wb-dialog {\n  width: min(52rem, 94vw);\n  max-width: 94vw;\n}\n\n/* Compact rails keep inactive partitions visible without competing with the\n   Bots sidebar or the right-docked Cronjobs pane. */\n.wb-section--collapsed {\n  min-width: 2rem;\n  max-width: 2rem;\n  background-color: color-mix(in srgb, var(--ui-bg-quinary) 78%, var(--ui-bg));\n  border: 1px solid color-mix(in srgb, var(--ui-stroke-secondary) 82%, transparent);\n  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ui-bg) 18%, transparent);\n}\n\n/* Action menus are viewport overlays; the explicit z-index also clears the\n   Cronjobs pane's right-docked surface. */\n.wb-menu-overlay {\n  position: fixed;\n  z-index: 10020;\n}\n\n/* Pending badge pulse */\n@keyframes wb-pulse {\n  0%, 100% { opacity: 1; }\n  50% { opacity: 0.5; }\n}\n\n.wb-pending-badge {\n  animation: wb-pulse 2s ease-in-out infinite;\n}\n";

// desktop-src/plugin.tsx
import {
  cn as cn4,
  Codicon as Codicon3,
  host as host3,
  KEYBINDS_AREA,
  PALETTE_AREA,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  STATUSBAR_AREAS,
  Tip as Tip2,
  useQuery as useQuery3
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
var fetchBoard = () => call("/board");
var fetchFile = (dir, file) => call(`/file?dirname=${encodeURIComponent(dir)}&filename=${encodeURIComponent(file)}`);
var fetchRecentEvents = (dir, file) => call(
  `/recent?limit=50&dir=${encodeURIComponent(dir)}&file=${encodeURIComponent(file)}`
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

// desktop-src/board.tsx
import {
  Button as Button2,
  cn as cn3,
  Codicon as Codicon2,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  host as host2,
  Input,
  useMutation,
  useQuery as useQuery2,
  useValue as useValue2
} from "@hermes/plugin-sdk";
import { Component, useCallback, useEffect, useMemo as useMemo2, useRef, useState as useState2 } from "react";

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
import { Button, cn, host, useQuery } from "@hermes/plugin-sdk";
import { useState } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
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
  const { data, isLoading, error } = useQuery({
    queryKey: FILE_KEY(card.dir, card.file),
    queryFn: () => fetchFile(card.dir, card.file),
    enabled: true
  });
  const { data: events, isLoading: evLoading } = useQuery({
    queryKey: RECENT_EVENTS_KEY(card.dir, card.file),
    queryFn: () => fetchRecentEvents(card.dir, card.file),
    enabled: tab === "history"
  });
  const tabBtn = (active) => cn(
    "cursor-pointer rounded px-2 py-1 text-[0.8125rem] transition-colors",
    active ? "bg-(--ui-accent)/15 text-(--ui-accent)" : "text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary)"
  );
  return /* @__PURE__ */ jsx(
    "div",
    {
      className: cn(
        "fixed inset-0 z-[10001] flex items-center justify-center bg-black/40"
      ),
      onClick: onClose,
      children: /* @__PURE__ */ jsxs(
        "div",
        {
          className: "flex h-[80vh] w-[560px] max-w-[92vw] flex-col rounded-xl border border-(--ui-stroke-secondary)\n                   bg-(--ui-bg-elevated) p-5 text-(--ui-text-primary) shadow-[0_20px_60px_rgba(0,0,0,0.5)]",
          onClick: (e) => e.stopPropagation(),
          role: "dialog",
          "aria-modal": "true",
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
            tab === "preview" ? /* @__PURE__ */ jsxs("div", { className: "flex-1 overflow-y-auto whitespace-pre-wrap text-[0.75rem] leading-relaxed", children: [
              isLoading && /* @__PURE__ */ jsx("div", { className: "flex h-full items-center justify-center text-(--ui-text-tertiary)", children: "加载中…" }),
              error && /* @__PURE__ */ jsx("div", { className: "flex h-full items-center justify-center text-(--ui-text-danger)", children: "加载失败" }),
              data && /* @__PURE__ */ jsx(PreviewBody, { content: data.content || "（空）", focusTitle: card.entry_title || null })
            ] }) : /* @__PURE__ */ jsxs("div", { className: "flex-1 overflow-y-auto text-[0.8125rem]", children: [
              evLoading && /* @__PURE__ */ jsx("div", { className: "flex h-full items-center justify-center text-(--ui-text-tertiary)", children: "加载中…" }),
              !evLoading && (!events || events.entries.length === 0) && /* @__PURE__ */ jsx("div", { className: "flex h-full items-center justify-center text-(--ui-text-quaternary)", children: "暂无运行历史" }),
              !evLoading && events && events.entries.length > 0 && /* @__PURE__ */ jsx("ul", { className: "flex flex-col gap-1", children: events.entries.map((e) => /* @__PURE__ */ jsxs(
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
    }
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
                /* @__PURE__ */ jsxs2("td", { className: cn2("px-2 py-1.5 whitespace-nowrap", isOverdue(card.due) ? "font-semibold text-(--ui-text-danger)" : "text-(--ui-text-secondary)"), children: [
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

// desktop-src/board.tsx
import { Fragment as Fragment3, jsx as jsx3, jsxs as jsxs3 } from "react/jsx-runtime";
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
  createSession: (input) => host2.request("session.create", input),
  bind: bindSession,
  submit: (runtimeSessionId, text) => host2.request("prompt.submit", {
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
  host2.notify({ kind: "error", message: `${result.error || "执行启动失败"}${rollbackNote}` });
}
var CardErrorBoundary = class extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return /* @__PURE__ */ jsx3("div", { className: "mb-1.5 rounded-md border border-(--ui-stroke-danger) bg-(--ui-bg-elevated) p-2.5 text-[0.75rem] text-(--ui-text-danger)", children: "卡片渲染失败（数据异常）" });
    }
    return this.props.children;
  }
};
function WbCardView({ card, sectionKey, onPreview, openMenuKey, onMenuOpenChange, multiMode, selected, onToggleSelect }) {
  const meta = partitionMeta(sectionKey);
  const tone = STATUS_TONE[card.status] || "var(--ui-text-tertiary)";
  const tagFilter = useValue2($tagFilter);
  const menuKey = JSON.stringify([sectionKey, card.file, card.entry_title || ""]);
  const menuOpen = openMenuKey === menuKey;
  const menuTriggerRef = useRef(null);
  const [menuPosition, setMenuPosition] = useState2(null);
  useEffect(() => {
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
  const [execOpen, setExecOpen] = useState2(false);
  const cardKey = JSON.stringify([card.dir, card.file, card.entry_title || ""]);
  const isSelected = selected.has(cardKey);
  const canArchive = canArchiveTask(sectionKey, card.status, card.execution_result || void 0);
  const mutOpts = {
    onError: (err) => host2.notify({ kind: "error", message: String(err) }),
    onSuccess: () => invalidateBoard()
  };
  const doComplete = useMutation({ mutationFn: () => completeTask(card.dir, card.file), ...mutOpts });
  const doDefer = useMutation({ mutationFn: () => deferTask(card.dir, card.file), ...mutOpts });
  const doAbandon = useMutation({ mutationFn: () => abandonTask(card.dir, card.file), ...mutOpts });
  const doReopen = useMutation({ mutationFn: () => reopenTask(card.dir, card.file), ...mutOpts });
  const doTrash = useMutation({ mutationFn: () => trashFile(card.dir, card.file), ...mutOpts });
  const doDelete = useMutation({ mutationFn: () => deleteFile(card.dir, card.file), ...mutOpts });
  const doRestore = useMutation({ mutationFn: () => restoreFile(card.dir, card.file), ...mutOpts });
  const doResolve = useMutation({
    mutationFn: () => resolveEntry(card.dir, card.file, card.entry_title ? { entry_title: card.entry_title } : void 0),
    ...mutOpts
  });
  const doToTask = useMutation({
    mutationFn: () => toTask(card.dir, card.file, card.entry_title ? { entry_title: card.entry_title } : void 0),
    ...mutOpts
  });
  const [editOpen, setEditOpen] = useState2(false);
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
    host2.navigate("/" + encodeURIComponent(result.storedSessionId));
  }, [card]);
  const execAggregate = useCallback(async (overrides) => {
    const entryTitle = card.entry_title || "";
    if (!entryTitle) return;
    try {
      const converted = await toTask(card.dir, card.file, { entry_title: entryTitle });
      if (!converted.ok) {
        host2.notify({ kind: "error", message: converted.error || "转任务失败" });
        return;
      }
      const taskFile = converted.task_file || "";
      const taskTitle = overrides?.title || converted.task || entryTitle;
      if (!taskFile) {
        host2.notify({ kind: "error", message: "转任务失败：无任务文件" });
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
      host2.navigate("/" + encodeURIComponent(result.storedSessionId));
    } catch (err) {
      host2.notify({ kind: "error", message: String(err) });
    }
  }, [card]);
  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(card.path);
      host2.notify({ kind: "success", message: "路径已复制" });
    } catch {
      host2.notify({ kind: "error", message: "复制失败" });
    }
  };
  return /* @__PURE__ */ jsxs3(Fragment3, { children: [
    /* @__PURE__ */ jsxs3(
      "div",
      {
        className: cn3(
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
          multiMode && /* @__PURE__ */ jsx3(
            "span",
            {
              className: "absolute top-1 left-1 z-10 flex size-4 items-center justify-center rounded-full border text-[0.75rem]",
              style: isSelected ? { background: "var(--ui-accent)", borderColor: "var(--ui-accent)", color: "var(--ui-bg)" } : { borderColor: "var(--ui-stroke-secondary)", color: "transparent" },
              children: "✓"
            }
          ),
          /* @__PURE__ */ jsxs3("div", { className: "flex items-start justify-between gap-1", children: [
            /* @__PURE__ */ jsx3("span", { className: "line-clamp-2 flex-1 break-words font-medium leading-snug text-[0.9375rem]", children: card.title || card.file.replace(/\.md$/, "") }),
            /* @__PURE__ */ jsxs3("span", { className: "flex shrink-0 items-center gap-1 pr-5", children: [
              card.priority && priorityMeta(card.priority) && /* @__PURE__ */ jsx3(
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
              card.size && sizeMeta(card.size) && /* @__PURE__ */ jsx3(
                "span",
                {
                  className: "rounded border px-1 text-[0.75rem] font-medium",
                  style: { color: sizeMeta(card.size).fg, borderColor: sizeMeta(card.size).fg },
                  children: card.size
                }
              ),
              card.entry_count > 0 && /* @__PURE__ */ jsx3("span", { className: "rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)", children: card.entry_count })
            ] })
          ] }),
          card.tags && card.tags.length > 0 && /* @__PURE__ */ jsx3("div", { className: "mt-1 flex flex-wrap gap-1", children: card.tags.map((t) => /* @__PURE__ */ jsx3(
            "button",
            {
              type: "button",
              onClick: (e) => {
                e.stopPropagation();
                $tagFilter.set(tagFilter === t ? "" : t);
              },
              className: cn3(
                "rounded px-1 text-[0.75rem] leading-4 transition-colors",
                tagFilter === t ? "bg-(--ui-accent) text-(--ui-bg)" : "bg-(--ui-bg-elevated) text-(--ui-text-tertiary) hover:text-(--ui-accent)"
              ),
              children: t
            },
            t
          )) }),
          /* @__PURE__ */ jsxs3("div", { className: "mt-1 flex items-center gap-1.5 text-[0.75rem] text-(--ui-text-quaternary)", children: [
            /* @__PURE__ */ jsx3("span", { className: "inline-block h-1.5 w-1.5 rounded-full", style: { backgroundColor: tone } }),
            /* @__PURE__ */ jsx3("span", { children: card.status }),
            card.due && /* @__PURE__ */ jsxs3("span", { className: isOverdue(card.due) ? "font-semibold text-(--ui-text-danger)" : void 0, children: [
              "· 截止 ",
              card.due,
              isOverdue(card.due) && " ⚠"
            ] }),
            card.status === "in_progress" && card.session_id && /* @__PURE__ */ jsx3("span", { children: "· ▶ 执行中" })
          ] }),
          !multiMode && /* @__PURE__ */ jsx3("div", { className: "mt-1 flex items-center gap-1", children: sectionKey === "task" && card.status === "todo" ? /* @__PURE__ */ jsxs3(Fragment3, { children: [
            /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doComplete.mutate();
            }, type: "button", "aria-label": "归档", children: [
              /* @__PURE__ */ jsx3(Codicon2, { name: "check", size: "0.7rem" }),
              "归档"
            ] }),
            /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              setExecOpen(true);
            }, type: "button", "aria-label": "执行", children: [
              /* @__PURE__ */ jsx3(Codicon2, { name: "play", size: "0.7rem" }),
              "执行"
            ] })
          ] }) : canArchive ? /* @__PURE__ */ jsxs3(Fragment3, { children: [
            /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doComplete.mutate();
            }, type: "button", "aria-label": "归档", children: [
              /* @__PURE__ */ jsx3(Codicon2, { name: "check", size: "0.7rem" }),
              "归档"
            ] }),
            card.status === "in_progress" && card.session_id && /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              host2.navigate("/" + encodeURIComponent(card.session_id));
            }, type: "button", "aria-label": "打开会话", children: [
              /* @__PURE__ */ jsx3(Codicon2, { name: "link-external", size: "0.7rem" }),
              "打开会话"
            ] })
          ] }) : sectionKey === "task" && card.status === "abandoned" ? /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
            e.stopPropagation();
            doReopen.mutate();
          }, type: "button", "aria-label": "重新打开", children: [
            /* @__PURE__ */ jsx3(Codicon2, { name: "refresh", size: "0.7rem" }),
            "重新打开"
          ] }) : sectionKey === "done" && card.entry_count > 0 ? /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
            e.stopPropagation();
            doResolve.mutate();
          }, type: "button", "aria-label": "确认处理", children: [
            /* @__PURE__ */ jsx3(Codicon2, { name: "check", size: "0.7rem" }),
            "确认处理"
          ] }) : sectionKey === "done" ? /* @__PURE__ */ jsxs3(Fragment3, { children: [
            card.session_id && /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              host2.navigate("/" + encodeURIComponent(card.session_id));
            }, type: "button", "aria-label": "打开会话", children: [
              /* @__PURE__ */ jsx3(Codicon2, { name: "link-external", size: "0.7rem" }),
              "打开会话"
            ] }),
            /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doReopen.mutate();
            }, type: "button", "aria-label": "回到任务列表", children: [
              /* @__PURE__ */ jsx3(Codicon2, { name: "refresh", size: "0.7rem" }),
              "回到任务列表"
            ] })
          ] }) : sectionKey === "trash" ? /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
            e.stopPropagation();
            doRestore.mutate();
          }, type: "button", "aria-label": "还原", children: [
            /* @__PURE__ */ jsx3(Codicon2, { name: "refresh", size: "0.7rem" }),
            "还原"
          ] }) : card.entry_count > 0 ? /* @__PURE__ */ jsxs3(Fragment3, { children: [
            /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doResolve.mutate();
            }, type: "button", "aria-label": "确认处理", children: [
              /* @__PURE__ */ jsx3(Codicon2, { name: "check", size: "0.7rem" }),
              "确认处理"
            ] }),
            /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              setExecOpen(true);
            }, type: "button", "aria-label": "执行", children: [
              /* @__PURE__ */ jsx3(Codicon2, { name: "play", size: "0.7rem" }),
              "执行"
            ] }),
            /* @__PURE__ */ jsxs3("button", { className: "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)", onClick: (e) => {
              e.stopPropagation();
              doToTask.mutate();
            }, type: "button", "aria-label": "转任务", children: [
              /* @__PURE__ */ jsx3(Codicon2, { name: "arrow-right", size: "0.7rem" }),
              "转任务"
            ] })
          ] }) : null }),
          /* @__PURE__ */ jsx3(
            "button",
            {
              "data-wb-menu": true,
              ref: menuTriggerRef,
              className: cn3(
                "absolute right-1 top-1 block rounded p-0.5 text-(--ui-text-tertiary)",
                "hover:bg-(--ui-stroke-secondary)"
              ),
              onClick: (e) => {
                e.stopPropagation();
                onMenuOpenChange(menuOpen ? null : menuKey);
              },
              type: "button",
              "aria-label": "Actions",
              children: /* @__PURE__ */ jsx3(Codicon2, { name: "kebab-vertical", size: "0.75rem" })
            }
          ),
          menuOpen && menuPosition && /* @__PURE__ */ jsxs3(
            "div",
            {
              "data-wb-menu": true,
              "data-wb-menu-overlay": true,
              className: "wb-menu-overlay fixed z-[10020] max-w-[calc(100vw-1rem)] min-w-[10rem] rounded-lg border border-(--ui-stroke-secondary)\n                     bg-(--ui-bg-elevated) p-1 text-[0.8125rem] shadow-lg backdrop-blur-md",
              style: { left: menuPosition.left, top: menuPosition.top },
              onClick: (e) => e.stopPropagation(),
              children: [
                sectionKey === "task" && card.status === "todo" && /* @__PURE__ */ jsxs3(Fragment3, { children: [
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "check", label: "✓ 归档", onClick: () => {
                    doComplete.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "play", label: "▶ 执行", onClick: () => {
                    setExecOpen(true);
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "history", label: "↻ 顺延", onClick: () => {
                    doDefer.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "edit", label: "✎ 编辑", onClick: () => {
                    setEditOpen(true);
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "trash", label: "✖ 放弃", onClick: () => {
                    doAbandon.mutate();
                    onMenuOpenChange(null);
                  } })
                ] }),
                canArchive && card.status !== "todo" && /* @__PURE__ */ jsxs3(Fragment3, { children: [
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "check", label: "✓ 归档", onClick: () => {
                    doComplete.mutate();
                    onMenuOpenChange(null);
                  } }),
                  card.session_id && /* @__PURE__ */ jsx3(MenuBtn, { icon: "link-external", label: "▶ 打开会话", onClick: () => {
                    host2.navigate("/" + encodeURIComponent(card.session_id));
                    onMenuOpenChange(null);
                  } })
                ] }),
                sectionKey === "task" && card.status === "abandoned" && /* @__PURE__ */ jsx3(MenuBtn, { icon: "refresh", label: "↩ 重新打开", onClick: () => {
                  doReopen.mutate();
                  onMenuOpenChange(null);
                } }),
                sectionKey === "done" && /* @__PURE__ */ jsxs3(Fragment3, { children: [
                  card.session_id && /* @__PURE__ */ jsx3(MenuBtn, { icon: "link-external", label: "▶ 打开会话", onClick: () => {
                    host2.navigate("/" + encodeURIComponent(card.session_id));
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "refresh", label: "↩ 回到任务列表", onClick: () => {
                    doReopen.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "trash", label: "🗑 移到回收站", onClick: () => {
                    doTrash.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "trash", label: "🗑 永久删除", onClick: () => {
                    if (confirm("确定永久删除？不可恢复。")) {
                      doDelete.mutate();
                      onMenuOpenChange(null);
                    }
                  } })
                ] }),
                sectionKey === "trash" && /* @__PURE__ */ jsxs3(Fragment3, { children: [
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "refresh", label: "↩ 还原", onClick: () => {
                    doRestore.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "trash", label: "🗑 永久删除", onClick: () => {
                    if (confirm("确定永久删除？不可恢复。")) {
                      doDelete.mutate();
                      onMenuOpenChange(null);
                    }
                  } })
                ] }),
                sectionKey !== "task" && sectionKey !== "done" && sectionKey !== "trash" && card.entry_count > 0 && /* @__PURE__ */ jsxs3(Fragment3, { children: [
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "check", label: "✓ 确认处理", onClick: () => {
                    doResolve.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "play", label: "▶ 执行", onClick: () => {
                    setExecOpen(true);
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "arrow-right", label: "↻ 转任务", onClick: () => {
                    doToTask.mutate();
                    onMenuOpenChange(null);
                  } }),
                  /* @__PURE__ */ jsx3(MenuBtn, { icon: "edit", label: "✎ 编辑", onClick: () => {
                    setEditOpen(true);
                    onMenuOpenChange(null);
                  } })
                ] }),
                /* @__PURE__ */ jsx3(MenuBtn, { icon: "eye", label: "👁 预览", onClick: () => {
                  onPreview(card);
                  onMenuOpenChange(null);
                } }),
                /* @__PURE__ */ jsx3(MenuBtn, { icon: "file", label: "📂 复制路径", onClick: () => {
                  copyPath();
                  onMenuOpenChange(null);
                } })
              ]
            }
          )
        ]
      }
    ),
    execOpen && /* @__PURE__ */ jsx3(
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
    editOpen && /* @__PURE__ */ jsx3(
      EditDialog,
      {
        card,
        onClose: () => setEditOpen(false),
        onConfirm: async (o) => {
          setEditOpen(false);
          try {
            const res = await editEntry({ dir: card.dir, file: card.file, entry_title: card.entry_title || void 0, title: o.title, content: o.content, due: o.due });
            if (!res.ok) {
              host2.notify({ kind: "error", message: res.error || "保存失败" });
              return;
            }
            invalidateBoard();
            host2.notify({ kind: "success", message: "已保存" });
          } catch (err) {
            host2.notify({ kind: "error", message: String(err) });
          }
        }
      }
    )
  ] });
}
function MenuBtn({ icon, label, onClick }) {
  return /* @__PURE__ */ jsx3(
    "button",
    {
      className: "flex w-full items-center gap-2 rounded px-2 py-1 text-left text-(--ui-text-primary)\n                 hover:bg-(--ui-stroke-secondary)",
      onClick,
      type: "button",
      children: label
    }
  );
}
function WbSectionView({ section, onPreview, openMenuKey, onMenuOpenChange, multiMode, selected, onToggleSelect }) {
  const meta = partitionMeta(section.key);
  const label = section.label ?? meta.label;
  const collapsedOverride = useValue2($collapsedSections)[section.key];
  const [showAllArchived, setShowAllArchived] = useState2(true);
  const filterText = useValue2($filterText).toLowerCase();
  const tagFilter = useValue2($tagFilter);
  const showArchived = useValue2($showArchived);
  const dueFilter = useValue2($dueFilter);
  const todayLocal = useMemo2(() => {
    const n = /* @__PURE__ */ new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }, []);
  const expanded = useMemo2(() => {
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
  const filtered = useMemo2(() => {
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
  const collapsed = collapsedOverride ?? false;
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
    return /* @__PURE__ */ jsxs3(
      "button",
      {
        type: "button",
        className: "wb-section--collapsed flex h-full w-8 shrink-0 flex-col items-center gap-1.5 rounded-lg p-2 transition-colors hover:bg-(--ui-stroke-secondary)",
        onClick: toggleCollapse,
        "aria-label": `展开${label}`,
        title: `展开${label}`,
        children: [
          /* @__PURE__ */ jsx3("span", { className: "grid h-5 shrink-0 place-items-center", children: /* @__PURE__ */ jsx3("span", { className: "size-1.5 rounded-full", style: { backgroundColor: meta.tone } }) }),
          /* @__PURE__ */ jsx3("span", { className: "text-[0.6875rem] font-medium uppercase tracking-wide text-(--ui-text-tertiary) [writing-mode:vertical-rl]", children: meta.label }),
          cardCount > 0 && /* @__PURE__ */ jsx3("span", { className: "text-[0.6875rem] tabular-nums text-(--ui-text-quaternary)", children: cardCount })
        ]
      }
    );
  }
  return /* @__PURE__ */ jsxs3("div", { className: "wb-section flex min-h-0 max-h-full shrink-0 flex-col rounded-lg p-2 transition-colors bg-[color-mix(in_srgb,var(--ui-bg-quinary)_50%,transparent)]", children: [
    /* @__PURE__ */ jsxs3(
      "button",
      {
        className: cn3(
          "flex h-6 items-center gap-1.5 rounded px-1 text-left",
          "text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)"
        ),
        onClick: toggleCollapse,
        type: "button",
        children: [
          /* @__PURE__ */ jsx3(Codicon2, { name: collapsed ? "chevron-right" : "chevron-down", size: "0.7rem" }),
          /* @__PURE__ */ jsx3("span", { className: "size-1.5 rounded-full", style: { backgroundColor: meta.tone } }),
          /* @__PURE__ */ jsx3("span", { className: "text-[0.8125rem] font-semibold", children: label }),
          /* @__PURE__ */ jsx3("span", { className: "ml-auto text-[0.75rem] tabular-nums text-(--ui-text-quaternary)", children: cardCount })
        ]
      }
    ),
    !collapsed && /* @__PURE__ */ jsxs3("div", { className: "flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto", children: [
      filtered.length === 0 && /* @__PURE__ */ jsx3("span", { className: "px-2 py-3 text-center text-[0.75rem] text-(--ui-text-quaternary)", children: "暂无条目" }),
      visible.map((card) => /* @__PURE__ */ jsx3(CardErrorBoundary, { children: /* @__PURE__ */ jsx3(
        WbCardView,
        {
          card,
          sectionKey: section.key,
          onPreview,
          openMenuKey,
          onMenuOpenChange,
          multiMode,
          selected,
          onToggleSelect
        }
      ) }, card.file + (card.entry_title || ""))),
      archivedPreview && filtered.length > ARCHIVED_PREVIEW_LIMIT && !showAllArchived && /* @__PURE__ */ jsxs3(
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
  const [title, setTitle] = useState2(card.title || card.file.replace(/\.md$/, ""));
  const [content, setContent] = useState2("");
  const [due, setDue] = useState2(card.due || "");
  const [rawBody, setRawBody] = useState2("");
  const [rawOriginal, setRawOriginal] = useState2("");
  const [editingRaw, setEditingRaw] = useState2(false);
  const [busy, setBusy] = useState2(false);
  useEffect(() => {
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
      host2.notify({ kind: "error", message: "标题不能为空" });
      return;
    }
    setBusy(true);
    try {
      if (!card.entry_title && editingRaw && rawBody.trim() !== rawOriginal.trim()) {
        const amendRes = await editEntry({ dir: card.dir, file: card.file, amend: true, content: rawBody.trim() });
        if (!amendRes.ok) {
          host2.notify({ kind: "error", message: `修正原文失败：${amendRes.error || "未知错误"}` });
          return;
        }
      }
      await onConfirm({ title: t, content: content.trim() || void 0, due: due.trim() || void 0 });
    } finally {
      setBusy(false);
    }
  };
  const field = "w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)";
  return /* @__PURE__ */ jsx3(Dialog, { open: true, onOpenChange: (o) => {
    if (!o) onClose();
  }, children: /* @__PURE__ */ jsxs3(
    DialogContent,
    {
      className: "wb-dialog",
      style: { width: "min(52rem, 94vw)", maxWidth: "94vw" },
      children: [
        /* @__PURE__ */ jsx3(DialogHeader, { children: /* @__PURE__ */ jsx3(DialogTitle, { children: "▶ 执行前编辑" }) }),
        /* @__PURE__ */ jsxs3("div", { className: "flex flex-col gap-2", children: [
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "标题",
            /* @__PURE__ */ jsx3("input", { className: field, value: title, onChange: (e) => setTitle(e.target.value) })
          ] }),
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "内容（执行前补充）",
            /* @__PURE__ */ jsx3("textarea", { className: field + " min-h-[5rem] resize-y", value: content, onChange: (e) => setContent(e.target.value), placeholder: "可选：补充执行要求（如「只研究，不摄入 Obsidian」）" })
          ] }),
          /* @__PURE__ */ jsx3("div", { className: "my-1 border-t border-(--ui-stroke-secondary)", "aria-hidden": "true" }),
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            /* @__PURE__ */ jsxs3("span", { className: "flex items-center justify-between", children: [
              "原始内容",
              editingRaw ? "（修正模式）" : "（只读）",
              card.entry_title ? /* @__PURE__ */ jsx3("span", { className: "text-[0.6875rem] text-(--ui-text-quaternary)", children: "条目内容（修正请用 ✎ 编辑）" }) : /* @__PURE__ */ jsx3(
                "button",
                {
                  type: "button",
                  className: "rounded border border-(--ui-stroke-secondary) px-2 py-0.5 text-[0.6875rem] text-(--ui-text-secondary) hover:border-(--ui-accent) hover:text-(--ui-accent)",
                  onClick: () => setEditingRaw((v) => !v),
                  children: editingRaw ? "完成修正" : "修正原文"
                }
              )
            ] }),
            editingRaw ? /* @__PURE__ */ jsx3(
              "textarea",
              {
                className: field + " min-h-[8rem] resize-y",
                value: rawBody,
                onChange: (e) => setRawBody(e.target.value)
              }
            ) : /* @__PURE__ */ jsx3("div", { className: field + " max-h-[12rem] overflow-y-auto whitespace-pre-wrap break-words", children: rawBody || "（无额外内容）" })
          ] }),
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "Due",
            /* @__PURE__ */ jsx3("input", { className: field, type: "date", value: due, onChange: (e) => setDue(e.target.value) })
          ] })
        ] }),
        /* @__PURE__ */ jsxs3(DialogFooter, { children: [
          /* @__PURE__ */ jsx3(Button2, { size: "sm", variant: "outline", onClick: onClose, children: "取消" }),
          /* @__PURE__ */ jsx3(Button2, { size: "sm", onClick: submit, disabled: busy, children: busy ? "执行中…" : "确认执行" })
        ] })
      ]
    }
  ) });
}
function EditDialog({ card, onClose, onConfirm }) {
  const [title, setTitle] = useState2(card.title || card.file.replace(/\.md$/, ""));
  const [content, setContent] = useState2("");
  const [due, setDue] = useState2(card.due || "");
  const [busy, setBusy] = useState2(false);
  const submit = async () => {
    const t = title.trim();
    if (!t) {
      host2.notify({ kind: "error", message: "标题不能为空" });
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
  return /* @__PURE__ */ jsx3(Dialog, { open: true, onOpenChange: (o) => {
    if (!o) onClose();
  }, children: /* @__PURE__ */ jsxs3(
    DialogContent,
    {
      className: "wb-dialog",
      style: { width: "min(52rem, 94vw)", maxWidth: "94vw" },
      children: [
        /* @__PURE__ */ jsx3(DialogHeader, { children: /* @__PURE__ */ jsx3(DialogTitle, { children: "✎ 编辑" }) }),
        /* @__PURE__ */ jsxs3("div", { className: "flex flex-col gap-2", children: [
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "标题",
            /* @__PURE__ */ jsx3("input", { className: field, value: title, onChange: (e) => setTitle(e.target.value) })
          ] }),
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "内容（备注/补充）",
            /* @__PURE__ */ jsx3("textarea", { className: field + " min-h-[6rem] resize-y", value: content, onChange: (e) => setContent(e.target.value) })
          ] }),
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "Due",
            /* @__PURE__ */ jsx3("input", { className: field, type: "date", value: due, onChange: (e) => setDue(e.target.value) })
          ] })
        ] }),
        /* @__PURE__ */ jsxs3(DialogFooter, { children: [
          /* @__PURE__ */ jsx3(Button2, { size: "sm", variant: "outline", onClick: onClose, children: "取消" }),
          /* @__PURE__ */ jsx3(Button2, { size: "sm", onClick: submit, disabled: busy, children: busy ? "保存中…" : "保存" })
        ] })
      ]
    }
  ) });
}
function DialogSelect({ value, onChange, options, placeholder }) {
  const [open, setOpen] = useState2(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  useEffect(() => {
    setOpen(false);
  }, [value]);
  const current = options.find((o) => o.value === value);
  return /* @__PURE__ */ jsxs3("div", { className: "relative", ref, children: [
    /* @__PURE__ */ jsxs3(
      "button",
      {
        className: "flex w-full items-center justify-between rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none hover:border-(--ui-accent)",
        onClick: () => setOpen(!open),
        type: "button",
        "aria-haspopup": "listbox",
        "aria-expanded": open,
        children: [
          /* @__PURE__ */ jsx3("span", { className: "truncate", children: current ? current.label : placeholder || "" }),
          /* @__PURE__ */ jsx3(Codicon2, { name: open ? "chevron-up" : "chevron-down", size: "0.7rem" })
        ]
      }
    ),
    open && /* @__PURE__ */ jsx3(
      "div",
      {
        className: "absolute top-full left-0 z-50 mt-1 max-h-48 w-full overflow-y-auto rounded border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-1 shadow-lg",
        role: "listbox",
        children: options.map((o) => /* @__PURE__ */ jsx3(
          "button",
          {
            className: cn3(
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
  const [dir, setDir] = useState2("任务");
  const [title, setTitle] = useState2("");
  const [due, setDue] = useState2("");
  const [content, setContent] = useState2("");
  const [busy, setBusy] = useState2(false);
  const [suggestion, setSuggestion] = useState2(null);
  const [picked, setPicked] = useState2(/* @__PURE__ */ new Set());
  const knownTags = useMemo2(() => {
    const set = /* @__PURE__ */ new Set();
    for (const s of board.sections) for (const c of s.files) for (const t of c.tags || []) set.add(t);
    return Array.from(set);
  }, [board]);
  useEffect(() => {
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
      host2.notify({ kind: "error", message: "标题不能为空" });
      return;
    }
    setBusy(true);
    try {
      const res = await addEntry({ dir, title: t, due: due || void 0, content: content.trim() || void 0 });
      if (!res.ok) {
        host2.notify({ kind: "error", message: res.error || "创建失败" });
        return;
      }
      if (picked.size > 0 && res.file) {
        const tags = Array.from(picked);
        const ed = await editEntry({ dir, file: res.file, tags });
        if (!ed.ok) host2.notify({ kind: "warning", message: "标签写入失败：" + (ed.error || "") });
      }
      invalidateBoard();
      onClose();
    } catch (err) {
      host2.notify({ kind: "error", message: String(err) });
    } finally {
      setBusy(false);
    }
  };
  const field = "w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)";
  return /* @__PURE__ */ jsx3(Dialog, { open: true, onOpenChange: (o) => {
    if (!o) onClose();
  }, children: /* @__PURE__ */ jsxs3(
    DialogContent,
    {
      className: "wb-dialog",
      style: { width: "min(52rem, 94vw)", maxWidth: "94vw" },
      children: [
        /* @__PURE__ */ jsx3(DialogHeader, { children: /* @__PURE__ */ jsx3(DialogTitle, { children: "＋ 新建任务" }) }),
        /* @__PURE__ */ jsxs3("div", { className: "flex flex-col gap-3", children: [
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "标题（必填）",
            /* @__PURE__ */ jsx3("input", { className: field, value: title, onChange: (e) => setTitle(e.target.value), placeholder: "任务标题", autoFocus: true })
          ] }),
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "分区",
            /* @__PURE__ */ jsx3(DialogSelect, { value: dir, onChange: setDir, options: NEW_TASK_DIRS, placeholder: "选择分区" })
          ] }),
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "Due（截止日期）",
            /* @__PURE__ */ jsx3("input", { className: field, type: "date", value: due, onChange: (e) => setDue(e.target.value) })
          ] }),
          /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)", children: [
            "内容（可选）",
            /* @__PURE__ */ jsx3("textarea", { className: field + " min-h-24 resize-y", value: content, onChange: (e) => setContent(e.target.value), placeholder: "备注/要求…" })
          ] }),
          suggestion && (suggestion.tags.length > 0 || suggestion.low.length > 0) && /* @__PURE__ */ jsxs3("div", { className: "flex flex-wrap items-center gap-1.5", children: [
            /* @__PURE__ */ jsx3("span", { className: "text-[0.8125rem] text-(--ui-text-tertiary)", children: "✨ 建议标签：" }),
            suggestion.tags.map((tag) => {
              const active = picked.has(tag);
              return /* @__PURE__ */ jsx3(
                "button",
                {
                  className: cn3(
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
            suggestion.low.length > 0 && /* @__PURE__ */ jsxs3("span", { className: "text-[0.8125rem] text-(--ui-text-quaternary)", children: [
              "建议标签：",
              suggestion.low.join(" "),
              "（可确认）"
            ] })
          ] })
        ] }),
        /* @__PURE__ */ jsxs3(DialogFooter, { children: [
          /* @__PURE__ */ jsx3(Button2, { size: "sm", variant: "outline", onClick: onClose, children: "取消" }),
          /* @__PURE__ */ jsx3(Button2, { size: "sm", onClick: () => void submit(), disabled: busy, children: busy ? "创建中…" : "创建" })
        ] })
      ]
    }
  ) });
}
var BRIEF_TYPE_META = {
  new_task: { icon: "lightbulb", label: "新任务" },
  duplicate: { icon: "warning", label: "重复" },
  blocked: { icon: "stop", label: "阻塞" },
  overdue: { icon: "calendar", label: "过期重估" },
  decision: { icon: "question", label: "需决策" }
};
function TodayCardRow({ card, onPreview }) {
  const tone = STATUS_TONE[card.status] || "var(--ui-text-tertiary)";
  const prio = priorityMeta(card.priority || "");
  return /* @__PURE__ */ jsxs3(
    "button",
    {
      className: "flex w-full items-center gap-2 rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1.5 text-left transition-colors hover:border-(--ui-accent)",
      onClick: () => onPreview(card),
      type: "button",
      children: [
        /* @__PURE__ */ jsx3("span", { className: "size-1.5 shrink-0 rounded-full", style: { background: tone } }),
        prio && /* @__PURE__ */ jsx3("span", { className: "h-3 w-0.5 shrink-0 rounded", style: { background: prio.fg } }),
        /* @__PURE__ */ jsx3("span", { className: "min-w-0 flex-1 truncate text-[0.75rem] font-medium text-(--ui-text-primary)", children: card.title || card.file.replace(/\.md$/, "") }),
        card.due && /* @__PURE__ */ jsx3("span", { className: cn3("shrink-0 text-[0.75rem]", isOverdue(card.due) ? "font-semibold text-(--ui-text-danger)" : "text-(--ui-text-tertiary)"), children: card.due })
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
    /* @__PURE__ */ jsx3("span", { className: "shrink-0 rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.75rem] text-(--ui-text-quaternary)", children: "Agent 建议" })
  ] });
}
function TodayView({ board, onPreview, onGoBoard }) {
  const [ignored, setIgnored] = useState2(/* @__PURE__ */ new Set());
  const { data: brief } = useQuery2({
    queryKey: ["workbench", "brief"],
    queryFn: fetchBrief,
    staleTime: 30 * 60 * 1e3
  });
  const taskCards = useMemo2(() => board.sections.find((s) => s.key === "task")?.files ?? [], [board]);
  const today = board.today;
  const overdue = taskCards.filter((c) => c.status === "todo" && c.due && c.due < today);
  const dueToday = taskCards.filter((c) => c.status === "todo" && c.due === today);
  const inProgress = taskCards.filter((c) => c.status === "in_progress");
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
  const emptyAll = overdue.length === 0 && dueToday.length === 0 && inProgress.length === 0;
  return /* @__PURE__ */ jsx3("div", { className: "flex flex-1 flex-col overflow-y-auto px-3 pb-3", children: /* @__PURE__ */ jsxs3("div", { className: "mx-auto flex w-full max-w-3xl flex-col gap-4 py-3", children: [
    /* @__PURE__ */ jsxs3("div", { className: "flex flex-col gap-1.5", children: [
      /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-1.5", children: [
        /* @__PURE__ */ jsxs3("span", { className: "text-[0.8125rem] font-semibold text-(--ui-text-danger)", children: [
          "⚠ 超期 (",
          overdue.length,
          ")"
        ] }),
        overdue.length > 0 && /* @__PURE__ */ jsx3("button", { className: "ml-auto text-[0.75rem] text-(--ui-accent) hover:underline", onClick: onGoBoard, type: "button", children: "进入看板 →" })
      ] }),
      overdue.slice(0, 5).map((c) => /* @__PURE__ */ jsx3(TodayCardRow, { card: c, onPreview }, c.file)),
      overdue.length > 5 && /* @__PURE__ */ jsxs3("span", { className: "px-1 text-[0.75rem] text-(--ui-text-quaternary)", children: [
        "还有 ",
        overdue.length - 5,
        " 条超期，",
        /* @__PURE__ */ jsx3("button", { className: "text-(--ui-accent) hover:underline", onClick: onGoBoard, type: "button", children: "进入看板" })
      ] }),
      /* @__PURE__ */ jsxs3("span", { className: "mt-2 text-[0.8125rem] font-semibold text-(--ui-text-secondary)", children: [
        "▸ 今日到期 (",
        dueToday.length,
        ")"
      ] }),
      dueToday.slice(0, 5).map((c) => /* @__PURE__ */ jsx3(TodayCardRow, { card: c, onPreview }, c.file)),
      /* @__PURE__ */ jsxs3("span", { className: "mt-2 text-[0.8125rem] font-semibold text-(--ui-text-secondary)", children: [
        "▸ 进行中 (",
        inProgress.length,
        ")"
      ] }),
      inProgress.map((c) => /* @__PURE__ */ jsx3(TodayCardRow, { card: c, onPreview }, c.file)),
      emptyAll && /* @__PURE__ */ jsxs3("div", { className: "rounded-md border border-dashed border-(--ui-stroke-tertiary) px-3 py-4 text-center", children: [
        /* @__PURE__ */ jsx3("div", { className: "text-[0.75rem] text-(--ui-text-secondary)", children: "今天没有安排 🎉" }),
        /* @__PURE__ */ jsx3("div", { className: "mt-1 text-[0.75rem] text-(--ui-text-quaternary)", children: "右下角「新建任务」或手机转发到 QQ 群自动收录" })
      ] })
    ] }),
    /* @__PURE__ */ jsxs3("div", { className: "flex flex-col gap-1.5", children: [
      /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-1.5", children: [
        /* @__PURE__ */ jsx3("span", { className: "text-[0.8125rem] font-semibold text-(--ui-text-secondary)", children: "✨ Agent 建议" }),
        /* @__PURE__ */ jsx3("span", { className: "text-[0.75rem] text-(--ui-text-quaternary)", children: "仅供参考，可随时忽略" })
      ] }),
      brief?.degraded ? /* @__PURE__ */ jsx3("div", { className: "rounded-md border border-(--ui-stroke-tertiary) px-2.5 py-2 text-[0.75rem] text-(--ui-text-quaternary)", children: "Agent 简报暂不可用（Hermes 未响应）——规则区仍实时可用" }) : visibleCards.length === 0 ? /* @__PURE__ */ jsx3("div", { className: "px-1 text-[0.75rem] text-(--ui-text-quaternary)", children: "暂无建议" }) : visibleCards.map((c) => /* @__PURE__ */ jsx3(
        BriefCardView,
        {
          card: c,
          onAccept: c.type === "new_task" ? () => void acceptBrief(c) : void 0,
          onIgnore: () => setIgnored((prev) => new Set(prev).add(c.title))
        },
        c.title
      ))
    ] })
  ] }) });
}
function WorkbenchBoardPage() {
  const { data: board, isLoading, error } = useQuery2({
    queryKey: BOARD_KEY,
    queryFn: () => fetchBoard(),
    refetchInterval: 3e4
  });
  const [previewCard, setPreviewCard] = useState2(null);
  const [openMenuKey, setOpenMenuKey] = useState2(null);
  useEffect(() => {
    if (!openMenuKey) return;
    const onDown = (e) => {
      if (e.target instanceof Element && e.target.closest("[data-wb-menu]")) return;
      setOpenMenuKey(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [openMenuKey]);
  const [showNewTask, setShowNewTask] = useState2(false);
  const [showSettings, setShowSettings] = useState2(false);
  const [showHealthDetails, setShowHealthDetails] = useState2(false);
  const health = useQuery2({ queryKey: ["workbench", "health"], queryFn: fetchHealth, refetchInterval: 3e4 });
  const settings = useQuery2({ queryKey: ["workbench", "settings"], queryFn: fetchSettings });
  const dueFilter = useValue2($dueFilter);
  const [bannerDismissedDate, setBannerDismissedDate] = useState2(
    () => typeof localStorage === "undefined" ? "" : localStorage.getItem("wbDeliveryBannerDismissedDate") || ""
  );
  const [showToday, setShowToday] = useState2(true);
  const thoughtSection = board?.sections.find((s) => s.key === "thought");
  const pendingCount = thoughtSection ? thoughtSection.files.reduce((n, f) => n + (f.entry_count || 0), 0) : 0;
  const goThoughtBoard = () => {
    setShowToday(false);
    $collapsedSections.set({ ...$collapsedSections.get(), thought: false });
  };
  const viewMode = useValue2($viewMode);
  const setViewMode = (m) => $viewMode.set(m);
  const [multiMode, setMultiMode] = useState2(false);
  const [selected, setSelected] = useState2(/* @__PURE__ */ new Set());
  const [batchBusy, setBatchBusy] = useState2(false);
  const [searchQ, setSearchQ] = useState2("");
  const [debouncedQ, setDebouncedQ] = useState2("");
  const [searchOpen, setSearchOpen] = useState2(false);
  const searchRef = useRef(null);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(searchQ.trim()), 250);
    return () => clearTimeout(t);
  }, [searchQ]);
  useEffect(() => {
    if (!searchOpen) return;
    const onDown = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) setSearchOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [searchOpen]);
  const { data: searchData } = useQuery2({
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
      const okN = res.summary?.ok ?? 0;
      const failN = res.summary?.fail ?? 0;
      host2.notify({ kind: failN > 0 ? "warning" : "success", message: `批量归档 ${okN} 项${failN ? `，${failN} 项失败` : ""}` });
      invalidateBoard();
      setSelected(/* @__PURE__ */ new Set());
      setMultiMode(false);
    } catch (err) {
      host2.notify({ kind: "error", message: String(err) });
    } finally {
      setBatchBusy(false);
    }
  };
  if (isLoading) {
    return /* @__PURE__ */ jsx3("div", { className: "flex h-full items-center justify-center text-sm text-(--ui-text-tertiary)", children: "加载中…" });
  }
  if (error) {
    return /* @__PURE__ */ jsx3("div", { className: "flex h-full items-center justify-center text-sm text-(--ui-text-danger)", children: "后端不可达" });
  }
  if (!board) return null;
  const deliverMissing = settings.data?.ok === true && !settings.data.config.deliver_target;
  const showDeliveryBanner = !!deliverMissing && bannerDismissedDate !== board.today;
  const healthData = health.data;
  const healthTone = {
    green: "bg-[#34d399]",
    yellow: "bg-[#fbbf24]",
    red: "bg-[#f87171]",
    disabled: "bg-[#94a3b8]"
  }[healthData?.status ?? "disabled"];
  const checkTone = (status) => ({
    green: "bg-[#34d399]",
    yellow: "bg-[#fbbf24]",
    red: "bg-[#f87171]",
    disabled: "bg-[#94a3b8]"
  })[status];
  const healthLabel = healthData?.label ?? "健康检查…";
  return /* @__PURE__ */ jsxs3("div", { className: "wb-root flex h-full flex-col", children: [
    showDeliveryBanner && /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-2 border-b border-[#fbbf24]/30 bg-[#fbbf24]/10 px-3 py-1.5 text-[0.75rem] text-[#fbbf24]", children: [
      /* @__PURE__ */ jsx3(Codicon2, { name: "warning", size: "0.8rem" }),
      /* @__PURE__ */ jsx3("span", { children: "投递目标未配置，日报/提醒不会发送到 QQ。" }),
      /* @__PURE__ */ jsx3(
        "button",
        {
          type: "button",
          className: "rounded border border-[#fbbf24]/40 px-1.5 py-0.5 hover:bg-[#fbbf24]/20",
          onClick: () => setShowSettings(true),
          children: "去设置"
        }
      ),
      /* @__PURE__ */ jsx3(
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
    /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-2 border-b border-(--ui-stroke-secondary) px-3 py-2", children: [
      /* @__PURE__ */ jsx3(Codicon2, { name: "checklist", size: "1rem" }),
      /* @__PURE__ */ jsx3("span", { className: "text-sm font-semibold", children: "工作台" }),
      /* @__PURE__ */ jsxs3("div", { className: "flex items-center rounded-md border border-(--ui-stroke-secondary) p-0.5", children: [
        /* @__PURE__ */ jsx3(
          "button",
          {
            type: "button",
            className: cn3(
              "rounded px-2 py-0.5 text-[0.8125rem] transition-colors",
              showToday ? "bg-(--ui-accent) text-white" : "text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)"
            ),
            onClick: () => setShowToday(true),
            children: "今日"
          }
        ),
        /* @__PURE__ */ jsx3(
          "button",
          {
            type: "button",
            className: cn3(
              "rounded px-2 py-0.5 text-[0.8125rem] transition-colors",
              !showToday ? "bg-(--ui-accent) text-white" : "text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)"
            ),
            onClick: () => setShowToday(false),
            children: "看板"
          }
        )
      ] }),
      /* @__PURE__ */ jsxs3("span", { className: "text-[0.75rem] text-(--ui-text-quaternary)", children: [
        board.totals.pending,
        " Pending / ",
        board.totals.total,
        " Total"
      ] }),
      /* @__PURE__ */ jsxs3("div", { className: "ml-auto flex items-center gap-2", children: [
        showToday && pendingCount > 0 && /* @__PURE__ */ jsxs3(Button2, { size: "sm", variant: "outline", onClick: goThoughtBoard, children: [
          /* @__PURE__ */ jsx3(Codicon2, { name: "inbox", size: "0.7rem" }),
          /* @__PURE__ */ jsxs3("span", { className: "ml-1", children: [
            "待确认 ",
            pendingCount
          ] })
        ] }),
        !multiMode && /* @__PURE__ */ jsxs3(Button2, { size: "sm", variant: "outline", onClick: () => {
          setSelected(/* @__PURE__ */ new Set());
          setMultiMode(true);
        }, children: [
          /* @__PURE__ */ jsx3(Codicon2, { name: "checklist", size: "0.7rem" }),
          /* @__PURE__ */ jsx3("span", { className: "ml-1", children: "批量" })
        ] }),
        /* @__PURE__ */ jsxs3(Button2, { size: "sm", onClick: () => setShowNewTask(true), children: [
          /* @__PURE__ */ jsx3(Codicon2, { name: "add", size: "0.7rem" }),
          /* @__PURE__ */ jsx3("span", { className: "ml-1", children: "新建任务" })
        ] }),
        /* @__PURE__ */ jsxs3("div", { className: "relative", ref: searchRef, children: [
          /* @__PURE__ */ jsx3(
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
          searchOpen && debouncedQ && searchData && /* @__PURE__ */ jsx3("div", { className: "absolute right-0 top-full z-50 mt-1 max-h-80 w-72 overflow-y-auto rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-1 text-[0.8125rem] shadow-lg", children: searchData.results.length === 0 ? /* @__PURE__ */ jsx3("div", { className: "px-2 py-2 text-(--ui-text-tertiary)", children: "无匹配结果" }) : searchData.results.map((r) => /* @__PURE__ */ jsxs3(
            "button",
            {
              type: "button",
              className: "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-(--ui-stroke-secondary)",
              onPointerDown: () => {
                setPreviewCard(toCard(r, board.root));
                setSearchOpen(false);
              },
              children: [
                /* @__PURE__ */ jsx3("span", { className: "shrink-0 text-[0.75rem] text-(--ui-text-tertiary)", children: partitionMeta(r.key).label }),
                /* @__PURE__ */ jsx3("span", { className: "min-w-0 flex-1 truncate font-medium text-(--ui-text-primary)", children: r.title }),
                r.tags.slice(0, 2).map((t) => /* @__PURE__ */ jsx3("span", { className: "shrink-0 rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)", children: t }, t))
              ]
            },
            `${r.dir}:${r.file}`
          )) })
        ] }),
        tagFilter && /* @__PURE__ */ jsxs3(
          "button",
          {
            type: "button",
            className: "flex items-center gap-1 rounded-full bg-(--ui-accent)/15 px-2 py-0.5 text-[0.8125rem] text-(--ui-accent)",
            onClick: () => $tagFilter.set(""),
            children: [
              "#",
              tagFilter,
              /* @__PURE__ */ jsx3(Codicon2, { name: "close", size: "0.6rem" })
            ]
          }
        ),
        /* @__PURE__ */ jsx3(
          Input,
          {
            className: "h-7 w-44 text-[0.8125rem]",
            placeholder: "筛选…",
            value: filterText,
            onChange: (e) => $filterText.set(e.target.value)
          }
        ),
        /* @__PURE__ */ jsx3(
          Button2,
          {
            size: "sm",
            variant: "outline",
            onClick: () => $showArchived.set(!$showArchived.get()),
            children: showArchived ? "隐藏已归档" : "显示已归档"
          }
        ),
        /* @__PURE__ */ jsx3("div", { className: "flex items-center rounded-md border border-(--ui-stroke-secondary) p-0.5", children: [
          ["all", "全部"],
          ["today", "今天到期"],
          ["overdue", "已超期"]
        ].map(([key, label]) => /* @__PURE__ */ jsx3(
          "button",
          {
            type: "button",
            className: cn3(
              "rounded px-2 py-0.5 text-[0.75rem] transition-colors",
              dueFilter === key ? "bg-(--ui-accent) text-white" : "text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)"
            ),
            onClick: () => $dueFilter.set(key),
            children: label
          },
          key
        )) }),
        /* @__PURE__ */ jsxs3("div", { className: "relative", children: [
          /* @__PURE__ */ jsxs3(
            "button",
            {
              type: "button",
              className: "flex items-center gap-1 rounded px-1.5 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)",
              onClick: () => setShowHealthDetails((v) => !v),
              "aria-expanded": showHealthDetails,
              title: "查看链路健康详情",
              children: [
                /* @__PURE__ */ jsx3("span", { className: `size-2 rounded-full ${healthTone}` }),
                /* @__PURE__ */ jsx3("span", { children: healthLabel }),
                /* @__PURE__ */ jsx3(Codicon2, { name: showHealthDetails ? "chevron-up" : "chevron-down", size: "0.65rem" })
              ]
            }
          ),
          showHealthDetails && healthData && /* @__PURE__ */ jsxs3("div", { className: "absolute right-0 top-full z-30 mt-1 w-72 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) p-2 shadow-xl", children: [
            /* @__PURE__ */ jsxs3("div", { className: "mb-1.5 flex items-center justify-between text-[0.75rem] font-semibold text-(--ui-text-primary)", children: [
              /* @__PURE__ */ jsx3("span", { children: "链路健康详情" }),
              /* @__PURE__ */ jsx3("span", { className: "font-normal text-(--ui-text-quaternary)", children: healthData.ts })
            ] }),
            /* @__PURE__ */ jsx3("div", { className: "space-y-1", children: healthData.checks.map((check) => /* @__PURE__ */ jsxs3("div", { className: "flex items-start gap-2 rounded px-1.5 py-1 hover:bg-(--ui-bg-quaternary)", children: [
              /* @__PURE__ */ jsx3("span", { className: `mt-1 size-2 shrink-0 rounded-full ${checkTone(check.status)}` }),
              /* @__PURE__ */ jsxs3("div", { className: "min-w-0 flex-1", children: [
                /* @__PURE__ */ jsx3("div", { className: "text-[0.75rem] text-(--ui-text-primary)", children: check.label }),
                /* @__PURE__ */ jsx3("div", { className: "text-[0.6875rem] text-(--ui-text-tertiary)", children: check.detail })
              ] })
            ] }, check.id)) }),
            healthData.last_updated && /* @__PURE__ */ jsxs3("div", { className: "mt-1.5 border-t border-(--ui-stroke-secondary) pt-1.5 text-[0.6875rem] text-(--ui-text-quaternary)", children: [
              "最近状态更新：",
              healthData.last_updated.replace("T", " ")
            ] })
          ] })
        ] }),
        /* @__PURE__ */ jsxs3(Button2, { size: "sm", variant: "outline", onClick: () => setShowSettings(true), title: "工作台设置", children: [
          /* @__PURE__ */ jsx3(Codicon2, { name: "gear", size: "0.7rem" }),
          /* @__PURE__ */ jsx3("span", { className: "ml-1", children: "设置" })
        ] }),
        /* @__PURE__ */ jsx3(ViewSwitcher, { mode: viewMode, onChange: setViewMode })
      ] })
    ] }),
    multiMode && /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-2 border-b border-(--ui-stroke-secondary) bg-(--ui-accent)/5 px-3 py-1.5", children: [
      /* @__PURE__ */ jsxs3("span", { className: "text-[0.8125rem] text-(--ui-text-secondary)", children: [
        "已选 ",
        selected.size,
        " 项"
      ] }),
      /* @__PURE__ */ jsx3(Button2, { size: "sm", variant: "outline", disabled: batchBusy || selected.size === 0, onClick: () => runBatch("complete"), children: "批量归档" }),
      /* @__PURE__ */ jsx3(Button2, { size: "sm", variant: "outline", disabled: batchBusy || selected.size === 0, onClick: () => runBatch("resolve"), children: "批量归档" }),
      /* @__PURE__ */ jsx3(Button2, { size: "sm", variant: "outline", disabled: batchBusy || selected.size === 0, onClick: () => runBatch("trash"), children: "批量删除" }),
      /* @__PURE__ */ jsx3(Button2, { size: "sm", variant: "outline", onClick: () => {
        setSelected(/* @__PURE__ */ new Set());
        setMultiMode(false);
      }, children: "取消" })
    ] }),
    showToday ? /* @__PURE__ */ jsx3(TodayView, { board, onPreview: setPreviewCard, onGoBoard: () => setShowToday(false) }) : /* @__PURE__ */ jsxs3(Fragment3, { children: [
      viewMode === "table" && /* @__PURE__ */ jsx3(TableBoardView, { board, onPreview: setPreviewCard }),
      viewMode === "board" && /* @__PURE__ */ jsx3("div", { className: "flex flex-1 gap-3 overflow-x-auto p-3", children: board.sections.map((section) => /* @__PURE__ */ jsx3(
        WbSectionView,
        {
          section,
          onPreview: setPreviewCard,
          openMenuKey,
          onMenuOpenChange: setOpenMenuKey,
          multiMode,
          selected,
          onToggleSelect: toggleSelect
        },
        section.key
      )) })
    ] }),
    previewCard && /* @__PURE__ */ jsx3(WbPreviewDrawer, { card: previewCard, onClose: () => setPreviewCard(null) }),
    showNewTask && /* @__PURE__ */ jsx3(NewTaskDialog, { board, onClose: () => setShowNewTask(false) }),
    showSettings && /* @__PURE__ */ jsx3(SettingsDialog, { onClose: () => setShowSettings(false) })
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
  const { data, isLoading, error } = useQuery2({
    queryKey: ["workbench", "settings"],
    queryFn: () => fetchSettings()
  });
  const [form, setForm] = useState2(null);
  const [busy, setBusy] = useState2(false);
  const [newName, setNewName] = useState2("");
  const [newType, setNewType] = useState2("thought");
  const [restartHint, setRestartHint] = useState2([]);
  const [errMsg, setErrMsg] = useState2("");
  useEffect(() => {
    if (data?.ok && data.config) {
      setForm(JSON.parse(JSON.stringify(data.config)));
    }
  }, [data]);
  if (!form) {
    return /* @__PURE__ */ jsx3(Dialog, { open: true, onOpenChange: (o) => {
      if (!o) onClose();
    }, children: /* @__PURE__ */ jsxs3(DialogContent, { className: "wb-dialog", style: { width: "min(52rem, 94vw)", maxWidth: "94vw" }, children: [
      /* @__PURE__ */ jsx3(DialogHeader, { children: /* @__PURE__ */ jsx3(DialogTitle, { children: "⚙ 工作台设置" }) }),
      /* @__PURE__ */ jsx3("div", { className: "flex items-center justify-center py-10 text-sm text-(--ui-text-tertiary)", children: isLoading ? "加载中…" : error ? "设置加载失败" : "" })
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
      host2.notify({ kind: "success", message: "设置已保存" });
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
  return /* @__PURE__ */ jsx3(Dialog, { open: true, onOpenChange: (o) => {
    if (!o) onClose();
  }, children: /* @__PURE__ */ jsxs3(DialogContent, { className: "wb-dialog", style: { width: "min(52rem, 94vw)", maxWidth: "94vw" }, children: [
    /* @__PURE__ */ jsx3(DialogHeader, { children: /* @__PURE__ */ jsx3(DialogTitle, { children: "⚙ 工作台设置" }) }),
    /* @__PURE__ */ jsxs3("div", { className: "flex max-h-[70vh] flex-col gap-4 overflow-y-auto pr-1 text-[0.8125rem]", children: [
      /* @__PURE__ */ jsxs3("section", { children: [
        /* @__PURE__ */ jsxs3("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx3("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "路径" }),
          /* @__PURE__ */ jsx3("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "重启后生效" })
        ] }),
        /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-(--ui-text-secondary)", children: [
          "工作台文件夹",
          /* @__PURE__ */ jsx3("input", { className: field, value: form.root, onChange: (e) => set("root", e.target.value), placeholder: "~/Workbench" })
        ] }),
        /* @__PURE__ */ jsxs3("label", { className: "mt-2 flex flex-col gap-1 text-(--ui-text-secondary)", children: [
          "Obsidian 知识库（日报工作日志位置）",
          /* @__PURE__ */ jsx3("input", { className: field, value: form.vault, onChange: (e) => set("vault", e.target.value), placeholder: "Obsidian 库路径（可留空）" })
        ] })
      ] }),
      /* @__PURE__ */ jsxs3("section", { children: [
        /* @__PURE__ */ jsxs3("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx3("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "分区" }),
          /* @__PURE__ */ jsx3("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "新增即时生效" }),
          /* @__PURE__ */ jsx3("span", { className: "text-[0.6875rem] text-(--ui-text-quaternary)", children: "删除仅限空分区" })
        ] }),
        /* @__PURE__ */ jsx3("div", { className: "flex flex-col gap-1", children: form.partitions.map((p) => /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-2 rounded border border-(--ui-stroke-secondary) px-2 py-1", children: [
          /* @__PURE__ */ jsx3(Codicon2, { name: partitionMeta(p.type).codicon, size: "0.8rem" }),
          /* @__PURE__ */ jsx3("span", { className: "min-w-0 flex-1 truncate font-medium text-(--ui-text-primary)", children: p.name }),
          /* @__PURE__ */ jsx3("span", { className: "text-[0.6875rem] text-(--ui-text-quaternary)", children: partitionMeta(p.type).label }),
          p.fixed ? /* @__PURE__ */ jsx3("span", { className: "text-[0.6875rem] text-(--ui-text-quaternary)", children: "固定" }) : /* @__PURE__ */ jsx3(
            "button",
            {
              type: "button",
              disabled: p.count > 0,
              title: p.count > 0 ? `非空（${p.count} 个文件）不能删除` : "删除分区",
              className: "text-(--ui-text-tertiary) hover:text-(--ui-text-danger) disabled:cursor-not-allowed disabled:opacity-40",
              onClick: () => removePartition(p.name),
              children: /* @__PURE__ */ jsx3(Codicon2, { name: "trash", size: "0.8rem" })
            }
          )
        ] }, p.name)) }),
        /* @__PURE__ */ jsxs3("div", { className: "mt-2 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx3("input", { className: field + " flex-1", value: newName, onChange: (e) => setNewName(e.target.value), placeholder: "新分区名（≤20 字）" }),
          /* @__PURE__ */ jsx3(DialogSelect, { value: newType, onChange: setNewType, options: PARTITION_TYPE_OPTIONS }),
          /* @__PURE__ */ jsx3(Button2, { size: "sm", variant: "outline", onClick: addPartition, children: "＋ 添加" })
        ] })
      ] }),
      /* @__PURE__ */ jsxs3("section", { children: [
        /* @__PURE__ */ jsxs3("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx3("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "定时任务" }),
          /* @__PURE__ */ jsx3("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "立即生效" })
        ] }),
        /* @__PURE__ */ jsx3("div", { className: "flex flex-col gap-1.5", children: SCHEDULE_ROWS.map((row) => /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-2", children: [
          /* @__PURE__ */ jsx3(
            "input",
            {
              type: "checkbox",
              className: "size-3.5",
              checked: form.scheduler[row.key]?.enabled ?? true,
              onChange: (e) => setScheduler(row.key, { enabled: e.target.checked })
            }
          ),
          /* @__PURE__ */ jsx3("span", { className: "w-24 shrink-0 text-(--ui-text-primary)", children: row.label }),
          row.key !== "lifecycle" ? /* @__PURE__ */ jsx3(
            "input",
            {
              className: field + " w-24",
              type: "time",
              value: form.scheduler[row.key]?.time ?? "20:00",
              onChange: (e) => setScheduler(row.key, { time: e.target.value })
            }
          ) : /* @__PURE__ */ jsx3("span", { className: "w-24 text-[0.6875rem] text-(--ui-text-quaternary)", children: "每 10 分钟" }),
          /* @__PURE__ */ jsx3("span", { className: "min-w-0 truncate text-[0.6875rem] text-(--ui-text-quaternary)", children: row.note })
        ] }, row.key)) }),
        /* @__PURE__ */ jsxs3("label", { className: "mt-2 flex items-center gap-2 text-(--ui-text-secondary)", children: [
          /* @__PURE__ */ jsx3("input", { type: "checkbox", className: "size-3.5", checked: form.write_worklog, onChange: (e) => set("write_worklog", e.target.checked) }),
          "日报写入 Obsidian 工作日志"
        ] })
      ] }),
      /* @__PURE__ */ jsxs3("section", { children: [
        /* @__PURE__ */ jsxs3("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx3("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "QQ 投递" }),
          /* @__PURE__ */ jsx3("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "立即生效" })
        ] }),
        /* @__PURE__ */ jsxs3("label", { className: "flex flex-col gap-1 text-(--ui-text-secondary)", children: [
          "投递目标（qqbot:群 openid）",
          /* @__PURE__ */ jsx3("input", { className: field, value: form.deliver_target, onChange: (e) => set("deliver_target", e.target.value), placeholder: "qqbot:..." })
        ] })
      ] }),
      /* @__PURE__ */ jsxs3("section", { children: [
        /* @__PURE__ */ jsxs3("div", { className: "mb-1 flex items-center gap-2", children: [
          /* @__PURE__ */ jsx3("h3", { className: "text-[0.8125rem] font-semibold text-(--ui-text-primary)", children: "回收站保留" }),
          /* @__PURE__ */ jsx3("span", { className: "rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)", children: "下次维护生效" })
        ] }),
        /* @__PURE__ */ jsxs3("div", { className: "flex items-center gap-2", children: [
          /* @__PURE__ */ jsx3(
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
          /* @__PURE__ */ jsx3("span", { className: "text-(--ui-text-secondary)", children: "天" }),
          /* @__PURE__ */ jsx3(
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
      errMsg && /* @__PURE__ */ jsx3("div", { className: "rounded border border-(--ui-stroke-danger) bg-(--ui-bg-elevated) px-2 py-1.5 text-[0.75rem] text-(--ui-text-danger)", children: errMsg }),
      restartHint.length > 0 && /* @__PURE__ */ jsxs3("div", { className: "rounded border border-(--ui-accent)/30 bg-(--ui-accent)/5 px-2 py-1.5 text-[0.75rem] text-(--ui-text-secondary)", children: [
        "已保存。以下设置重启 Hermes 后生效：",
        restartHint.join("、"),
        "（路径 / 分区白名单）"
      ] })
    ] }),
    /* @__PURE__ */ jsxs3(DialogFooter, { children: [
      /* @__PURE__ */ jsx3(Button2, { size: "sm", variant: "outline", onClick: onClose, children: "取消" }),
      /* @__PURE__ */ jsx3(Button2, { size: "sm", onClick: save, disabled: busy, children: busy ? "保存中…" : "保存" })
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
import { jsx as jsx4, jsxs as jsxs4 } from "react/jsx-runtime";
function WbStatusCount() {
  const { data: board } = useQuery3({
    queryFn: () => fetchBoard(),
    queryKey: BOARD_KEY,
    refetchInterval: 3e4
  });
  if (!board || board.totals.pending === 0) {
    return null;
  }
  return /* @__PURE__ */ jsx4(Tip2, { label: `${board.totals.pending} pending / ${board.totals.total} total`, children: /* @__PURE__ */ jsxs4(
    "button",
    {
      className: cn4(
        "inline-flex h-full items-center gap-1 rounded-none px-1.5 text-[0.6875rem] tabular-nums transition-colors",
        "text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground"
      ),
      onClick: () => host3.navigate("/workbench"),
      type: "button",
      children: [
        /* @__PURE__ */ jsx4(Codicon3, { name: "checklist", size: "0.7rem" }),
        /* @__PURE__ */ jsx4("span", { children: board.totals.pending })
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
        render: () => /* @__PURE__ */ jsx4(WorkbenchBoardPage, {})
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
        render: () => /* @__PURE__ */ jsx4(WbStatusCount, {})
      },
      {
        id: "open",
        area: PALETTE_AREA,
        data: {
          id: "workbench.open",
          label: "Workbench: Open board",
          keywords: ["workbench", "board", "tasks", "inbox"],
          run: () => host3.navigate("/workbench")
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
          run: () => host3.navigate("/workbench")
        }
      }
    ]);
  }
};
var plugin_default = plugin;
export {
  plugin_default as default
};
