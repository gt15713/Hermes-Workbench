"""workbench-view 存储层抽象（阶段 1：存储后端可替换，为 SQLite 铺路）。

设计文档 v2 §2.3/§7.2：
- 阶段 1：Repository 抽象完成（存储后端可替换），文件实现保留为默认；
- 阶段 1.5：新增 SQLite 后端（workbench.db），文件 + DB 双写；
- 阶段 2：双写稳定后事实源切到 DB，文件降级为可选只读镜像。

本文件定义 WorkbenchRepo 接口 + FileRepo（文件实现）+ SqliteRepo（DB 实现）
+ DualRepo（阶段 1.5 双写包装）。
所有写路径必须经 repo 原语（_safe_resolve + 锁 + 原子写），禁止直接 unlink。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path

from contract import PARTITION_NAMES  # noqa: F401 - 兼容旧引用
from workbench_config import get_partition_names, get_root

_log = logging.getLogger("workbench-view")

WORKBENCH_ROOT = Path(get_root())

# 写操作全局锁（进程内串行化读-改-写；跨进程用 FileLock）
_WRITE_LOCK = threading.RLock()


class FileLock:
    """C4（P1-3）：跨进程 advisory file lock（Windows msvcrt 非阻塞 + 轮询；超时 → TimeoutError）。

    - 锁文件：{目标文件}.lock（释放后尽力清理）
    - 非 Windows 无 msvcrt → 降级无锁（读环境不阻塞）
    - 用法：with FileLock(path): ...（写前获取、写后释放）
    """

    def __init__(self, path: Path, timeout: float = 3.0, poll: float = 0.05) -> None:
        self.lock_path = Path(str(path) + ".lock")
        self.timeout = timeout
        self.poll = poll
        self._fd = None

    def __enter__(self) -> "FileLock":
        try:
            import msvcrt
        except ImportError:  # pragma: no cover - 非 Windows
            return self
        import os as _os
        import time as _time

        self._fd = open(self.lock_path, "a+")
        # msvcrt.locking 锁定的是「当前文件位置」起的字节区间：文件必须 ≥1 字节且指针归零
        self._fd.seek(0, 2)
        if self._fd.tell() == 0:
            self._fd.write("0")
            self._fd.flush()
        self._fd.seek(0)
        deadline = _time.monotonic() + self.timeout
        while True:
            try:
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                self._fd.seek(0)
                self._fd.truncate()
                self._fd.write(str(_os.getpid()))
                self._fd.flush()
                return self
            except OSError:
                if _time.monotonic() >= deadline:
                    self._fd.close()
                    self._fd = None
                    raise TimeoutError(f"workbench file lock timeout: {self.lock_path}") from None
                _time.sleep(self.poll)

    def __exit__(self, *exc) -> None:
        if self._fd is None:
            return
        try:
            import msvcrt

            self._fd.seek(0)
            msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._fd.close()
            self._fd = None
            self._try_remove_lock()

    def _try_remove_lock(self) -> None:
        """释放后尽力清理锁文件：内容仍为本进程 PID 才删（他人已重新加锁则不删）。"""
        import os as _os

        try:
            if self.lock_path.is_file():
                cur = self.lock_path.read_text(encoding="utf-8", errors="replace").strip()
                if cur == str(_os.getpid()) or cur == "":
                    self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass


class WorkbenchRepo(ABC):
    """工作台存储接口。存储后端（文件/SQLite）可替换。"""

    root: Path

    # ---------- 路径解析 ----------
    @abstractmethod
    def resolve(self, dirname: str, filename: str) -> Path | None:
        """校验 dirname/filename 后返回安全绝对路径；非法返回 None。"""

    @abstractmethod
    def partition_dir(self, dirname: str) -> Path:
        """返回分区目录（不存在不创建）。"""

    # ---------- 读 ----------
    @abstractmethod
    def list_files(self, dirname: str) -> list[Path]:
        """列出分区内 *.md 文件（按 mtime 倒序）。"""

    @abstractmethod
    def read_text(self, path: Path) -> str:
        """读取文件全文（UTF-8，容错 replace）。"""

    @abstractmethod
    def exists(self, path: Path) -> bool:
        """文件是否存在。"""

    @abstractmethod
    def mtime(self, path: Path) -> float:
        """文件 mtime（秒）。"""

    # ---------- 写 ----------
    @abstractmethod
    def write_text(self, path: Path, text: str) -> None:
        """原子写：临时文件 + os.replace（Windows 同卷原子）。"""

    @abstractmethod
    def move(self, src: Path, dst: Path) -> Path:
        """move 容错：占用重试 → 回退复制+删除。返回最终目标路径。"""

    @abstractmethod
    def delete(self, path: Path) -> None:
        """物理删除（仅回收站 TTL 与显式授权清理使用；常规删除走 trash）。"""

    # ---------- 日志 ----------
    @abstractmethod
    def append_action_log(self, action: str, detail: str) -> None:
        """追加一条工作台日志到 日志/YYYY-MM-DD.md（自动建目录/文件）。"""

    @abstractmethod
    def append_done_log(self, log: Path, section_title: str, entry: str) -> None:
        """追加归档索引日志，条目去重（同 wikilink 目标只记一次）。"""


class FileRepo(WorkbenchRepo):
    """文件系统实现（阶段 1 默认）。"""

    def __init__(self, root: Path | str | None = None, lock_timeout: float = 3.0) -> None:
        self.root = Path(root) if root is not None else WORKBENCH_ROOT
        self._lock = _WRITE_LOCK  # 进程内锁（与旧模块级锁一致）
        self.lock_timeout = lock_timeout  # C4：跨进程文件锁超时（秒）

    # ---------- 路径解析 ----------
    def resolve(self, dirname: str, filename: str) -> Path | None:
        if dirname not in get_partition_names():
            return None
        p = (self.root / dirname / filename).resolve()
        partition_root = (self.root / dirname).resolve()
        if not p.is_relative_to(partition_root):
            return None
        return p

    def partition_dir(self, dirname: str) -> Path:
        return self.root / dirname

    # ---------- 读 ----------
    def list_files(self, dirname: str) -> list[Path]:
        d = self.root / dirname
        if not d.is_dir():
            return []
        return sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def exists(self, path: Path) -> bool:
        return path.is_file()

    def mtime(self, path: Path) -> float:
        return path.stat().st_mtime

    # ---------- 写 ----------
    def write_text(self, path: Path, text: str) -> None:
        # C4（P1-3）：跨进程 advisory lock（写前获取、写后释放；超时 → 抛异常 = 告警+跳过，不静默覆盖）
        with FileLock(path, timeout=self.lock_timeout):
            self._write_text_locked(path, text)

    def _write_text_locked(self, path: Path, text: str) -> None:
        with self._lock:
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            max_retry = 2
            for attempt in range(max_retry):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    if attempt < max_retry - 1:
                        import time
                        time.sleep(0.3)
                        continue
                    # 回退：复制 + 删除（与 move 同语义）
                    shutil.copy2(tmp, path)
                    try:
                        tmp.unlink()
                    except OSError:
                        pass

    def move(self, src: Path, dst: Path) -> Path:
        with self._lock:
            max_retry = 2
            for attempt in range(max_retry):
                try:
                    src.rename(dst)
                    return dst
                except PermissionError:
                    if attempt < max_retry - 1:
                        import time
                        time.sleep(0.3)
                        continue
                    # 回退：复制 + 删除
                    shutil.copy2(src, dst)
                    try:
                        src.unlink()
                    except OSError:
                        pass  # 源被占用无法删，保留原文件（数据不丢）
            return dst

    def delete(self, path: Path) -> None:
        with self._lock:
            try:
                path.unlink()
            except OSError:
                _log.warning("workbench: delete failed: %s", path)

    # ---------- 日志 ----------
    def append_action_log(self, action: str, detail: str) -> None:
        try:
            log_dir = self.root / "日志"
            log_dir.mkdir(exist_ok=True)
            log = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"
            ts = datetime.now().strftime("%H:%M")
            line = f"\n## {ts} {action}\n\n- {detail}\n"
            if log.exists():
                text = log.read_text(encoding="utf-8", errors="replace")
            else:
                text = "# 工作台日志 " + datetime.now().strftime("%Y-%m-%d") + "\n"
            self.write_text(log, text + line)
        except OSError as e:
            _log.warning("log action failed: %s", e)

    def append_done_log(self, log: Path, section_title: str, entry: str) -> None:
        log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else f"# 已处理 {date.today():%Y-%m-%d}\n"
        # 提取 wikilink 目标：[[X| 或 [[X]] → X
        m = re.search(r"\[\[([^\]|]+)(?:\||\]\])", entry)
        key = m.group(1).strip() if m else entry.strip()
        if f"[[{key}|" not in log_text and f"[[{key}]]" not in log_text:
            log_text += f"\n## {section_title}\n\n- {entry}\n"
            self.write_text(log, log_text)


# ---------- 阶段 1.5：SQLite 后端 + 双写（DualRepo） ----------

# 阶段 2：读路径默认切 DB（workbench.db 事实源），文件降级为可选只读镜像。
# 回滚通道：WORKBENCH_READ_FROM_DB=0 时读回文件（灰度回滚用）。
_READ_FROM_DB = os.environ.get("WORKBENCH_READ_FROM_DB", "1").strip().lower() not in ("0", "false", "no", "")

# workbench.db 位置：插件目录内（与 kanban.db 同级概念，纳入每日备份 cron）
WORKBENCH_DB_PATH = Path(
    os.environ.get(
        "WORKBENCH_DB",
        str(Path(__file__).resolve().parent.parent / "workbench.db"),
    )
)

# schema（tasks 镜像文件 + task_events 事件流；阶段 4 事件通道直接复用）
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    partition  TEXT NOT NULL,
    filename   TEXT NOT NULL,
    mtime      REAL NOT NULL,
    content    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(partition, filename)
);
CREATE TABLE IF NOT EXISTS task_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    partition  TEXT NOT NULL,
    filename   TEXT NOT NULL,
    kind       TEXT NOT NULL,
    payload    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_partition ON tasks(partition);
CREATE INDEX IF NOT EXISTS idx_events_lookup ON task_events(partition, filename, created_at);
-- 阶段 4：mtime 索引（board 增量/archive 扫描）+ 事件 kind 索引（SSE 按 kind 过滤增量）
CREATE INDEX IF NOT EXISTS idx_tasks_mtime ON tasks(mtime);
CREATE INDEX IF NOT EXISTS idx_events_kind ON task_events(kind, id);
-- 阶段 2.5：QQ 收录幂等 outbox（message_id 唯一；status=done 视为已消费，processing=崩溃残留可重放）
CREATE TABLE IF NOT EXISTS ingest_messages (
    message_id TEXT PRIMARY KEY,
    partition  TEXT NOT NULL,
    filename   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'processing',
    created_at TEXT NOT NULL
);
"""


