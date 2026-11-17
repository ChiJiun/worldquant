"""Tests for deploy/vm/tool_guard.py, the PreToolUse hook of the unattended runner.

Pure decision logic plus the hook's command-line contract (exit 0 = let the
call continue, exit 2 = block). Nothing here starts Claude or touches BRAIN.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = REPO_ROOT / "deploy" / "vm" / "tool_guard.py"
PY = ".venv/bin/python"

_spec = importlib.util.spec_from_file_location("wq_tool_guard", GUARD_PATH)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "research" / "notes").mkdir(parents=True)
    (root / "research" / "state").mkdir(parents=True)
    (root / ".env").write_text("WQ_PASSWORD=placeholder\n", encoding="utf-8")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    return root


@pytest.fixture()
def config(repo: Path):
    return guard.GuardConfig(str(repo), PY, str(repo.parent / "simulate.marker"))


def _decide(config, repo: Path, tool: str, tool_input: dict, cwd: str | None = None):
    return guard.decide({"tool_name": tool, "tool_input": tool_input, "cwd": cwd or str(repo)}, config)


@pytest.mark.parametrize(
    "command",
    [
        f"{PY} -m app settings",
        f"{PY} -m app research --mode auto",
        f"{PY} -m app attribute --candidate-id A_settings_001 --result-id abc123",
        f"{PY} -m app validate-candidate --candidate-id A.1 --refresh",
        f"{PY} -m app fetch-correlations --refresh --limit 20",
        f"{PY} -m app fetch-correlations --kind both --limit=1",
        f"{PY} -m app select-alphas --finalize-run --clear-candidates",
        f"{PY} -m app result abc123",
        f"{PY} -m app login-check",
        f"{PY} -m app init-research",
    ],
)
def test_bash_lets_the_research_cli_through(config, repo: Path, command: str) -> None:
    assert _decide(config, repo, "Bash", {"command": command}) is None


@pytest.mark.parametrize(
    "command",
    [
        "cat .env",
        "ls",
        "cd research/notes",
        "echo wq-guard-probe",
        "grep -r WQ_PASSWORD .",
        f"{PY} -m app settings && cat .env",
        f"{PY} -m app settings; cat .env",
        f"{PY} -m app settings | tee out.txt",
        f"{PY} -m app settings > out.txt",
        f"{PY} -m app result $(cat .env)",
        f"{PY} -m app result `cat .env`",
        f'{PY} -m app result "abc"',
        f"{PY} -m app result 'abc'",
        f"{PY} -m app settings\ncat .env",
        f"cd research/notes && {PY} -m app settings",
        f"WQ_DRY_RUN=true {PY} -m app settings",
        "python -m app settings",
        "/usr/bin/python3 -m app settings",
        f"{PY} -c pass",
        f"{PY} -m pip install requests",
        f"{PY} -m app",
        f"{PY} -m app record-passed-alpha --candidate-id X",
        f"{PY} -m app init-data",
        f"{PY} -m app --help",
        "",
        "   ",
    ],
)
def test_bash_blocks_everything_else(config, repo: Path, command: str) -> None:
    assert _decide(config, repo, "Bash", {"command": command}) is not None


def test_bash_must_run_from_the_repository_root(config, repo: Path) -> None:
    elsewhere = str(repo / "research" / "notes")
    reason = _decide(config, repo, "Bash", {"command": f"{PY} -m app settings"}, cwd=elsewhere)
    assert reason is not None and "repository root" in reason


@pytest.mark.parametrize(
    "command",
    [
        # `;` and `&` as separate words: the guard must not rely on them sticking to the subcommand.
        f"{PY} -m pip settings",
        f"{PY} -c help settings",
        # Only SAFE_COMMAND rejects this one: str.split() would accept the tab.
        f"{PY} -m app research --mode\tauto",
        f"{PY} -m app settings ; cat .env",
        f"{PY} -m app settings & id",
        f"{PY} -m app settings\tx",
        f"{PY} -m app result *",
        f"{PY} -m app settings extra",
        f"{PY} -m app settings --help",
        f"{PY} -m app research -h",
        f"{PY} -m app research --mode",
        f"{PY} -m app research --mode auto --mode pass-alpha-search",
        f"{PY} -m app research --mod auto",
        f"{PY} -m app result",
        f"{PY} -m app result a b",
        f"{PY} -m app result ../users/self",
        f"{PY} -m app result users/self",
        f"{PY} -m app attribute --result-id ../x",
        f"{PY} -m app select-alphas --finalize-run=yes",
        f"{PY} -m app fetch-correlations --allow-mock",
        f"{PY} -m app fetch-correlations --allow",
        f"{PY} -m app validate-candidate -- --refresh",
    ],
)
def test_bash_checks_every_option_and_argument(config, repo: Path, command: str) -> None:
    assert _decide(config, repo, "Bash", {"command": command}) is not None


@pytest.mark.parametrize(
    "options",
    [
        "",
        "--refresh",
        "--alpha-id abc",
        "--limit 0",
        "--limit 21",
        "--limit 500",
        "--limit +5",
        "--limit 1.5",
        "--limit five",
        "--limit=",
    ],
)
def test_fetch_correlations_needs_a_small_limit(config, repo: Path, options: str) -> None:
    command = f"{PY} -m app fetch-correlations {options}".strip()
    assert _decide(config, repo, "Bash", {"command": command}) is not None


def test_fetch_correlations_limit_bound_is_twenty() -> None:
    assert guard.FETCH_CORRELATIONS_MAX_LIMIT == 20


# Characters a shell would interpret. SAFE_COMMAND is the first of two layers
# (_parse_options re-checks every word), so test it on its own: a command that
# only differs from an allowed one by such a character must not match.
SHELL_CHARACTERS = list(";&|<>$`'\"\\(){}[]*?~!#^") + ["\t", "\n", "\r", "\x00", "\u00a0"]


@pytest.mark.parametrize("char", SHELL_CHARACTERS)
def test_safe_command_rejects_shell_characters(char: str) -> None:
    assert guard.SAFE_COMMAND.fullmatch(f"{PY} -m app result abc") is not None
    assert guard.SAFE_COMMAND.fullmatch(f"{PY} -m app result a{char}b") is None


def test_safe_command_accepts_exactly_its_documented_characters() -> None:
    allowed = "ABCXYZabcxyz0123456789_.,:=@%+/ -"
    assert guard.SAFE_COMMAND.fullmatch(allowed) is not None
    for code in range(32, 127):
        char = chr(code)
        expected = char in allowed or char.isalnum()
        assert (guard.SAFE_COMMAND.fullmatch(char) is not None) == expected, repr(char)


def test_repeatable_option_is_the_only_one_that_may_repeat(config, repo: Path) -> None:
    command = f"{PY} -m app fetch-correlations --alpha-id abc --alpha-id def --limit 5"
    assert _decide(config, repo, "Bash", {"command": command}) is None
    repeated = f"{PY} -m app fetch-correlations --limit 5 --limit 500"
    assert _decide(config, repo, "Bash", {"command": repeated}) is not None


def test_option_table_covers_exactly_the_allowed_subcommands() -> None:
    assert set(guard.SUBCOMMAND_OPTIONS) == set(guard.ALLOWED_SUBCOMMANDS)


@pytest.mark.parametrize(
    "options",
    [
        "",
        "--current-run",
        "--limit 5",
        "--limit",
        "--limit 1 --allow-mock",
        "--limit 1 --input other.jsonl",
        "--limit 1 --expression rank",
        # argparse keeps the last of repeated options and accepts abbreviations.
        "--limit 1 --limit 50",
        "--limit 1 --lim 50",
        "--limit=1 --li=99",
        "--limit 1 --inp research/notes/batch.md",
        "--limit 1 --expr close",
        "--limit 1 --allow-m",
        "--limit 1 --family x",
        "--limit 1 --candidate-id x",
        "--limit 1 --current-run=1",
        "--limit 1 extra",
        "--limit=1 --decay -1",
    ],
)
def test_simulate_needs_limit_one_and_no_escape_hatches(config, repo: Path, options: str) -> None:
    command = f"{PY} -m app simulate {options}".strip()
    assert _decide(config, repo, "Bash", {"command": command}) is not None
    assert not Path(config.simulate_marker).exists()


@pytest.mark.parametrize("limit", ["--limit 1", "--limit=1"])
def test_simulate_is_let_through_once_per_round(config, repo: Path, limit: str) -> None:
    command = f"{PY} -m app simulate {limit} --current-run --decay 4"

    assert _decide(config, repo, "Bash", {"command": command}) is None
    assert Path(config.simulate_marker).exists()

    second = _decide(config, repo, "Bash", {"command": command})
    assert second is not None and "already ran" in second


@pytest.mark.parametrize("path", ["README.md", "research/state/family_memory.json", ".env.example", "data/candidates.jsonl"])
def test_read_inside_the_repository_is_allowed(config, repo: Path, path: str) -> None:
    assert _decide(config, repo, "Read", {"file_path": path}) is None
    assert _decide(config, repo, "Read", {"file_path": str(repo / path)}) is None


@pytest.mark.parametrize(
    "path",
    [".env", "./.env", "research/.env", ".env.local", ".env.production", ".env~", "..env.swp", ".env.bak", "backup.env", ".git/config", ".git"],
)
def test_read_never_reaches_an_env_file_or_git(config, repo: Path, path: str) -> None:
    reason = _decide(config, repo, "Read", {"file_path": path})
    assert reason is not None and ".env" in reason


@pytest.mark.parametrize("path", ["../outside.txt", "research/../../outside.txt", "~/.ssh/id_ed25519", "~/.config/wq-runner/env"])
def test_read_outside_the_repository_is_blocked(config, repo: Path, path: str) -> None:
    assert _decide(config, repo, "Read", {"file_path": path}) is not None


def test_read_blocks_an_absolute_path_outside_the_repository(config, repo: Path) -> None:
    outside = repo.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    assert _decide(config, repo, "Read", {"file_path": str(outside)}) is not None
    assert _decide(config, repo, "Read", {}) is not None


def test_read_follows_symlinks_out_of_the_repository(config, repo: Path) -> None:
    # Creating a symlink usually needs extra privileges on Windows, so this test
    # skips there; test_paths_are_resolved_with_realpath covers the same rule on
    # every platform without a real link.
    secret = repo.parent / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    link = repo / "research" / "notes" / "link.md"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    assert _decide(config, repo, "Read", {"file_path": "research/notes/link.md"}) is not None
    assert _decide(config, repo, "Write", {"file_path": "research/notes/link.md"}) is not None


def test_paths_are_resolved_with_realpath(config, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must follow links (realpath), not just tidy the path (normpath)."""
    outside = str(repo.parent / "secret.txt")
    link = os.path.normcase(os.path.join(str(repo), "research", "notes", "link.md"))
    real_realpath = os.path.realpath

    def fake_realpath(path, *args, **kwargs):
        if os.path.normcase(os.path.normpath(path)) == link:
            return outside
        return real_realpath(path, *args, **kwargs)

    monkeypatch.setattr(guard.os.path, "realpath", fake_realpath)
    assert _decide(config, repo, "Read", {"file_path": "research/notes/link.md"}) is not None
    assert _decide(config, repo, "Write", {"file_path": "research/notes/link.md"}) is not None
    assert _decide(config, repo, "Write", {"file_path": "research/notes/other.md"}) is None


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
@pytest.mark.parametrize("path", ["data/candidates.jsonl", "research/notes/idea.md", "research/notes/hypotheses.md", "research/notes/round_2026-11-17.md"])
def test_write_is_limited_to_the_candidate_file_and_markdown_notes(config, repo: Path, tool: str, path: str) -> None:
    assert _decide(config, repo, tool, {"file_path": path}) is None


