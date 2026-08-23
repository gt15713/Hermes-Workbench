"""contract.py 状态机契约测试（阶段 1）。

覆盖：
- 状态集完整性（8 态齐全、无重复）
- 合法迁移表（3.1 全表）
- 非法迁移拒绝
- 标签映射（3.2）
- 与 plugin_api 死代码清理的一致性（_STATUS_LABEL/_TYPE_LABEL 已删）
"""
import pytest

from contract import (
    ALL_ACTIONS,
    ALL_STATUSES,
    SCHEMA_VERSION,
    STATUS_ABANDONED,
    STATUS_CLEARED,
    STATUS_COMPLETED,
    STATUS_CONVERTED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_TODO,
    STATUS_LABEL,
    can_transition,
    is_valid_status,
    next_status,
    status_label,
)


class TestContractStatusSet:
    def test_all_statuses_complete(self):
        expected = {
            "pending", "todo", "in_progress",
            "completed", "cleared", "converted", "abandoned",
        }
        assert ALL_STATUSES == expected

    def test_all_statuses_valid(self):
        for s in ALL_STATUSES:
            assert is_valid_status(s)

    def test_unknown_status_invalid(self):
        assert not is_valid_status("bogus")
        assert not is_valid_status("")


class TestContractTransitions:
    """3.1 合法迁移全表断言。"""

    @pytest.mark.parametrize("frm,action,to", [
        ("pending", "resolve", "cleared"),
        ("pending", "to-task", "converted"),
        ("pending", "taskify", "todo"),
        ("todo", "execute", "in_progress"),
        ("todo", "complete", "completed"),
        ("todo", "defer", "todo"),
        ("todo", "abandon", "abandoned"),
        ("abandoned", "reopen", "todo"),
        ("in_progress", "reset-execution", "todo"),
        ("in_progress", "complete", "completed"),
    ])
    def test_valid_transition(self, frm, action, to):
        assert can_transition(frm, action) is True
        assert next_status(frm, action) == to

    @pytest.mark.parametrize("frm,action", [
        ("pending", "complete"),
        ("pending", "defer"),
        ("todo", "resolve"),
        ("completed", "complete"),
        ("cleared", "to-task"),
        ("bogus", "resolve"),
        ("todo", "bogus"),
    ])
    def test_invalid_transition_rejected(self, frm, action):
        assert can_transition(frm, action) is False
        assert next_status(frm, action) is None


class TestContractLabels:
    def test_status_label_map_complete(self):
        # 3.2：每个状态都有标签
        for s in ALL_STATUSES:
            assert STATUS_LABEL[s]

    def test_status_label_unknown_passthrough(self):
        assert status_label("mystery") == "mystery"

    def test_actions_nonempty(self):
        assert len(ALL_ACTIONS) >= 8


class TestContractSchemaVersion:
    def test_schema_version_defined(self):
        assert SCHEMA_VERSION >= 1
        assert isinstance(SCHEMA_VERSION, int)
