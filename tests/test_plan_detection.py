"""Tests for plan block detection in ConversationOrchestrator."""

from __future__ import annotations

from snapagent.orchestrator.conversation import ConversationOrchestrator


def test_extract_plan_finds_block():
    text = (
        "Let me plan this.\n\n"
        "**Plan:**\n"
        "1. [ ] Search for AI frameworks\n"
        "2. [ ] Fetch top results\n"
        "3. [ ] Synthesize comparison\n"
    )
    plan = ConversationOrchestrator._extract_plan(text)
    assert plan is not None
    assert "1. [ ] Search for AI frameworks" in plan
    assert "3. [ ] Synthesize comparison" in plan


def test_extract_plan_none_for_normal_text():
    assert ConversationOrchestrator._extract_plan("Just a normal response.") is None


def test_extract_plan_none_for_empty():
    assert ConversationOrchestrator._extract_plan(None) is None
    assert ConversationOrchestrator._extract_plan("") is None


def test_extract_plan_with_checked_items():
    text = (
        "**Plan:**\n"
        "1. [x] Already searched\n"
        "2. [ ] Fetch page content\n"
    )
    plan = ConversationOrchestrator._extract_plan(text)
    assert plan is not None
    assert "[x] Already searched" in plan
