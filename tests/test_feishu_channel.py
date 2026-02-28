"""Feishu channel chunking behavior tests."""

from __future__ import annotations

import pytest

from snapagent.bus.events import OutboundMessage
from snapagent.bus.queue import MessageBus
from snapagent.channels.feishu import FeishuChannel, _split_message
from snapagent.config.schema import FeishuConfig


def _make_channel() -> FeishuChannel:
    channel = FeishuChannel(config=FeishuConfig(), bus=MessageBus())
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