@pytest.mark.parametrize(
    "path",
    [
        # Claude Code loads these as instructions without a tool call.
        "research/notes/CLAUDE.md",
        "research/notes/claude.md",
        "research/notes/CLAUDE.local.md",
        "research/notes/AGENTS.md",
        "research/notes/SKILL.md",
        "research/notes/sub/CLAUDE.local.md",
        "research/notes/.claude/skills/x/SKILL.md",
        "research/notes/.claude/rules/r.md",
        "research/notes/.hidden.md",
        "research/notes/2026/idea.md",
        # Subdirectories whose own name looks like a valid note.
        "research/notes/a.md/CLAUDE.md",
        "research/notes/a.md/b.md",
        "research/notes/x.md/.claude/rules/r.md",
        "research/notes/idea.MD",
        "research/notes/my idea.md",
        "research/notes/app/__main__.py",
        "research/notes/run.sh",
        "research/notes/idea.md/../../state/family_memory.json",
        "research/state/family_memory.json",
        "research/logs/passed_alphas.csv",
        "data/other.jsonl",
        "app/cli.py",
        "deploy/vm/tool_guard.py",
        ".env",
        ".claude/settings.json",
        ".claude/skills/worldquant-researcher-workflow/SKILL.md",
        "CLAUDE.md",
        "README.md",
        "docs/researcher-prompt.md",
        "research/README.md",
        "../outside.md",
        "~/.bashrc",
    ],
)
def test_write_blocks_every_other_path(config, repo: Path, path: str) -> None:
    assert _decide(config, repo, "Write", {"file_path": path}) is not None
    assert _decide(config, repo, "Edit", {"file_path": path}) is not None


