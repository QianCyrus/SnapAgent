"""Feishu channel send/chunk behavior tests."""

from __future__ import annotations

import json

import pytest

from snapagent.bus.events import OutboundMessage
from snapagent.bus.queue import MessageBus
from snapagent.channels.feishu import FeishuChannel, _split_message
from snapagent.config.schema import FeishuConfig


def _make_channel(*, workspace=None) -> FeishuChannel:
    channel = FeishuChannel(
        FeishuConfig(enabled=True, app_id="app_id", app_secret="app_secret"),
        MessageBus(),
        workspace=workspace,
    )
    # Skip SDK initialization path and focus on send() logic.
    channel._client = object()
    return channel


def test_split_message_force_splits_when_no_separator():
    content = "x" * 23
    chunks = _split_message(content, max_len=8)
    assert chunks == ["x" * 8, "x" * 8, "x" * 7]


def test_split_message_preserves_whitespace_and_newlines():
    content = "line1\n\nline2 with space \nline3"
    chunks = _split_message(content, max_len=10)
    assert "".join(chunks) == content


def test_split_message_rejects_non_positive_max_len():
    with pytest.raises(ValueError):
        _split_message("abc", max_len=0)


@pytest.mark.asyncio
async def test_feishu_send_splits_long_content_into_multiple_cards():
    channel = _make_channel()
    calls: list[dict] = []

    def _fake_send(_receive_id_type: str, _receive_id: str, msg_type: str, content: str) -> bool:
        calls.append({"msg_type": msg_type, "content": content})
        return True

    channel._send_message_sync = _fake_send  # type: ignore[method-assign]
    long_content = "a" * 9000
    await channel.send(OutboundMessage(channel="feishu", chat_id="ou_test", content=long_content))

    chunks = _split_message(long_content)
    assert len(calls) == len(chunks)
    assert all(c["msg_type"] == "interactive" for c in calls)
    assert all(len(chunk) <= 2000 for chunk in chunks)
    for i, call in enumerate(calls):
        payload = json.loads(call["content"])
        assert payload["elements"] == [{"tag": "markdown", "content": chunks[i]}]


@pytest.mark.asyncio
async def test_send_resolves_relative_media_path_from_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    media_file = workspace / "reports" / "incident.pdf"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_bytes(b"pdf-content")

    channel = _make_channel(workspace=workspace)
    uploaded_paths: list[str] = []
    sent_calls: list[tuple[str, str]] = []

    def _upload_file_sync(path: str) -> str | None:
        uploaded_paths.append(path)
        return "file_key_123"

    def _send_message_sync(
        _receive_id_type: str, _receive_id: str, msg_type: str, content: str
    ) -> bool:
        sent_calls.append((msg_type, content))
        return True

    channel._upload_file_sync = _upload_file_sync
    channel._send_message_sync = _send_message_sync

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_test_chat_id",
            content="body",
            media=["reports/incident.pdf"],
        )
    )

    assert uploaded_paths == [str(media_file.resolve())]
    assert [msg_type for msg_type, _ in sent_calls] == ["file", "interactive"]
    assert json.loads(sent_calls[0][1]) == {"file_key": "file_key_123"}


@pytest.mark.asyncio
async def test_send_skips_missing_media_and_still_sends_text(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    channel = _make_channel(workspace=workspace)
    sent_calls: list[tuple[str, str]] = []

    def _upload_file_sync(path: str) -> str | None:
        raise AssertionError(f"upload should not be called for missing file: {path}")

    def _send_message_sync(
        _receive_id_type: str, _receive_id: str, msg_type: str, content: str
    ) -> bool:
        sent_calls.append((msg_type, content))
        return True

    channel._upload_file_sync = _upload_file_sync
    channel._send_message_sync = _send_message_sync

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_test_chat_id",
            content="body",
            media=["reports/missing.pdf"],
        )
    )

    assert len(sent_calls) == 1
    assert sent_calls[0][0] == "interactive"


@pytest.mark.asyncio
async def test_send_resolves_relative_media_path_from_cwd_fallback(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    cwd_dir = tmp_path / "cwd"
    media_file = cwd_dir / "reports" / "fallback.pdf"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_bytes(b"pdf-content")
    monkeypatch.chdir(cwd_dir)

    channel = _make_channel(workspace=workspace)
    uploaded_paths: list[str] = []
    sent_calls: list[tuple[str, str]] = []

    def _upload_file_sync(path: str) -> str | None:
        uploaded_paths.append(path)
        return "file_key_fallback"

    def _send_message_sync(
        _receive_id_type: str, _receive_id: str, msg_type: str, content: str
    ) -> bool:
        sent_calls.append((msg_type, content))
        return True

    channel._upload_file_sync = _upload_file_sync
    channel._send_message_sync = _send_message_sync

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_test_chat_id",
            content="body",
            media=["reports/fallback.pdf"],
        )
    )

    assert uploaded_paths == [str(media_file.resolve())]
    assert [msg_type for msg_type, _ in sent_calls] == ["file", "interactive"]
    assert json.loads(sent_calls[0][1]) == {"file_key": "file_key_fallback"}


@pytest.mark.asyncio
async def test_send_supports_absolute_media_path(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    media_file = tmp_path / "absolute" / "doc.pdf"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_bytes(b"pdf-content")

    channel = _make_channel(workspace=workspace)
    uploaded_paths: list[str] = []
    sent_calls: list[tuple[str, str]] = []

    def _upload_file_sync(path: str) -> str | None:
        uploaded_paths.append(path)
        return "file_key_absolute"

    def _send_message_sync(
        _receive_id_type: str, _receive_id: str, msg_type: str, content: str
    ) -> bool:
        sent_calls.append((msg_type, content))
        return True

    channel._upload_file_sync = _upload_file_sync
    channel._send_message_sync = _send_message_sync

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_test_chat_id",
            content="body",
            media=[str(media_file)],
        )
    )

    assert uploaded_paths == [str(media_file.resolve())]
    assert [msg_type for msg_type, _ in sent_calls] == ["file", "interactive"]
    assert json.loads(sent_calls[0][1]) == {"file_key": "file_key_absolute"}
