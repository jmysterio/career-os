"""Runs Claude Code headless for one narrow job: call a single connector tool, or answer from text alone."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


class ClaudeError(RuntimeError):
    pass


def _claude() -> str:
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    if not Path(claude).exists():
        raise ClaudeError("Couldn't find the `claude` command on this computer.")
    return claude


SAVED_DIRS = (Path.home() / ".claude", Path("/tmp/tool-responses").resolve())
SAVED = re.compile(r"saved to:?\s*(\S+\.(?:txt|json))", re.I)
TOO_LARGE = re.compile(r"too large|saved to", re.I)


def _unwrap(text: str) -> str:
    """Saved answers come wrapped as {"result": ...} or {"content": [{"type": "text", "text": ...}]}."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if not isinstance(data, dict) or "markdown_content" in data:
        return text
    if isinstance(data.get("content"), list):
        return "".join(p.get("text", "") for p in data["content"] if isinstance(p, dict))
    return str(data["result"]) if "result" in data else text


def _result_text(content: object) -> str:
    """A tool's answer, whether inline or saved to a file because it was large."""
    raw = content if isinstance(content, str) else "".join(
        part.get("text", "") for part in content if isinstance(part, dict))
    saved = SAVED.search(raw)
    if not saved:
        if len(raw) < 400 and TOO_LARGE.search(raw):
            raise ClaudeError("The answer was too big to read back. Try again.")
        return _unwrap(raw)
    path = Path(saved.group(1)).resolve()
    if not any(path.is_relative_to(d) for d in SAVED_DIRS) or not path.is_file():
        raise ClaudeError("Claude saved the answer somewhere unexpected; stopping.")
    return _unwrap(path.read_text())


def call_tools(prompt: str, tools: list[str], timeout: int = 240, max_turns: int = 5) -> list[tuple[str, dict, str]]:
    """(tool, input, raw answer) for every call Claude made to `tools`, the only tools it may use.
    Claude's own words are discarded."""
    try:
        run = subprocess.run(
            [_claude(), "-p", prompt, "--allowedTools", *tools, "--output-format", "stream-json", "--verbose",
             "--max-turns", str(max_turns)], capture_output=True, text=True, timeout=timeout, cwd=Path.home())
    except subprocess.TimeoutExpired:
        raise ClaudeError("Claude took too long to answer. Try again.") from None
    calls: dict[str, tuple[str, dict]] = {}
    answers: list[tuple[str, dict, str]] = []
    for line in run.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        for part in (msg.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use" and part.get("name") in tools:
                calls[part["id"]] = (part["name"], part.get("input") or {})
            elif part.get("type") == "tool_result" and part.get("tool_use_id") in calls:
                name, args = calls[part["tool_use_id"]]
                answers.append((name, args, _result_text(part.get("content", ""))))
    if not answers:
        raise ClaudeError("Claude didn't get an answer from the connector. Is it signed in for Claude Code?"
                          + (f" ({run.stderr.strip()[:150]})" if run.stderr.strip() else ""))
    return answers


def connector_error(text: str, service: str) -> str | None:
    """A plain explanation when the connector answered with a failure instead of data."""
    head = text[:500]
    if "invalid_token" in head or "status 401" in head or "Needs authentication" in head:
        return (f"Claude Code's {service} sign-in has expired. Open the AI Expert Suite, sign in to {service} "
                "again, then press Sync again.")
    if head.startswith(("MCP tool call failed", "Error")):
        return f"The {service} connector failed: {head[:200]}"
    return None


def call_tool(prompt: str, tool: str, timeout: int = 240) -> str:
    """The raw answer of `tool`, the only tool Claude may use."""
    return call_tools(prompt, [tool], timeout)[-1][2]


def ask(prompt: str, data: str, timeout: int = 240) -> str:
    """Claude's reply to `prompt` about `data` (sent on stdin), with no tools and a single turn."""
    try:
        run = subprocess.run([_claude(), "-p", prompt, "--output-format", "json", "--max-turns", "1"],
                             input=data, capture_output=True, text=True, timeout=timeout, cwd=Path.home())
        out = json.loads(run.stdout)
    except subprocess.TimeoutExpired:
        raise ClaudeError("Claude took too long to answer.") from None
    except ValueError:
        raise ClaudeError("Claude didn't finish." + (f" ({run.stderr.strip()[:150]})" if run.stderr.strip() else "")) \
            from None
    if out.get("is_error") or not out.get("result"):
        raise ClaudeError(f"Claude couldn't answer ({str(out.get('result') or out.get('subtype') or '')[:150]}).")
    return str(out["result"])