def test_notebook_edit_is_not_a_write_tool(config, repo: Path) -> None:
    payload = {"file_path": "research/notes/a.md", "notebook_path": "x.ipynb"}
    assert _decide(config, repo, "NotebookEdit", payload) is not None


def test_grep_needs_a_path_below_the_repository_root(config, repo: Path) -> None:
    assert _decide(config, repo, "Grep", {"pattern": "fitness", "path": "research"}) is None
    assert _decide(config, repo, "Grep", {"pattern": "fitness", "path": "README.md", "glob": "*.md"}) is None

    for blocked in ({"pattern": "WQ_"}, {"pattern": "WQ_", "path": "."}, {"pattern": "WQ_", "path": str(repo)}):
        assert _decide(config, repo, "Grep", blocked) is not None
    assert _decide(config, repo, "Grep", {"pattern": "WQ_", "path": ".env"}) is not None
    assert _decide(config, repo, "Grep", {"pattern": "x", "path": ".."}) is not None
    assert _decide(config, repo, "Grep", {"pattern": "x", "path": "research", "glob": "../**"}) is not None
    # Brace alternatives expand to `..` or an absolute path after the check.
    for glob in ("{..,x}/.env", "{/etc,x}/*", "*.{md,json}", "x}"):
        assert _decide(config, repo, "Grep", {"pattern": "x", "path": "research", "glob": glob}) is not None


