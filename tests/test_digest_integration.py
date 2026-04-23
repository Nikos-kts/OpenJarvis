"""End-to-end integration test for the morning digest pipeline.

Uses mocked connectors and engine to verify the full flow:
digest_collect -> LLM synthesis -> DigestStore -> CLI delivery.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openjarvis.agents.digest_store import DigestStore
from openjarvis.core.types import ToolResult


def test_full_digest_pipeline(tmp_path):
    """Verify collect -> synthesize -> store -> retrieve."""
    from openjarvis.agents.morning_digest import MorningDigestAgent

    # Mock engine returns a narrative
    mock_engine = MagicMock()
    mock_engine.generate.return_value = {
        "content": (
            "Good morning, sir. You slept 7.5 hours with a readiness score of 78. "
            "You have 2 meetings today and 5 unread emails. "
            "In the news, a new GPT-5 paper dropped on Arxiv."
        ),
        "finish_reason": "stop",
        "usage": {},
    }

    # Mock tool results
    collect_result = ToolResult(
        tool_name="digest_collect",
        content=(
            "=== HEALTH ===\n[oura] Sleep — April 1: score 78, avg HR 58 bpm\n\n"
            '=== MESSAGES ===\n[gmail] From: alice@co.com — "Q3 Review" (2h ago)\n\n'
            "=== CALENDAR ===\n[gcalendar] 10:30 AM — Team Standup (30 min)\n"
        ),
        success=True,
        metadata={"total_items": 6},
    )

    db_path = str(tmp_path / "digest.db")

    agent = MorningDigestAgent(
        mock_engine,
        "claude-sonnet-4-6",
        tools=[],
        persona="neutral",
        digest_store_path=db_path,
    )

    with patch.object(
        agent._executor,
        "execute",
        side_effect=[collect_result],
    ):
        result = agent.run("Generate morning digest")

    # Verify agent result
    assert "Good morning" in result.content

    # Verify stored in DigestStore
    store = DigestStore(db_path=db_path)
    artifact = store.get_latest()
    assert artifact is not None
    assert "Good morning" in artifact.text
    assert artifact.model_used == "claude-sonnet-4-6"
    store.close()
