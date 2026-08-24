import json
from datetime import datetime

from qq_health import assess_qq_health


def _write_state(path, state):
    path.write_text(json.dumps(state), encoding="utf-8")


def test_connected_recent_c2c_and_group_mention_are_reported_without_identifiers(tmp_path):
    state_path = tmp_path / "gateway_state.json"
    log_path = tmp_path / "gateway.log"
    adapter_path = tmp_path / "adapter.py"
    _write_state(
        state_path,
        {"platforms": {"qqbot": {"state": "connected", "updated_at": "2026-08-24T06:08:44+00:00"}}},
    )
    log_path.write_text(
        "2026-08-24 12:15:22,661 INFO gateway.run: inbound message: platform=qqbot "
        "user=private-openid chat=private-openid msg='private secret'\n"
        "2026-08-24 14:08:36,518 INFO gateway.run: inbound message: platform=qqbot "
        "user=member-openid chat=group-openid msg='group secret'\n",
        encoding="utf-8",
    )
    adapter_path.write_text('"GROUP_AT_MESSAGE_CREATE"', encoding="utf-8")

    result = assess_qq_health(
        state_path=state_path,
        log_path=log_path,
        adapter_path=adapter_path,
        now=datetime(2026, 8, 24, 14, 10, 0),
        recent_hours=24,
    )

    assert result == {
        "status": "yellow",
        "transport": {"status": "green", "detail": "QQ WebSocket 已连接"},
        "c2c": {"status": "green", "detail": "最近私聊摄取：2026-08-24 12:15:22"},
        "group": {"status": "green", "detail": "最近群聊摄取：2026-08-24 14:08:36"},
        "full_group": {
            "status": "yellow",
            "detail": "当前适配器仅确认群 @ 消息；普通群消息等待上游兼容",
        },
    }
    serialized = json.dumps(result, ensure_ascii=False)
    assert "private-openid" not in serialized
    assert "group-openid" not in serialized
    assert "secret" not in serialized


def test_connected_without_recent_intake_is_yellow_not_false_green(tmp_path):
    state_path = tmp_path / "gateway_state.json"
    log_path = tmp_path / "gateway.log"
    adapter_path = tmp_path / "adapter.py"
    _write_state(state_path, {"platforms": {"qqbot": {"state": "connected"}}})
    log_path.write_text("2026-08-20 09:00:00,000 INFO gateway.run: started\n", encoding="utf-8")
    adapter_path.write_text('"GROUP_AT_MESSAGE_CREATE"', encoding="utf-8")

    result = assess_qq_health(
        state_path=state_path,
        log_path=log_path,
        adapter_path=adapter_path,
        now=datetime(2026, 8, 24, 14, 10, 0),
        recent_hours=24,
    )

    assert result["status"] == "yellow"
    assert result["transport"]["status"] == "green"
    assert result["c2c"] == {"status": "yellow", "detail": "近 24 小时无私聊摄取证据"}
    assert result["group"] == {"status": "yellow", "detail": "近 24 小时无群聊摄取证据"}


def test_disconnected_transport_is_red_even_when_old_messages_exist(tmp_path):
    state_path = tmp_path / "gateway_state.json"
    log_path = tmp_path / "gateway.log"
    adapter_path = tmp_path / "adapter.py"
    _write_state(state_path, {"platforms": {"qqbot": {"state": "disconnected"}}})
    log_path.write_text(
        "2026-08-24 14:08:36,518 INFO gateway.run: inbound message: platform=qqbot "
        "user=member chat=group msg='probe'\n",
        encoding="utf-8",
    )
    adapter_path.write_text(
        '"GROUP_AT_MESSAGE_CREATE"\n"GROUP_MESSAGE_CREATE"\n"GROUP_MESSAGE_CREATE"',
        encoding="utf-8",
    )

    result = assess_qq_health(
        state_path=state_path,
        log_path=log_path,
        adapter_path=adapter_path,
        now=datetime(2026, 8, 24, 14, 10, 0),
        recent_hours=24,
    )

    assert result["status"] == "red"
    assert result["transport"] == {"status": "red", "detail": "QQ WebSocket 未连接"}
    assert result["full_group"] == {
        "status": "yellow",
        "detail": "适配器声明支持普通群消息，但尚无事件级运行证据",
    }


def test_full_group_turns_green_from_explicit_recent_event_evidence(tmp_path):
    state_path = tmp_path / "gateway_state.json"
    log_path = tmp_path / "gateway.log"
    adapter_path = tmp_path / "adapter.py"
    _write_state(state_path, {"platforms": {"qqbot": {"state": "connected"}}})
    log_path.write_text(
        "2026-08-24 14:08:36,518 INFO workbench-view: "
        "workbench qq event received type=GROUP_MESSAGE_CREATE\n",
        encoding="utf-8",
    )
    adapter_path.write_text('"GROUP_MESSAGE_CREATE"', encoding="utf-8")

    result = assess_qq_health(
        state_path=state_path,
        log_path=log_path,
        adapter_path=adapter_path,
        now=datetime(2026, 8, 24, 14, 10, 0),
        recent_hours=24,
    )

    assert result["full_group"] == {
        "status": "green",
        "detail": "最近普通群消息摄取：2026-08-24 14:08:36",
    }


def test_full_group_ignores_expired_and_future_event_evidence(tmp_path):
    state_path = tmp_path / "gateway_state.json"
    log_path = tmp_path / "gateway.log"
    adapter_path = tmp_path / "adapter.py"
    _write_state(state_path, {"platforms": {"qqbot": {"state": "connected"}}})
    log_path.write_text(
        "2026-08-20 14:08:36,518 INFO workbench-view: "
        "workbench qq event received type=GROUP_MESSAGE_CREATE\n"
        "2026-08-24 14:20:00,000 INFO workbench-view: "
        "workbench qq event received type=GROUP_MESSAGE_CREATE\n",
        encoding="utf-8",
    )
    adapter_path.write_text('"GROUP_MESSAGE_CREATE"\n"GROUP_MESSAGE_CREATE"', encoding="utf-8")

    result = assess_qq_health(
        state_path=state_path,
        log_path=log_path,
        adapter_path=adapter_path,
        now=datetime(2026, 8, 24, 14, 10, 0),
        recent_hours=24,
    )

    assert result["full_group"]["status"] == "yellow"
