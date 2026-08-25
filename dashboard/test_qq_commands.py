from qq_commands import parse_qq_command


def test_non_command_is_ignored():
    assert parse_qq_command("今天心情不错") is None


def test_read_commands_accept_slash_and_chinese_prefixes():
    assert parse_qq_command("/wb today").name == "today"
    assert parse_qq_command("工作台 状态").name == "health"
    assert parse_qq_command("/wb 帮助").name == "help"


def test_add_command_preserves_argument():
    command = parse_qq_command("/wb 任务 整理 QQ 官方文档")
    assert command.name == "add"
    assert command.argument == "整理 QQ 官方文档"
    assert command.mutating is True


def test_mutations_require_arguments():
    command = parse_qq_command("/wb 完成")
    assert command.name == "invalid"
    assert command.error == "完成命令需要任务标题"


def test_archive_and_defer_are_explicit_mutations():
    archive = parse_qq_command("工作台 归档 修复健康检查")
    defer = parse_qq_command("/wb 延期 修复健康检查 2026-08-30")

    assert (archive.name, archive.argument, archive.mutating) == (
        "archive",
        "修复健康检查",
        True,
    )
    assert (defer.name, defer.argument, defer.extra, defer.mutating) == (
        "defer",
        "修复健康检查",
        "2026-08-30",
        True,
    )


def test_defer_rejects_impossible_calendar_date():
    command = parse_qq_command("/wb 延期 修复健康检查 2026-02-30")

    assert command.name == "invalid"
    assert command.error == "延期命令需要任务标题和 YYYY-MM-DD 日期"


def test_unknown_workbench_command_returns_helpful_error():
    command = parse_qq_command("/wb 删除所有任务")
    assert command.name == "invalid"
    assert command.error == "未知工作台命令；发送 /wb 帮助 查看可用命令"


def test_multiplatform_capture_commands_map_to_explicit_actions():
    review = parse_qq_command("/wb 待回看 https://example.com/video")
    verify = parse_qq_command("工作台 待验证 这个说法是否可靠")
    note = parse_qq_command("/wb 随想 今天重新理解了边界")

    assert (review.name, review.argument, review.mutating) == (
        "review",
        "https://example.com/video",
        True,
    )
    assert (verify.name, verify.argument, verify.mutating) == (
        "verify",
        "这个说法是否可靠",
        True,
    )
    assert (note.name, note.argument, note.mutating) == (
        "note",
        "今天重新理解了边界",
        True,
    )


def test_task_id_commands_preserve_reference_and_content():
    show = parse_qq_command("/wb 查看 WB-A1B2C3D4")
    append = parse_qq_command("/wb 继续 WB-A1B2C3D4 补充微信侧验证结果")
    reopen = parse_qq_command("/wb 重开 WB-A1B2C3D4")

    assert (show.name, show.argument, show.mutating) == ("show", "WB-A1B2C3D4", False)
    assert (append.name, append.argument, append.extra, append.mutating) == (
        "append",
        "WB-A1B2C3D4",
        "补充微信侧验证结果",
        True,
    )
    assert (reopen.name, reopen.argument, reopen.mutating) == (
        "reopen",
        "WB-A1B2C3D4",
        True,
    )


def test_append_requires_task_reference_and_note():
    command = parse_qq_command("/wb 继续 WB-A1B2C3D4")

    assert command.name == "invalid"
    assert command.error == "继续命令需要任务编号和补充内容"
