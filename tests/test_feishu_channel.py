import json

import pytest

from snapagent.bus.events import OutboundMessage
from snapagent.bus.queue import MessageBus
from snapagent.channels.feishu import FeishuChannel
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
