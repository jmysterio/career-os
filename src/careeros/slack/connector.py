"""Reads one Slack canvas through the Slack connector by running Claude Code headless (read_canvas only)."""
from __future__ import annotations

from ..claude_cli import ClaudeError, call_tool, connector_error

TOOL = "mcp__plugin_slack_slack__slack_read_canvas"


def fetch_canvas(canvas_id: str) -> str:
    """The canvas as returned by the connector (JSON with markdown_content), never Claude's own words."""
    raw = call_tool(f"Call the slack_read_canvas tool exactly once with canvas_id={canvas_id}. "
                    "When it returns, reply with only DONE.", TOOL)
    if err := connector_error(raw, "Slack"):
        raise ClaudeError(err)
    return raw
