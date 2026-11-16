# Unattended research rounds on a Linux VM

`run_research_round.sh` runs **one** round of the researcher workflow without a human: it starts Claude Code headless (`claude -p "/worldquant-researcher-workflow [mode]"`), which reads the research memory, writes one candidate, runs a live BRAIN simulation and records the result. Cron calls it repeatedly; `flock` keeps rounds from overlapping.

Nothing here submits an alpha: the CLI has no submit command. The round ends at `outputs/submit_queue.csv`; submission stays a manual step.

## What limits the agent

Two layers. The first one is the one that counts.

**1. `tool_guard.py`, a PreToolUse hook.** According to Claude Code's hook documentation, a PreToolUse hook runs before every tool call, including calls that need no permission and calls made by subagents. The guard blocks the call (exit code 2) unless it is one of these:

| Tool | Let through |
| --- | --- |
| Bash | Exactly `<python> -m app <subcommand> ...` on one line, run from the repository root, made only of letters, digits, spaces and `_ . , : = @ % + / -`. No quotes, pipes, `;`, `&&`, redirection, variables, `cd`, `cat`, `ls` or any other command. Subcommands: `settings`, `login-check`, `research`, `init-research`, `simulate`, `result`, `attribute`, `validate-candidate`, `fetch-correlations`, `select-alphas`. Not `record-passed-alpha`, not `init-data`. |
| Bash, `simulate` | Additionally needs `--limit 1`, may not use `--allow-mock`, `--expression` or `--input`, and is let through once per round. |
| Read | Paths that resolve (symlinks followed) inside the repository, except `.env` and `.env.*` other than `.env.example`. |
| Edit, Write | `data/candidates.jsonl` and `research/notes/**/*.md` only. |
| Grep | Needs a `path` inside the repository that is not the repository root, so it cannot sweep the directory that holds `.env`. |
| Glob | Patterns and paths inside the repository. |
| Skill | Only `worldquant-researcher-workflow`. |
| TodoWrite and the task-list tools | Always. |
| Anything else (WebFetch, WebSearch, Agent, MCP tools, unknown tools) | Never. |

An internal error, malformed input or missing configuration also blocks (tested). The hook is registered with `"onFailure": "block"` and a 20 second timeout, which Claude Code documents as turning a crash or a hang of the hook process into a block; that part is not exercised by the tests or by the self-test below.

**2. Claude Code's own permission settings.** `--permission-mode dontAsk` (a call that would prompt is denied), an allow list of `Bash(<python> -m app *)`, `Edit(./data/candidates.jsonl)` and `Edit(./research/notes/**/*.md)`, `--disallowedTools "Read(./.env)" "WebFetch" "WebSearch" "Agent"`, and the settings `permissions.blockReadsOutsideWorkingDirectories` / `blockWritesOutsideWorkingDirectories`. No `--dangerously-skip-permissions`. On their own these flags are not enough: Claude Code runs read-only shell commands such as `cat`, `ls` and `grep` without a prompt in every mode, which is why the hook exists.

**The runner checks that the hook really runs.** Before the first round on each Claude Code version it asks Claude for two harmless calls, `echo wq-guard-probe` and a read of `/etc/hostname`, and continues only when the guard's log shows both were blocked; it then writes `logs/agent/guard-verified-<version>` so later runs on that version skip the check. If they were not both blocked, it writes `logs/agent/STOP` and exits 4. The one exception: when `claude` exits non-zero and the guard logged nothing at all (not logged in, no network, timeout), that is counted as an ordinary failure and the runner exits with that code. A round that ends successfully without a single guard call also writes `STOP` and exits 4, and removes the `guard-verified` file.

What this does not cover:

- `python -m app` itself reads `.env` and talks to BRAIN; the agent chooses which allowed subcommands to run and with which arguments.
- The agent decides what goes into `data/candidates.jsonl`, so the alpha it simulates is its own choice. That is the point of the loop.
- "One round" is an instruction in the system prompt. What is enforced is one `simulate` per run of the script, `--max-turns` and the wall-clock timeout.
- The Claude token and, through `.env`, the BRAIN credentials are in the environment or files of the same Unix user the agent runs as. The guard keeps the agent's tools away from them; it is not an operating-system sandbox.
- The guard's rules are covered by tests. Its wiring into a real Claude Code session is checked only by the self-test above, on the machine where the runner runs.

## Setup

Requirements: Linux x86_64 or arm64, Python 3.8+ (CI runs 3.11 to 3.13), git, `flock` and `timeout` (util-linux / coreutils), Claude Code 2.1.314 or later (for the settings and `onFailure` used above), and enough memory for it (its documentation asks for 4 GB).

```bash
git clone https://github.com/ChiJiun/worldquant.git ~/worldquant
cd ~/worldquant
python3 -m venv .venv            # Debian/Ubuntu: needs the python3-venv package, or
                                 # `python3 -m venv --without-pip .venv` plus get-pip.py
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
curl -fsSL https://claude.ai/install.sh | bash   # installs ~/.local/bin/claude
```

Clone on the VM rather than copying a Windows checkout: the script must keep LF line endings.

Then, by hand:

1. **Research data.** `research/`, `data/` and `outputs/` are not in git. Copy them from the machine that has them, or start empty with `python -m app init-research`. Once the VM runs rounds it owns the research state; do not run rounds against a second copy and merge later.
2. **BRAIN credentials.** Create `~/worldquant/.env` from `.env.example` with `WQ_DRY_RUN=false`, `WQ_CLIENT_MODE=requests`, `WQ_USERNAME` and `WQ_PASSWORD`, then `chmod 600 .env`. Check with `.venv/bin/python -m app settings` and `.venv/bin/python -m app login-check`.
3. **Claude login.** Either run `claude auth login` on the VM once (open the printed URL in a browser on any machine and paste the code back), or create a long-lived token with `claude setup-token` and store it:

   ```bash
   mkdir -p ~/.config/wq-runner && chmod 700 ~/.config/wq-runner
   printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' '<token>' > ~/.config/wq-runner/env
   chmod 600 ~/.config/wq-runner/env
   ```

   Leave `ANTHROPIC_API_KEY` unset unless API billing is intended: Claude Code prefers it over a subscription login in `-p` mode.
4. **One supervised round.** Run `deploy/vm/run_research_round.sh` in a terminal. The first run does the self-test and then one real round. Read `logs/agent/runner.log`, the newest `logs/agent/round-*.json` and its `.guard.log` before scheduling anything.
5. **Schedule.** One round per hour, never overlapping:

   ```cron
   7 * * * * flock -n /tmp/wq-research.lock $HOME/worldquant/deploy/vm/run_research_round.sh >/dev/null 2>&1
   ```

   The cron line discards output, so `logs/agent/runner.log` is the only place a refused or failed run shows up.

## Operating it

| Task | Command |
| --- | --- |
| Pause | `touch ~/worldquant/logs/agent/STOP` |
| Resume | `rm ~/worldquant/logs/agent/STOP` |
| What happened | `tail -n 30 ~/worldquant/logs/agent/runner.log` |
| Last round's report | newest `~/worldquant/logs/agent/round-*.json`, field `result` |
| What the agent tried | the matching `round-*.guard.log`: one `allow` or `deny` line per tool call |
| Research state | `.venv/bin/python -m app research` |
| Update the code | pause, `git pull --ff-only`, `.venv/bin/python -m pytest -q`, resume |
| Re-run the self-test | `rm ~/worldquant/logs/agent/guard-verified-*` |

Files in `logs/agent/`: `runner.log`, `STOP`, `consecutive_failures`, `guard-verified-<claude version>`, and per run `round-<UTC>.json`, `.json.err`, `.guard.log`, `.simulate` (present when the round's simulate was let through), plus the same `selftest-<UTC>.*` files for a self-test.

## Settings

Set these in `~/.config/wq-runner/env` or in the environment of the cron line.

| Variable | Default | Meaning |
| --- | --- | --- |
| `WQ_RUNNER_MODE` | empty | Skill mode, for example `pass-alpha-improvement`; empty lets the skill infer it from research memory |
| `WQ_RUNNER_MODEL` | empty | Passed as `--model`; empty uses the Claude Code default |
| `WQ_RUNNER_TIMEOUT` | `45m` | Wall-clock limit for one `claude` run (`timeout` syntax); `SIGKILL` follows 30 seconds after `SIGTERM` |
| `WQ_RUNNER_MAX_TURNS` | `80` | Passed as `--max-turns` |
| `WQ_RUNNER_BASH_TIMEOUT_MS` | `900000` | Exported as `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS`, so a `simulate` that polls for ten minutes is not cut off at the Bash tool's two-minute default |
| `WQ_RUNNER_MAX_FAILURES` | `3` | Consecutive failures before the runner writes `STOP` |
| `WQ_RUNNER_KEEP_LOGS` | `200` | Number of round (and self-test) file sets kept |
| `WQ_RUNNER_STATE_DIR` | `logs/agent` | Where the files above live |
| `WQ_RUNNER_PYTHON` | `.venv/bin/python` | Interpreter. The agent must type exactly this string, so keep it free of spaces |
| `WQ_RUNNER_CLAUDE` | `claude` | Claude Code executable |
| `WQ_RUNNER_ENV_FILE` | `~/.config/wq-runner/env` | The optional file described above |

The four numeric settings must be positive integers; anything else exits 2 before Claude starts.

## Exit codes

| Code | Meaning | Counted as a failure |
| --- | --- | --- |
| `0` | Round finished, or skipped because `STOP` exists (a `skip:` line is logged) | no |
| `2` | Missing tooling or bad configuration | no |
| `3` | Preflight refused: `python -m app settings` did not show `dry_run=False`, `client_mode=requests`, `has_username=True` and `has_password=True` | no |
| `4` | The tool guard did not run or did not block; `STOP` is written at once | `STOP` |
| other | Exit code of `claude` or `timeout` (`124` or `137` mean the round hit `WQ_RUNNER_TIMEOUT`) | yes |

A round also counts as a failure when `claude` exits 0 but its JSON result has `is_error` true or a `subtype` starting with `error`; the runner then exits 1. Codes 2 and 3 do not stop the loop: cron keeps calling the script, and each call logs its reason to `runner.log` and exits (the only silent cases are a state directory that cannot be created and a repository directory that cannot be entered).