class WorkbenchConflictError(RuntimeError):
    """并发写冲突（mtime 前置校验失败）。"""


def _db_connect(db_path: Path) -> sqlite3.Connection:
    """WAL + busy_timeout 连接（参考官方 kanban 的 WAL 并发策略）。"""
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SqliteRepo(WorkbenchRepo):
    """SQLite 后端实现。阶段 1.5 作镜像（双写）；阶段 2 可作事实源。

    路径 ↔ (partition, filename) 映射：path 必须位于 root 内且第一段是合法分区名。
    每次操作短连接（读少写少场景足够，避开跨线程共享连接的坑）。
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        root: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else WORKBENCH_DB_PATH
        self.root = Path(root) if root is not None else WORKBENCH_ROOT
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.executescript(_SCHEMA_SQL)
                conn.commit()
            finally:
                conn.close()

    def _split(self, path: Path) -> tuple[str | None, str | None]:
        """绝对路径 → (partition, filename)；不在工作台内/非法分区返回 (None, None)。"""
        p = Path(path).resolve()
        try:
            rel = p.relative_to(self.root)
        except ValueError:
            return None, None
        parts = rel.parts
        if len(parts) < 2 or parts[0] not in PARTITION_NAMES:
            return None, None
        return parts[0], str(Path(*parts[1:])).replace("\\", "/")

    # ---------- 读（阶段 2 事实源用；当前读路径仍走 FileRepo） ----------

    def resolve(self, dirname: str, filename: str) -> Path | None:
        if dirname not in PARTITION_NAMES:
            return None
        return self.root / dirname / filename

    def partition_dir(self, dirname: str) -> Path:
        return self.root / dirname

    def list_files(self, dirname: str) -> list[Path]:
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT filename FROM tasks WHERE partition=? ORDER BY mtime DESC",
                    (dirname,),
                ).fetchall()
                return [self.root / dirname / r["filename"] for r in rows]
            finally:
                conn.close()

    def read_text(self, path: Path) -> str:
        partition, filename = self._split(path)
        if partition is None:
            return ""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT content FROM tasks WHERE partition=? AND filename=?",
                    (partition, filename),
                ).fetchone()
                return row["content"] if row else ""
            finally:
                conn.close()

    def exists(self, path: Path) -> bool:
        partition, filename = self._split(path)
        if partition is None:
            return False
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT 1 FROM tasks WHERE partition=? AND filename=?",
                    (partition, filename),
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    def mtime(self, path: Path) -> float:
        partition, filename = self._split(path)
        if partition is None:
            return 0.0
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT mtime FROM tasks WHERE partition=? AND filename=?",
                    (partition, filename),
                ).fetchone()
                return row["mtime"] if row else 0.0
            finally:
                conn.close()

    # ---------- 写（镜像同步 + 事件流） ----------

    def _upsert(self, partition: str, filename: str, mtime: float, content: str, status: str) -> None:
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.execute(
                    """INSERT INTO tasks (partition, filename, mtime, content, status, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(partition, filename) DO UPDATE SET
                         mtime=excluded.mtime, content=excluded.content,
                         status=excluded.status, updated_at=excluded.updated_at""",
                    (partition, filename, mtime, content, status, _now_str()),
                )
                conn.commit()
            finally:
                conn.close()

    def _event(self, partition: str, filename: str, kind: str, payload: str) -> None:
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.execute(
                    "INSERT INTO task_events (partition, filename, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (partition, filename, kind, payload, _now_str()),
                )
                conn.commit()
            finally:
                conn.close()

    def record_ingest_created(self, partition: str, filename: str, payload: str) -> None:
        """API-B（B1）：记录一条带信息的 created 业务事件（幂等不重复）。

        - 镜像 upsert 已写 payload 空的 created 行（首次收录）→ UPDATE 补信息
        - 无空 created 行（当天第 2+ 次收录，镜像走 updated）→ INSERT 业务事件
        两种场景恰好一条带信息的 created；失败仅告警（outbox 幂等不受影响）。
        """
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                cur = conn.execute(
                    "UPDATE task_events SET payload=? WHERE kind='created' AND partition=? AND filename=? AND (payload IS NULL OR payload='')",
                    (payload, partition, filename),
                )
                if cur.rowcount == 0:
                    conn.execute(
                        "INSERT INTO task_events (partition, filename, kind, payload, created_at) VALUES (?, ?, 'created', ?, ?)",
                        (partition, filename, payload, _now_str()),
                    )
                conn.commit()
            finally:
                conn.close()

    def record_updated_payload(self, partition: str, filename: str, payload: str) -> None:
        """Attach business context to the latest mirror-generated updated event."""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.execute(
                    """UPDATE task_events SET payload=? WHERE id=(
                           SELECT id FROM task_events
                           WHERE kind='updated' AND partition=? AND filename=?
                             AND (payload IS NULL OR payload='')
                           ORDER BY id DESC LIMIT 1
                       )""",
                    (payload, partition, filename),
                )
                conn.commit()
            finally:
                conn.close()

    def get_mirror_mtime(self, partition: str, filename: str) -> float | None:
        """P0-3（B2）：镜像行 mtime（无行返回 None）。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT mtime FROM tasks WHERE partition=? AND filename=?", (partition, filename)
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()

    def get_status(self, partition: str, filename: str) -> str:
        """镜像行 status（无行/为空 → ''；2026-08-23 自愈修复用）。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT status FROM tasks WHERE partition=? AND filename=?", (partition, filename)
                ).fetchone()
                return str(row[0] or "") if row else ""
            finally:
                conn.close()

    def set_status(self, partition: str, filename: str, status: str) -> None:
        """仅刷新镜像行 status（不动 content/mtime；2026-08-23 自愈修复用）。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.execute(
                    "UPDATE tasks SET status=?, updated_at=? WHERE partition=? AND filename=?",
                    (status, _now_str(), partition, filename),
                )
                conn.commit()
            finally:
                conn.close()

    def list_mirror_rows(self) -> list[tuple[str, str, float, str]]:
        """P0-3（B2）：全部镜像行 (partition, filename, mtime, status)。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                return [tuple(r) for r in conn.execute(
                    "SELECT partition, filename, mtime, status FROM tasks"
                ).fetchall()]
            finally:
                conn.close()

    def delete_mirror_row(self, partition: str, filename: str) -> None:
        """P0-3（B2）：删除镜像行（真孤儿清除；与 verify 收敛一致）。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.execute("DELETE FROM tasks WHERE partition=? AND filename=?", (partition, filename))
                conn.commit()
            finally:
                conn.close()

    def write_text(self, path: Path, text: str, expected_mtime: float | None = None) -> None:
        partition, filename = self._split(path)
        if partition is None:
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        # 阶段 2.5：mtime 前置校验——目标已存在且调用方持有旧版本（并发期间被改）→ 拒绝
        if expected_mtime is not None:
            self.check_conflict(path, expected_mtime)
        m = re.search(r"^status:\s*(\S+)", text, re.M)
        status = m.group(1).strip() if m else ""
        existed = self.exists(path)
        self._upsert(partition, filename, mtime, text, status)
        self._event(partition, filename, "updated" if existed else "created", "")

    def check_conflict(self, path: Path, expected_mtime: float | None) -> None:
        """mtime 前置校验：目标存在且 DB 版本比调用方持有的新 → 抛 WorkbenchConflictError。"""
        partition, filename = self._split(path)
        if partition is None or expected_mtime is None:
            return
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT mtime FROM tasks WHERE partition=? AND filename=?",
                    (partition, filename),
                ).fetchone()
            finally:
                conn.close()
        if row is not None and abs(row["mtime"] - expected_mtime) > 0.01:
            raise WorkbenchConflictError(
                f"并发写冲突: {path} 已被修改（DB mtime={row['mtime']:.2f}, 持有={expected_mtime:.2f}）"
            )

    # ---------- 阶段 2.5：QQ 收录幂等 outbox ----------

    def ingest_exists(self, message_id: str) -> bool:
        """message_id 是否已消费（status=done）。processing（崩溃残留）→ 视为未消费，可重放。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT status FROM ingest_messages WHERE message_id=?",
                    (message_id,),
                ).fetchone()
            finally:
                conn.close()
        return row is not None and row["status"] == "done"

    def ingest_status(self, message_id: str) -> str | None:
        """Return the durable claim state used to recover interrupted commands."""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT status FROM ingest_messages WHERE message_id=?",
                    (message_id,),
                ).fetchone()
            finally:
                conn.close()
        return str(row["status"]) if row is not None else None

    def ingest_release_processing(self, message_id: str) -> None:
        """Release a claim after a handled, deterministic failure."""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.execute(
                    "DELETE FROM ingest_messages WHERE message_id=? AND status='processing'",
                    (message_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def agent_ingest_count(self, day: str) -> int:
        """C3（P1-1）：Agent 源每日 ingest 计数（message_id `agent-` 前缀；Business Rule 4.8 上限 20 条）。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM ingest_messages "
                    "WHERE message_id LIKE 'agent-%' AND substr(created_at, 1, 10) = ?",
                    (day,),
                ).fetchone()
                return int(row["n"]) if row else 0
            finally:
                conn.close()

    def ingest_upsert(self, message_id: str, partition: str, filename: str, status: str) -> None:
        """记录/更新 outbox 状态：processing（claim）→ done（消费完成）。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO ingest_messages (message_id, partition, filename, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (message_id, partition, filename, status, _now_str()),
                )
                conn.commit()
            finally:
                conn.close()

    def move(self, src: Path, dst: Path) -> Path:
        src_p, src_f = self._split(src)
        dst_p, dst_f = self._split(dst)
        if src_p is None or dst_p is None:
            return dst
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT content, mtime, status FROM tasks WHERE partition=? AND filename=?",
                    (src_p, src_f),
                ).fetchone()
                if row is not None:
                    # 清目标旧行（覆盖场景），迁移内容
                    conn.execute(
                        "DELETE FROM tasks WHERE partition=? AND filename=?",
                        (dst_p, dst_f),
                    )
                    conn.execute(
                        "INSERT INTO tasks (partition, filename, mtime, content, status, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (dst_p, dst_f, row["mtime"], row["content"], row["status"], _now_str()),
                    )
                    conn.execute(
                        "DELETE FROM tasks WHERE partition=? AND filename=?",
                        (src_p, src_f),
                    )
                # 运行历史跟随任务实体移动。否则归档/恢复后的卡片只能看到
                # 一条 moved，归档前的 created/updated/execution 事件会留在旧分区。
                conn.execute(
                    "UPDATE task_events SET partition=?, filename=?"
                    " WHERE partition=? AND filename=?",
                    (dst_p, dst_f, src_p, src_f),
                )
                conn.execute(
                    "INSERT INTO task_events (partition, filename, kind, payload, created_at) VALUES (?, ?, 'moved', ?, ?)",
                    (dst_p, dst_f, f"{src_p}/{src_f} -> {dst_p}/{dst_f}", _now_str()),
                )
                conn.commit()
            finally:
                conn.close()
        return dst

    def delete(self, path: Path) -> None:
        partition, filename = self._split(path)
        if partition is None:
            return
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.execute(
                    "DELETE FROM tasks WHERE partition=? AND filename=?",
                    (partition, filename),
                )
                conn.execute(
                    "INSERT INTO task_events (partition, filename, kind, payload, created_at) VALUES (?, ?, 'deleted', '', ?)",
                    (partition, filename, _now_str()),
                )
                conn.commit()
            finally:
                conn.close()

    def append_action_log(self, action: str, detail: str) -> None:
        # Phase 0-4（A1）：kind=log 事件无消费方（Codex 实测占 24%），DB 镜像写入移除；
        # 文件侧日志（日志/YYYY-MM-DD.md）由 FileRepo.append_action_log 负责，不受影响。
        pass

    def append_done_log(self, log: Path, section_title: str, entry: str) -> None:
        # Phase 0-4（A1）：kind=done_log 事件无消费方，DB 镜像写入移除；
        # 已处理索引文件由 FileRepo.append_done_log 负责，不受影响。
        pass

    # ---------- 校验/测试辅助（一致性校验脚本复用） ----------

    def _all_tasks(self) -> list[sqlite3.Row]:
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                return conn.execute(
                    "SELECT partition, filename, mtime, content, status, updated_at FROM tasks"
                ).fetchall()
            finally:
                conn.close()

    def _all_events(self) -> list[sqlite3.Row]:
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                return conn.execute(
                    "SELECT partition, filename, kind, payload, created_at FROM task_events"
                ).fetchall()
            finally:
                conn.close()

    # ---------- 阶段 4：事件通道 ----------

    def list_events(self, since_id: int = 0, limit: int = 200) -> list[dict]:
        """按 id 增量拉取 task_events（SSE 事件通道用）。id 自增单调，since_id 断点续拉。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT id, partition, filename, kind, payload, created_at FROM task_events"
                    " WHERE id > ? ORDER BY id ASC LIMIT ?",
                    (since_id, limit),
                ).fetchall()
                return [
                    {
                        "id": r[0],
                        "partition": r[1],
                        "filename": r[2],
                        "kind": r[3],
                        "payload": r[4] or "",
                        "ts": r[5],
                    }
                    for r in rows
                ]
            finally:
                conn.close()

    def list_file_events(self, partition: str, filename: str, limit: int = 50) -> list[dict]:
        """按 partition+filename 过滤 task_events，created_at 倒序（运行历史用）。

        Task 5.2 批次 1：抽屉「运行历史」标签页数据源。
        """
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT id, partition, filename, kind, payload, created_at FROM task_events"
                    " WHERE partition = ? AND filename = ?"
                    " ORDER BY id DESC LIMIT ?",
                    (partition, filename, limit),
                ).fetchall()
                return [
                    {
                        "id": r[0],
                        "partition": r[1],
                        "filename": r[2],
                        "kind": r[3],
                        "payload": r[4] or "",
                        "ts": r[5],
                    }
                    for r in rows
                ]
            finally:
                conn.close()

    def health(self) -> bool:
        """DB 可读性检查（/health 用）。"""
        with self._lock:
            conn = _db_connect(self.db_path)
            try:
                conn.execute("SELECT 1").fetchone()
                return True
            finally:
                conn.close()


