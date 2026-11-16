#!/usr/bin/env bash
# Run ONE unattended research round on a Linux VM.
#
# Claude Code runs headless (`claude -p`) and executes the
# worldquant-researcher-workflow skill once. Meant to be called from cron under
# `flock`, so rounds never overlap. Setup and operation: deploy/vm/README.md.
#
# Exit codes: 0 round finished or skipped by the STOP file, 2 missing tooling,
# 3 refused by the preflight (not a live, credentialed setup), otherwise the
# exit code of `claude` / `timeout`.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR" || exit 2
export PATH="$HOME/.local/bin:$PATH"

# Optional untracked file owned by the user: the Claude token
# (CLAUDE_CODE_OAUTH_TOKEN) and WQ_RUNNER_* overrides. Never BRAIN credentials;
# those stay in the repository's .env, which this script does not read.
RUNNER_ENV="${WQ_RUNNER_ENV_FILE:-$HOME/.config/wq-runner/env}"
if [ -f "$RUNNER_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$RUNNER_ENV"
  set +a
fi

PYTHON="${WQ_RUNNER_PYTHON:-.venv/bin/python}"
CLAUDE="${WQ_RUNNER_CLAUDE:-claude}"
MODE="${WQ_RUNNER_MODE:-}"
MODEL="${WQ_RUNNER_MODEL:-}"
ROUND_TIMEOUT="${WQ_RUNNER_TIMEOUT:-45m}"
MAX_TURNS="${WQ_RUNNER_MAX_TURNS:-80}"
MAX_FAILURES="${WQ_RUNNER_MAX_FAILURES:-3}"
KEEP_LOGS="${WQ_RUNNER_KEEP_LOGS:-200}"
STATE_DIR="${WQ_RUNNER_STATE_DIR:-$REPO_DIR/logs/agent}"

mkdir -p "$STATE_DIR" || exit 2
STOP_FILE="$STATE_DIR/STOP"
FAIL_FILE="$STATE_DIR/consecutive_failures"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$STATE_DIR/runner.log" >&2
}

# Kill switch: `touch logs/agent/STOP` pauses the loop, `rm` resumes it.
if [ -e "$STOP_FILE" ]; then
  log "skip: $STOP_FILE exists ($(head -c 200 "$STOP_FILE" | tr '\n' ' '))"
  exit 0
fi

if ! command -v "$CLAUDE" >/dev/null 2>&1; then
  log "error: '$CLAUDE' not found on PATH"
  exit 2
fi

# Preflight: only a live, credentialed setup may run. `settings` prints no
# secrets, only has_username / has_password.
if ! settings="$("$PYTHON" -m app settings 2>&1)"; then
  log "error: '$PYTHON -m app settings' failed: $(printf '%s' "$settings" | tail -n 1)"
  exit 2
fi
for want in "dry_run=False" "client_mode=requests" "has_username=True" "has_password=True"; do
  if ! grep -qxF "$want" <<<"$settings"; then
    log "refuse: settings does not show $want"
    exit 3
  fi
done

prompt="/worldquant-researcher-workflow"
if [ -n "$MODE" ]; then
  prompt="$prompt $MODE"
fi

rules="This is an unattended, scheduled run. Nobody can answer questions, so never ask one: \
if you cannot proceed, stop and say why in your final message. \
Run exactly one round of the workflow and at most one simulate. \
Call the CLI only as '$PYTHON -m app ...' from the repository root; no other shell command is permitted. \
Do not read .env. The only files you may edit are data/candidates.jsonl and files under research/notes/. \
Never submit an alpha to BRAIN. \
End with a short summary: mode, candidate id, verdict, next action."

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$STATE_DIR/round-$stamp.json"

args=(
  -p "$prompt"
  --permission-mode dontAsk
  --max-turns "$MAX_TURNS"
  --output-format json
  --append-system-prompt "$rules"
)
if [ -n "$MODEL" ]; then
  args+=(--model "$MODEL")
fi
# Variadic options go last so they cannot swallow the prompt.
args+=(
  --disallowedTools "Read(./.env)"
  --allowedTools
  "Bash($PYTHON -m app *)"
  "Read"
  "Glob"
  "Grep"
  "Edit(./data/candidates.jsonl)"
  "Edit(./research/notes/**)"
)

log "start: round $stamp mode=${MODE:-auto}"
timeout "$ROUND_TIMEOUT" "$CLAUDE" "${args[@]}" >"$out" 2>"$out.err"
status=$?

if [ "$status" -eq 0 ]; then
  rm -f "$FAIL_FILE"
  log "done: round $stamp ok -> $out"
else
  failures=$(( $(cat "$FAIL_FILE" 2>/dev/null || echo 0) + 1 ))
  echo "$failures" >"$FAIL_FILE"
  log "fail: round $stamp exit=$status consecutive_failures=$failures (stderr: $out.err)"
  if [ "$failures" -ge "$MAX_FAILURES" ]; then
    echo "stopped at $stamp after $failures consecutive failed rounds (last exit $status); fix the cause, then delete this file" >"$STOP_FILE"
    log "stop: wrote $STOP_FILE"
  fi
fi

# Keep the newest $KEEP_LOGS rounds.
ls -1t "$STATE_DIR"/round-*.json 2>/dev/null | tail -n +"$((KEEP_LOGS + 1))" | while IFS= read -r old; do
  rm -f "$old" "$old.err"
done

exit "$status"
