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


def _result_text(content: object) -> str:
    """A tool's answer, whether inline or saved to a file under ~/.claude because it was large."""
    raw = content if isinstance(content, str) else "".join(
        part.get("text", "") for part in content if isinstance(part, dict))
    saved = re.search(r"saved to (\S+\.(?:txt|json))", raw)
    if not saved:
        return raw
    path = Path(saved.group(1))
    if ".claude" not in path.parts or not path.is_file():
        raise ClaudeError("Claude saved the answer somewhere unexpected; stopping.")
    text = path.read_text()
    try:
        data = json.loads(text)
    except ValueError:
        return text
    return data.get("result", text) if isinstance(data, dict) and "markdown_content" not in data else text


def call_tool(prompt: str, tool: str, timeout: int = 240) -> str:
    """The raw answer of `tool`, the only tool Claude may use. Claude's own words are discarded."""
    try:
        run = subprocess.run(
            [_claude(), "-p", prompt, "--allowedTools", tool, "--output-format", "stream-json", "--verbose",
             "--max-turns", "5"], capture_output=True, text=True, timeout=timeout, cwd=Path.home())
    except subprocess.TimeoutExpired:
        raise ClaudeError("Claude took too long to answer. Try again.") from None
    wanted: set[str] = set()
    answer: str | None = None
    for line in run.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        for part in (msg.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use" and part.get("name") == tool:
                wanted.add(part["id"])
            elif part.get("type") == "tool_result" and part.get("tool_use_id") in wanted:
                answer = _result_text(part.get("content", ""))
    if answer is None:
        raise ClaudeError("Claude didn't get an answer from the connector."
                          + (f" ({run.stderr.strip()[:150]})" if run.stderr.strip() else ""))
    return answer


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
