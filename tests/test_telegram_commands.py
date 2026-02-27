"""Telegram command registration tests."""

from __future__ import annotations


def test_telegram_bot_commands_include_doctor():
    from snapagent.channels.telegram import TelegramChannel

    assert any(cmd.command == "doctor" for cmd in TelegramChannel.BOT_COMMANDS)
