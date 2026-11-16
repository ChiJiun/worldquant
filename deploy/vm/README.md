# Unattended research rounds on a Linux VM

`run_research_round.sh` runs **one** round of the researcher workflow without a human: it starts Claude Code headless (`claude -p "/worldquant-researcher-workflow [mode]"`), which reads the research memory, writes one candidate, runs one live BRAIN simulation and records the result. Cron calls it repeatedly; `flock` keeps rounds from overlapping.

Nothing here submits an alpha. The round ends at `outputs/submit_queue.csv`; submission stays a manual step.

## What the runner does

1. Sources `~/.config/wq-runner/env` when it exists (Claude token and `WQ_RUNNER_*` overrides).
2. Exits 0 without doing anything when `logs/agent/STOP` exists.
3. Preflight: `python -m app settings` must show `dry_run=False`, `client_mode=requests`, `has_username=True` and `has_password=True`; otherwise it exits 3 and Claude is never started.
4. Starts Claude Code with `--permission-mode dontAsk`, so every tool call outside the allow list is denied instead of prompted:
   - allowed: `Bash(.venv/bin/python -m app *)`, `Read`, `Glob`, `Grep`, `Edit(./data/candidates.jsonl)`, `Edit(./research/notes/**)`
   - denied: `Read(./.env)`
   - no web tools, no other shell command, no `--dangerously-skip-permissions`
5. Writes Claude's JSON output to `logs/agent/round-<UTC timestamp>.json` (stderr to the same name plus `.err`) and one line per event to `logs/agent/runner.log`.
6. Counts consecutive failed rounds in `logs/agent/consecutive_failures`; at `WQ_RUNNER_MAX_FAILURES` it writes `logs/agent/STOP` and later runs are skipped until that file is deleted.

The allow list is a guard rail, not a sandbox: `python -m app` reads `.env` itself, and the agent decides which CLI subcommands to run. Run it on a machine and BRAIN account where that is acceptable.

## Setup

Requirements: Linux x86_64 or arm64, Python 3.8+ (CI runs 3.11 to 3.13), git, `flock` and `timeout` (util-linux / coreutils), and enough memory for Claude Code (its documentation asks for 4 GB).

```bash
git clone https://github.com/ChiJiun/worldquant.git ~/worldquant
cd ~/worldquant
python3 -m venv .venv            # Debian/Ubuntu: needs the python3-venv package, or
                                 # `python3 -m venv --without-pip .venv` plus get-pip.py
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
curl -fsSL https://claude.ai/install.sh | bash   # installs ~/.local/bin/claude
```

Then, by hand:

1. **Research data.** `research/`, `data/` and `outputs/` are not in git. Copy them from the machine that has them, or start empty with `python -m app init-research`. Once the VM runs rounds it owns the research state; do not run rounds against a second copy and merge later.
2. **BRAIN credentials.** Create `~/worldquant/.env` from `.env.example` with `WQ_DRY_RUN=false`, `WQ_CLIENT_MODE=requests`, `WQ_USERNAME` and `WQ_PASSWORD`, then `chmod 600 .env`. Check with `.venv/bin/python -m app settings` and `.venv/bin/python -m app login-check`.
3. **Claude login.** Either run `claude` on the VM once and use `/login` (copy the URL to a browser elsewhere), or create a long-lived token with `claude setup-token` and store it:

   ```bash
   mkdir -p ~/.config/wq-runner && chmod 700 ~/.config/wq-runner
   printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' '<token>' > ~/.config/wq-runner/env
   chmod 600 ~/.config/wq-runner/env
   ```

   Leave `ANTHROPIC_API_KEY` unset unless API billing is intended: Claude Code prefers it over a subscription login in `-p` mode.
4. **One supervised round.** Run `deploy/vm/run_research_round.sh` in a terminal and read `logs/agent/runner.log` and the newest `logs/agent/round-*.json` before scheduling anything.
5. **Schedule.** One round per hour, never overlapping:

   ```cron
   7 * * * * flock -n /tmp/wq-research.lock $HOME/worldquant/deploy/vm/run_research_round.sh >/dev/null 2>&1
   ```

## Operating it

| Task | Command |
| --- | --- |
| Pause | `touch ~/worldquant/logs/agent/STOP` |
| Resume | `rm ~/worldquant/logs/agent/STOP` |
| What happened | `tail -n 30 ~/worldquant/logs/agent/runner.log` |
| Last round's report | newest `~/worldquant/logs/agent/round-*.json`, field `result` |
| Research state | `.venv/bin/python -m app research` |
| Update the code | pause, `git pull --ff-only`, `.venv/bin/python -m pytest -q`, resume |

## Settings

Set these in `~/.config/wq-runner/env` or in the environment of the cron line.

| Variable | Default | Meaning |
| --- | --- | --- |
| `WQ_RUNNER_MODE` | empty | Skill mode, for example `pass-alpha-improvement`; empty lets the skill infer it from research memory |
| `WQ_RUNNER_MODEL` | empty | Passed as `--model`; empty uses the Claude Code default |
| `WQ_RUNNER_TIMEOUT` | `45m` | Wall-clock limit for one round (`timeout` syntax) |
| `WQ_RUNNER_MAX_TURNS` | `80` | Passed as `--max-turns` |
| `WQ_RUNNER_MAX_FAILURES` | `3` | Consecutive failed rounds before the runner writes `STOP` |
| `WQ_RUNNER_KEEP_LOGS` | `200` | Number of `round-*.json` files kept |
| `WQ_RUNNER_STATE_DIR` | `logs/agent` | Where logs, `STOP` and the failure counter live |
| `WQ_RUNNER_PYTHON` | `.venv/bin/python` | Interpreter; also the prefix of the allowed `Bash(...)` rule |
| `WQ_RUNNER_CLAUDE` | `claude` | Claude Code executable |
| `WQ_RUNNER_ENV_FILE` | `~/.config/wq-runner/env` | The optional file described above |

Exit codes: `0` round finished or skipped by `STOP`, `2` missing tooling, `3` refused by the preflight, anything else is the exit code of `claude` or `timeout` (`124` means the round hit `WQ_RUNNER_TIMEOUT`).
