from taskman_mcp import server


def test_read_and_write_annotations_are_explicit() -> None:
    assert server.READ.readOnlyHint is True
    assert server.READ.destructiveHint is False
    assert server.WRITE.readOnlyHint is False
    assert server.WRITE.destructiveHint is False


def test_mcp_does_not_expose_hard_delete() -> None:
    tool_names = set(server.mcp._tool_manager._tools)  # noqa: SLF001 - contract assertion
    assert "archive_task" in tool_names
    assert not any("delete" in name or "remove" in name for name in tool_names)
