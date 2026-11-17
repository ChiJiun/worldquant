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
from typing import Any, Dict, List, Optional, Tuple

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
WRITE_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})
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


def _is_secret_path(relative: str) -> bool:
    """`.env` and anything named like it (backups, swap files), plus `.git/` (remote URLs may hold tokens)."""
    parts = relative.split("/")
    if parts[0] == ".git":
        return True
    name = parts[-1]
    return ".env" in name and name != ".env.example"


def _base_dir(payload: Dict[str, Any], config: GuardConfig) -> str:
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and os.path.isabs(cwd) else config.repo


def check_read(path: Any, config: GuardConfig, base: str) -> Optional[str]:
    if not isinstance(path, str) or not path:
        return "no file path given"
    relative = _relative_to_repo(path, config, base)
    if relative is None:
        return "reads are limited to the repository: %s is outside it" % path
    if _is_secret_path(relative):
        return ".env files and .git/ may hold credentials and must not be read"
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


# Options each subcommand may use, mapped to True when the option takes a value.
# Names must match exactly: argparse also accepts abbreviations (`--lim`) and
# keeps the last of repeated options, so anything looser could be bent into a
# different command than the one checked here. Options left out on purpose:
# simulate --input/--expression/--family/--candidate-id/--allow-mock and
# fetch-correlations --allow-mock.
SUBCOMMAND_OPTIONS = {
    "settings": {},
    "login-check": {},
    "init-research": {},
    "research": {"--mode": True},
    "simulate": {
        "--limit": True,
        "--current-run": False,
        "--instrument-type": True,
        "--region": True,
        "--universe": True,
        "--language": True,
        "--decay": True,
        "--delay": True,
        "--truncation": True,
        "--neutralization": True,
        "--pasteurization": True,
        "--lookback": True,
        "--max-trade": True,
        "--max-position": True,
    },
    "result": {},
    "attribute": {"--candidate-id": True, "--result-id": True},
    "validate-candidate": {"--candidate-id": True, "--result-id": True, "--write-artifact": False, "--refresh": False},
    "fetch-correlations": {"--alpha-id": True, "--kind": True, "--refresh": False, "--limit": True},
    "select-alphas": {"--finalize-run": False, "--clear-candidates": False},
}
# Options argparse collects into a list, so repeating them is meaningful.
REPEATABLE_OPTIONS = frozenset({("fetch-correlations", "--alpha-id")})
# Positional arguments each subcommand takes.
SUBCOMMAND_POSITIONALS = {"result": 1}
# Option values and positionals: ids, numbers and enum words. No path
# separators, so nothing can point the CLI at another file or URL path.
SAFE_VALUE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.,:+-]*")


def _parse_options(subcommand: str, tokens: List[str]) -> Tuple[Optional[str], Dict[str, str]]:
    """Check `tokens` against SUBCOMMAND_OPTIONS; return (reason, {option: value})."""
    known = SUBCOMMAND_OPTIONS[subcommand]
    values: Dict[str, str] = {}
    positionals: List[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token.startswith("-"):
            positionals.append(token)
            continue
        name, has_inline, inline = token.partition("=")
        if name not in known:
            return "option %r is not available for %s in an unattended round" % (name, subcommand), {}
        if name in values and (subcommand, name) not in REPEATABLE_OPTIONS:
            return "option %s may be given only once" % name, {}
        if known[name]:
            if has_inline:
                value = inline
            elif index < len(tokens) and not tokens[index].startswith("-"):
                value = tokens[index]
                index += 1
            else:
                return "option %s needs a value" % name, {}
            if SAFE_VALUE.fullmatch(value) is None or ".." in value:
                return "the value of %s must be a plain id, number or word" % name, {}
            values[name] = value
        else:
            if has_inline:
                return "option %s takes no value" % name, {}
            values[name] = ""
    expected = SUBCOMMAND_POSITIONALS.get(subcommand, 0)
    if len(positionals) != expected:
        return "%s takes %d positional argument(s), got %d" % (subcommand, expected, len(positionals)), {}
    for value in positionals:
        if SAFE_VALUE.fullmatch(value) is None or ".." in value:
            return "arguments must be plain ids, numbers or words", {}
    return None, values


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
    reason, values = _parse_options(subcommand, options)
    if reason:
        return reason
    if subcommand == "simulate":
        return _check_simulate(values, config)
    return None


def _check_simulate(values: Dict[str, str], config: GuardConfig) -> Optional[str]:
    if values.get("--limit") != "1":
        return "an unattended round simulates one candidate from data/candidates.jsonl: pass `--limit 1`"
    marker = config.simulate_marker
    if marker:
        # O_EXCL makes "first simulate of the round" atomic even if two hooks run at once.
        try:
            handle = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return "this round already ran its one simulate; finish the round with the result you have"
        os.write(handle, b"simulate allowed\n")
        os.close(handle)
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
        return check_write(tool_input.get("file_path"), config, base)
    if tool == "Grep":
        return check_grep(tool_input, config, base)
    if tool == "Glob":
        return check_glob(tool_input, config, base)
    if tool == "Skill":
        if tool_input.get("skill") == SKILL_NAME:
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