class DualRepo(WorkbenchRepo):
    """双写后端（阶段 2 起：读走 DB 事实源，写仍双写文件 + SQLite）。

    阶段 1.5：读走文件（文件为事实源）、写双写；
    阶段 2：读切 DB（workbench.db 唯一事实源），文件降级为可选只读镜像（默认关闭）；
    灰度期写仍双写（文件作为过渡副本）；完整切换（阶段 2.5 后）再评估停止文件写。

    容错：文件写失败 → 不碰 DB；DB 读失败 → 回退文件读（warning 不阻断）；
    DB 写失败 → 记录 warning 不阻断业务（一致性由每日校验兜底）。
    回滚通道：WORKBENCH_READ_FROM_DB=0 时读回文件。
    """

    def __init__(
        self,
        file_repo: FileRepo | None = None,
        sqlite_repo: SqliteRepo | None = None,
        read_from_db: bool | None = None,
    ) -> None:
        self.file = file_repo or FileRepo()
        self.db = sqlite_repo or SqliteRepo()
        self.read_from_db = _READ_FROM_DB if read_from_db is None else read_from_db
        self._lock = self.file._lock

    @property
    def root(self) -> Path:
        return self.file.root

    @root.setter
    def root(self, v: Path | str) -> None:
        self.file.root = Path(v)

    # ---------- 读（阶段 2：走 DB 事实源；异常回退文件） ----------

    def resolve(self, dirname: str, filename: str) -> Path | None:
        return self.file.resolve(dirname, filename)

    def partition_dir(self, dirname: str) -> Path:
        return self.file.partition_dir(dirname)

    def list_files(self, dirname: str) -> list[Path]:
        if self.read_from_db:
            try:
                return self.db.list_files(dirname)
            except Exception as e:  # noqa: BLE001
                _log.warning("workbench: db list failed, fallback file: %s", e)
        return self.file.list_files(dirname)

    def read_text(self, path: Path) -> str:
        if self.read_from_db:
            try:
                return self.db.read_text(path)
            except Exception as e:  # noqa: BLE001
                _log.warning("workbench: db read failed, fallback file: %s", e)
        return self.file.read_text(path)

    def exists(self, path: Path) -> bool:
        if self.read_from_db:
            try:
                return self.db.exists(path)
            except Exception as e:  # noqa: BLE001
                _log.warning("workbench: db exists failed, fallback file: %s", e)
        return self.file.exists(path)

    def mtime(self, path: Path) -> float:
        if self.read_from_db:
            try:
                return self.db.mtime(path)
            except Exception as e:  # noqa: BLE001
                _log.warning("workbench: db mtime failed, fallback file: %s", e)
        return self.file.mtime(path)

    # ---------- 写（灰度期仍双写：文件优先，DB 镜像失败仅告警） ----------

    def write_text(self, path: Path, text: str, expected_mtime: float | None = None) -> None:
        from workbench_config import get_storage_mode

        # 阶段 2.5：mtime 前置校验（冲突 → 上抛，调用方回滚/重试；不吞异常）
        if expected_mtime is not None:
            self.db.check_conflict(path, expected_mtime)
        mode = get_storage_mode()
        if mode == "db_only":
            self.db.write_text(path, text)
            return
        self.file.write_text(path, text)
        if mode == "file_only":
            return
        try:
            self.db.write_text(path, text)
        except Exception as e:  # noqa: BLE001
            _log.warning("workbench: db mirror write failed: %s", e)

    def move(self, src: Path, dst: Path) -> Path:
        from workbench_config import get_storage_mode

        mode = get_storage_mode()
        result = self.file.move(src, dst) if mode != "db_only" else dst
        try:
            self.db.move(src, dst)
        except Exception as e:  # noqa: BLE001
            _log.warning("workbench: db mirror move failed: %s", e)
        return result

    def delete(self, path: Path) -> None:
        from workbench_config import get_storage_mode

        if get_storage_mode() != "db_only":
            self.file.delete(path)
        try:
            self.db.delete(path)
        except Exception as e:  # noqa: BLE001
            _log.warning("workbench: db mirror delete failed: %s", e)

    def event(self, partition: str, filename: str, kind: str, payload: str = "") -> None:
        """写入 task_events 事件表。"""
        try:
            self.db._event(partition, filename, kind, payload)
        except Exception as e:  # noqa: BLE001
            _log.warning("workbench: db event failed: %s", e)

    def record_ingest_created(self, partition: str, filename: str, payload: str) -> None:
        """API-B（B1）：记录一条带信息的 created 业务事件（UPDATE 空行或 INSERT，幂等）。"""
        try:
            self.db.record_ingest_created(partition, filename, payload)
        except Exception as e:  # noqa: BLE001
            _log.warning("workbench: db record_ingest_created failed: %s", e)

    def record_updated_payload(self, partition: str, filename: str, payload: str) -> None:
        """Enrich the latest updated event without creating a duplicate event."""
        try:
            self.db.record_updated_payload(partition, filename, payload)
        except Exception as e:  # noqa: BLE001
            _log.warning("workbench: db record_updated_payload failed: %s", e)

    def append_action_log(self, action: str, detail: str) -> None:
        self.file.append_action_log(action, detail)
        try:
            self.db.append_action_log(action, detail)
        except Exception as e:  # noqa: BLE001
            _log.warning("workbench: db mirror log failed: %s", e)

    def append_done_log(self, log: Path, section_title: str, entry: str) -> None:
        self.file.append_done_log(log, section_title, entry)
        try:
            self.db.append_done_log(log, section_title, entry)
        except Exception as e:  # noqa: BLE001
            _log.warning("workbench: db mirror done_log failed: %s", e)

    def sync_from_files(self) -> dict[str, int]:
        """P0-3（B2）：读时懒同步——逐文件 mtime 对比镜像，不一致增量重摄；孤儿行清除。

        - 文件 mtime != DB mtime → 重摄（_parse_md）→ upsert（重摄前 re-stat 防竞态，变了跳过本轮）
        - DB 有行但文件不存在 → 删除镜像行（真孤儿；与 verify 收敛一致）
        - 解析失败 → 保留旧镜像，跳过（绝不覆盖用户文件/镜像）
        - 纯镜像同步，不产生业务事件；仅刷新 tasks 行（status 变化由 board 读时体现）
        """
        from wb_utils import _parse_md  # 延迟 import（wb_utils 无 repo 依赖，避免顶层耦合）

        scanned = reingested = removed = repaired = 0
        for dirname in PARTITION_NAMES:
            try:
                files = self.file.list_files(dirname)
            except OSError:
                continue
            for f in files:
                scanned += 1
                try:
                    fmtime = f.stat().st_mtime
                except OSError:
                    continue
                partition, filename = self.db._split(f)
                if partition is None or filename is None:
                    continue
                db_mtime = self.db.get_mirror_mtime(partition, filename)
                if db_mtime is not None and abs(db_mtime - fmtime) < 1e-6:
                    # 2026-08-23：mtime 一致但镜像 status 为空 → 文件侧已含 frontmatter status
                    # （agent 直接写库/搬文件导致的漂移），读板时自愈刷新，不重摄全文。
                    if not self.db.get_status(partition, filename):
                        try:
                            info = _parse_md(f)
                            status = str(info.get("status") or "")
                        except Exception:  # noqa: BLE001
                            continue
                        if status:
                            self.db.set_status(partition, filename, status)
                            repaired += 1
                    continue  # 一致，跳过（增量）
                # 不一致 → 重摄前 re-stat 防竞态（扫描期间被写则跳过本轮）
                try:
                    fmtime2 = f.stat().st_mtime
                except OSError:
                    continue
                if abs(fmtime2 - fmtime) > 1e-6:
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    info = _parse_md(f)
                    status = str(info.get("status") or "")
                except Exception:  # noqa: BLE001
                    continue  # 解析失败：保留旧镜像，不覆盖
                self.db._upsert(partition, filename, fmtime2, text, status)
                reingested += 1
        # 孤儿行清除：DB 有行但文件不存在（真孤儿；与 verify --fix 语义一致）
        for partition, filename, _, _ in self.db.list_mirror_rows():
            try:
                p = self.file.resolve(partition, filename)
                if p is None or not p.is_file():
                    self.db.delete_mirror_row(partition, filename)
                    removed += 1
            except OSError:
                continue
        return {"scanned": scanned, "reingested": reingested, "removed": removed, "repaired": repaired}


# 模块级单例（plugin_api 兼容：默认实例）
# 阶段 1.5：文件 + SQLite 双写（DualRepo 包装 FileRepo + SqliteRepo）
_repo = DualRepo()

# 兼容别名：plugin_api 等 `from repo import _repo as file_repo` 拿到同一实例
file_repo = _repo