def test_glob_stays_inside_the_repository(config, repo: Path) -> None:
    assert _decide(config, repo, "Glob", {"pattern": "**/*.md"}) is None
    assert _decide(config, repo, "Glob", {"pattern": "*.json", "path": "research/state"}) is None

    assert _decide(config, repo, "Glob", {"pattern": "/etc/*"}) is not None
    assert _decide(config, repo, "Glob", {"pattern": "../*"}) is not None
    assert _decide(config, repo, "Glob", {"pattern": "~/.ssh/*"}) is not None
    assert _decide(config, repo, "Glob", {"pattern": "*", "path": ".."}) is not None
    assert _decide(config, repo, "Glob", {"pattern": "{..,x}/*"}) is not None
    assert _decide(config, repo, "Glob", {"pattern": "{/etc,x}/*"}) is not None
    assert _decide(config, repo, "Glob", {"pattern": "**/*.{md,json}"}) is not None
    assert _decide(config, repo, "Glob", {}) is not None


@pytest.mark.parametrize("tool", ["WebFetch", "WebSearch", "Agent", "Task", "mcp__server__tool", "KillShell", "SomethingNew"])
def test_unknown_and_network_tools_are_blocked(config, repo: Path, tool: str) -> None:
    assert _decide(config, repo, tool, {"url": "https://example.com", "prompt": "x"}) is not None


def test_bookkeeping_tools_and_the_workflow_skill_pass(config, repo: Path) -> None:
    assert _decide(config, repo, "TodoWrite", {"todos": []}) is None
    assert _decide(config, repo, "Skill", {"skill": "worldquant-researcher-workflow"}) is None
    denied = _decide(config, repo, "Skill", {"skill": "other-skill", "args": "secret-value"})
    assert denied is not None and "tool_input keys: args, skill" in denied and "secret-value" not in denied
    assert _decide(config, repo, "Skill", {"skill": "evil:worldquant-researcher-workflow"}) is not None
    assert _decide(config, repo, "Skill", {}) is not None


@pytest.mark.parametrize("payload", [None, [], "x", {}, {"tool_name": "Bash"}, {"tool_name": 1, "tool_input": {}}, {"tool_name": "Bash", "tool_input": "ls"}])
def test_malformed_input_is_blocked(config, payload) -> None:
    assert guard.decide(payload, config) is not None


def _run_hook(repo: Path, stdin: str, log: Path | None = None, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("WQ_GUARD_")}
    env.update({"WQ_GUARD_REPO": str(repo), "WQ_GUARD_PYTHON": PY})
    if log is not None:
        env["WQ_GUARD_LOG"] = str(log)
    env.update(env_overrides)
    for key in [name for name, value in env.items() if value == ""]:
        del env[key]
    return subprocess.run([sys.executable, str(GUARD_PATH)], input=stdin, env=env, capture_output=True, text=True, timeout=60, check=False)


def test_hook_exit_codes_and_log(repo: Path, tmp_path: Path) -> None:
    log = tmp_path / "guard.log"
    allowed = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "README.md"}, "cwd": str(repo)})
    blocked = json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat .env"}, "cwd": str(repo)})

    first = _run_hook(repo, allowed, log)
    assert first.returncode == 0
    assert first.stderr == ""

    second = _run_hook(repo, blocked, log)
    assert second.returncode == 2
    assert "Blocked by deploy/vm/tool_guard.py" in second.stderr

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith(" allow Read")
    assert " deny Bash | " in lines[1]


def test_hook_fails_closed(repo: Path) -> None:
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "README.md"}, "cwd": str(repo)})

    assert _run_hook(repo, "not json").returncode == 2
    assert _run_hook(repo, "").returncode == 2
    assert _run_hook(repo, payload, WQ_GUARD_REPO="").returncode == 2
    assert _run_hook(repo, payload, WQ_GUARD_PYTHON="").returncode == 2
    assert _run_hook(repo, payload, WQ_GUARD_REPO="relative/path").returncode == 2
