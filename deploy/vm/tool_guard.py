#!/usr/bin/env python3
"""PreToolUse hook for unattended research rounds (see deploy/vm/README.md).

Claude Code runs this before every tool call and passes the call as JSON on
stdin. Exit code 0 lets the call go on to the normal permission rules; exit
code 2 blocks it and shows stderr to the model. This file is the enforcement
layer: permission rules alone still let read-only shell commands such as
`cat .env` through, and a hook that crashes with another exit code does not
block anything. So everything not explicitly recognised here is blocked, and
every internal error is turned into a block as well.

Configuration comes from the environment the runner exports:

- WQ_GUARD_REPO: absolute path of the repository root
- WQ_GUARD_PYTHON: the interpreter string the agent must type, e.g. .venv/bin/python
- WQ_GUARD_SIMULATE_MARKER: file created when this round's one simulate is let through
- WQ_GUARD_LOG: file that gets one line per decision; the runner reads it to
  prove the hook really ran
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SKILL_NAME = "worldquant-researcher-workflow"

# Subcommands an unattended round may run. `record-passed-alpha` is left out on
# purpose: it writes a row with hand-supplied metrics into the pool the submit
# queue is built from. `init-data` is setup, not research.
ALLOWED_SUBCOMMANDS = frozenset(
    {
        "settings",
        "login-check",
        "research",
        "init-research",
        "simulate",
        "result",
        "attribute",
        "validate-candidate",
        "fetch-correlations",
        "select-alphas",
    }
)

# Whole-command whitelist: no quotes, no shell operators, no expansion, no
# newlines. With nothing to interpret, bash and this file split the command the
# same way, on spaces.
SAFE_COMMAND = re.compile(r"[A-Za-z0-9_.,:=@%+/ -]+")

READ_TOOLS = frozenset({"Read"})
WRITE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
# Bookkeeping tools that touch nothing outside the session.
HARMLESS_TOOLS = frozenset({"TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"})


class GuardConfig:
    def __init__(self, repo: str, python: str, simulate_marker: str = "") -> None:
        self.repo = os.path.realpath(repo)
        self.python = python
        self.simulate_marker = simulate_marker


def config_from_env(environ: Dict[str, str]) -> GuardConfig:
    repo = environ.get("WQ_GUARD_REPO", "")
    python = environ.get("WQ_GUARD_PYTHON", "")
    if not repo or not os.path.isabs(repo) or not python:
        raise ValueError("WQ_GUARD_REPO (absolute) and WQ_GUARD_PYTHON must be set")
    return GuardConfig(repo, python, environ.get("WQ_GUARD_SIMULATE_MARKER", ""))


def _resolve(path: str, base: str) -> str:
    return os.path.realpath(os.path.join(base, os.path.expanduser(path)))


def _relative_to_repo(path: str, config: GuardConfig, base: str) -> Optional[str]:
    """Repo-relative POSIX path of `path`, or None when it resolves outside the repo."""
    resolved = _resolve(path, base)
    try:
        relative = os.path.relpath(resolved, config.repo)
    except ValueError:  # different drive on Windows
        return None
    if relative == os.pardir or relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
        return None
    return relative.replace(os.sep, "/")


def _is_env_file(relative: str) -> bool:
    name = relative.rsplit("/", 1)[-1]
    return name == ".env" or (name.startswith(".env.") and name != ".env.example")


def _base_dir(payload: Dict[str, Any], config: GuardConfig) -> str:
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and os.path.isabs(cwd) else config.repo


def check_read(path: Any, config: GuardConfig, base: str) -> Optional[str]:
    if not isinstance(path, str) or not path:
        return "no file path given"
    relative = _relative_to_repo(path, config, base)
    if relative is None:
        return "reads are limited to the repository: %s is outside it" % path
    if _is_env_file(relative):
        return ".env holds credentials and must not be read"
    return None


def check_write(path: Any, config: GuardConfig, base: str) -> Optional[str]:
    if not isinstance(path, str) or not path:
        return "no file path given"
    relative = _relative_to_repo(path, config, base)
    if relative == "data/candidates.jsonl":
        return None
    if relative is not None and relative.startswith("research/notes/") and relative.endswith(".md"):
        return None
    return "the only writable files are data/candidates.jsonl and research/notes/**/*.md"


def check_grep(tool_input: Dict[str, Any], config: GuardConfig, base: str) -> Optional[str]:
    """Grep prints file contents, so it may not sweep the directory that holds .env."""
    path = tool_input.get("path")
    if not isinstance(path, str) or not path:
        return "give Grep a `path` below the repository root, for example research/ or outputs/"
    reason = check_read(path, config, base)
    if reason:
        return reason
    if _relative_to_repo(path, config, base) == ".":
        return "Grep may not search the repository root (it holds .env); pass a subdirectory or a file"
    glob = tool_input.get("glob")
    if isinstance(glob, str) and _glob_escapes(glob):
        return "search patterns must stay inside the repository"
    return None


def check_glob(tool_input: Dict[str, Any], config: GuardConfig, base: str) -> Optional[str]:
    """Glob only lists names; keep it inside the repository."""
    path = tool_input.get("path")
    if path not in (None, ""):
        if not isinstance(path, str) or _relative_to_repo(path, config, base) is None:
            return "Glob is limited to the repository"
    pattern = tool_input.get("pattern")
    if not isinstance(pattern, str) or _glob_escapes(pattern):
        return "search patterns must stay inside the repository"
    return None


def _glob_escapes(pattern: str) -> bool:
    normalized = pattern.replace("\\", "/")
    return normalized.startswith(("/", "~")) or ".." in normalized.split("/") or re.match(r"[A-Za-z]:", normalized) is not None


def _option_value(tokens: List[str], name: str) -> Optional[str]:
    for index, token in enumerate(tokens):
        if token == name:
            return tokens[index + 1] if index + 1 < len(tokens) else ""
        if token.startswith(name + "="):
            return token[len(name) + 1 :]
    return None


def _has_option(tokens: List[str], name: str) -> bool:
    return any(token == name or token.startswith(name + "=") for token in tokens)


def check_bash(command: Any, config: GuardConfig, cwd: Optional[str]) -> Optional[str]:
    usage = "the only shell command allowed is `%s -m app <subcommand> ...` on one line" % config.python
    if not isinstance(command, str) or not command.strip():
        return usage
    if SAFE_COMMAND.fullmatch(command) is None:
        return usage + " without quotes, pipes, redirection, variables or other shell syntax"
    if cwd is not None and os.path.realpath(cwd) != config.repo:
        return "run the CLI from the repository root, not from %s" % cwd
    tokens = command.split()
    if len(tokens) < 4 or tokens[0] != config.python or tokens[1:3] != ["-m", "app"]:
        return usage
    subcommand, options = tokens[3], tokens[4:]
    if subcommand not in ALLOWED_SUBCOMMANDS:
        return "subcommand %r is not available to an unattended round (allowed: %s)" % (
            subcommand,
            ", ".join(sorted(ALLOWED_SUBCOMMANDS)),
        )
    if subcommand == "simulate":
        return _check_simulate(options, config)
    return None


def _check_simulate(options: List[str], config: GuardConfig) -> Optional[str]:
    for banned in ("--allow-mock", "--expression", "--input"):
        if _has_option(options, banned):
            return "simulate may not use %s in an unattended round; write data/candidates.jsonl instead" % banned
    if _option_value(options, "--limit") != "1":
        return "an unattended round simulates one candidate: pass `--limit 1`"
    marker = config.simulate_marker
    if marker:
        if os.path.exists(marker):
            return "this round already ran its one simulate; finish the round with the result you have"
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("simulate allowed\n")
    return None


def decide(payload: Any, config: GuardConfig) -> Optional[str]:
    """Return None to let the tool call through, or the reason it is blocked."""
    if not isinstance(payload, dict):
        return "malformed hook input"
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return "malformed hook input"
    base = _base_dir(payload, config)

    if tool == "Bash":
        cwd = payload.get("cwd")
        return check_bash(tool_input.get("command"), config, cwd if isinstance(cwd, str) else None)
    if tool in READ_TOOLS:
        return check_read(tool_input.get("file_path"), config, base)
    if tool in WRITE_TOOLS:
        return check_write(tool_input.get("file_path") or tool_input.get("notebook_path"), config, base)
    if tool == "Grep":
        return check_grep(tool_input, config, base)
    if tool == "Glob":
        return check_glob(tool_input, config, base)
    if tool == "Skill":
        name = str(tool_input.get("skill", ""))
        if name.rsplit(":", 1)[-1] == SKILL_NAME:
            return None
        return "only the %s skill may be loaded" % SKILL_NAME
    if tool in HARMLESS_TOOLS:
        return None
    return "tool %s is not available to an unattended round" % tool


def _log_decision(path: str, tool: str, reason: Optional[str]) -> None:
    if not path:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = "%s %s %s" % (stamp, "allow" if reason is None else "deny", tool)
    if reason is not None:
        line += " | " + reason.replace("\n", " ")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main() -> int:
    tool = "?"
    try:
        config = config_from_env(dict(os.environ))
        payload = json.loads(sys.stdin.read())
        if isinstance(payload, dict) and isinstance(payload.get("tool_name"), str):
            tool = payload["tool_name"]
        reason = decide(payload, config)
    except Exception as exc:  # fail closed: an error must never let a call through
        reason = "tool guard error (%s: %s)" % (type(exc).__name__, exc)
    try:
        _log_decision(os.environ.get("WQ_GUARD_LOG", ""), tool, reason)
    except OSError:
        pass  # a missing log makes the runner stop the loop; the decision still stands
    if reason is None:
        return 0
    sys.stderr.write("Blocked by deploy/vm/tool_guard.py: %s\n" % reason)
    return 2


if __name__ == "__main__":
    sys.exit(main())
