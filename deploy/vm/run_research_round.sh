#!/usr/bin/env bash
# Run ONE unattended research round on a Linux VM.
#
# Claude Code runs headless (`claude -p`) and executes the
# worldquant-researcher-workflow skill once. Meant to be called from cron under
# `flock`, so rounds never overlap. Setup and operation: deploy/vm/README.md.
#
# Every tool call the agent makes goes through deploy/vm/tool_guard.py (a
# PreToolUse hook), which is what actually limits it; the permission flags are a
# second layer. Before the first round on each Claude Code version the runner
# checks with two harmless probes that the hook really blocks; the check is
# repeated whenever the guard, this script or the settings it builds change.
#
# Exit codes: 0 round finished or skipped by the STOP file, 2 missing tooling or
# bad configuration, 3 refused by the preflight (not a live, credentialed
# setup), 4 the tool guard did not run or did not block (STOP is written),
# otherwise the exit code of `claude` / `timeout` (2, 3 and 4 from them are
# reported as 1 so they cannot be mistaken for the runner's own codes).
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR" || exit 2
export PATH="$HOME/.local/bin:$PATH"

# Optional untracked file owned by the user: the Claude token
# (CLAUDE_CODE_OAUTH_TOKEN) and WQ_RUNNER_* overrides.
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
BASH_TIMEOUT_MS="${WQ_RUNNER_BASH_TIMEOUT_MS:-900000}"
STATE_DIR="${WQ_RUNNER_STATE_DIR:-$REPO_DIR/logs/agent}"
GUARD="$REPO_DIR/deploy/vm/tool_guard.py"

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

for name in MAX_TURNS MAX_FAILURES KEEP_LOGS BASH_TIMEOUT_MS; do
  case "${!name}" in
    '' | *[!0-9]* | 0)
      log "error: WQ_RUNNER_$name must be a positive integer, got '${!name}'"
      exit 2
      ;;
  esac
done

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

# `onFailure` needs Claude Code 2.1.295 and blockWritesOutsideWorkingDirectories
# 2.1.314. An older release would still pass the self-test (the hook runs and
# logs its denials) but would not block when the hook crashes or hangs.
MIN_CLAUDE_VERSION="2.1.314"
claude_version_line="$("$CLAUDE" --version 2>/dev/null | head -n 1)"
if ! "$PYTHON" - "${claude_version_line%% *}" "$MIN_CLAUDE_VERSION" <<'PY'
import sys


def parse(version):
    return tuple(int(part) for part in version.split("."))


try:
    sys.exit(0 if parse(sys.argv[1]) >= parse(sys.argv[2]) else 1)
except ValueError:
    sys.exit(1)
PY
then
  log "error: Claude Code $MIN_CLAUDE_VERSION or later is required, '$CLAUDE --version' printed '$claude_version_line'"
  exit 2
fi

# The guard runs outside the repository's working directory rules, so give the
# hook an absolute interpreter even when the agent types a relative one.
case "$PYTHON" in
  /*) guard_python="$PYTHON" ;;
  *) guard_python="$REPO_DIR/$PYTHON" ;;
esac
if ! settings_json="$(
  "$PYTHON" - "$guard_python" "$GUARD" "$REPO_DIR" <<'PY'
import json
import sys

print(
    json.dumps(
        {
            "permissions": {
                "blockReadsOutsideWorkingDirectories": True,
                "blockWritesOutsideWorkingDirectories": True,
            },
            # Backstops for files the agent can write: never load a CLAUDE.md
            # from research/notes (the guard already refuses to write one), and
            # never run !`...` shell injection from skills.
            "claudeMdExcludes": [sys.argv[3] + "/research/notes/**"],
            "disableSkillShellExecution": True,
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": sys.argv[1],
                                "args": [sys.argv[2]],
                                "timeout": 20,
                                "onFailure": "block",
                            }
                        ],
                    }
                ]
            },
        }
    )
)
PY
)"; then
  log "error: could not build the Claude settings JSON"
  exit 2
fi

# The self-test result is only valid for the exact hook wiring it saw: the guard,
# this script (the flags run_claude passes) and the settings JSON.
if ! guard_digest="$(
  "$PYTHON" - "$settings_json" "$GUARD" "$REPO_DIR/deploy/vm/run_research_round.sh" <<'PY'
import hashlib
import sys

digest = hashlib.sha256(sys.argv[1].encode("utf-8"))
for path in sys.argv[2:]:
    with open(path, "rb") as handle:
        digest.update(b"\0" + handle.read())
print(digest.hexdigest()[:12])
PY
)"; then
  log "error: could not hash the tool guard and runner"
  exit 2
fi

export WQ_GUARD_REPO="$REPO_DIR"
export WQ_GUARD_PYTHON="$PYTHON"
# A simulate polls BRAIN for up to ten minutes; the Bash tool's default limit is two.
export BASH_DEFAULT_TIMEOUT_MS="$BASH_TIMEOUT_MS"
export BASH_MAX_TIMEOUT_MS="$BASH_TIMEOUT_MS"

# run_claude <prompt> <stdout file> <system prompt>
run_claude() {
  local args=(
    -p "$1"
    --permission-mode dontAsk
    --max-turns "$MAX_TURNS"
    --output-format json
    --settings "$settings_json"
    --append-system-prompt "$3"
  )
  if [ -n "$MODEL" ]; then
    args+=(--model "$MODEL")
  fi
  # Variadic options go last so they cannot swallow the prompt. A bare tool
  # name in --disallowedTools removes that tool from the session.
  args+=(
    --disallowedTools "Read(./.env)" "WebFetch" "WebSearch" "Agent"
    --allowedTools
    "Bash($PYTHON -m app *)"
    "Edit(./data/candidates.jsonl)"
    "Edit(./research/notes/*.md)"
  )
  timeout -k 30s "$ROUND_TIMEOUT" "$CLAUDE" "${args[@]}" >"$2" 2>"$2.err"
}

stop_loop() {
  echo "$1" >"$STOP_FILE"
  log "stop: wrote $STOP_FILE ($1)"
}

# runner_exit <code>: exit code of claude / timeout as the runner reports it.
# 2, 3 and 4 are the runner's own codes (configuration, preflight, guard), so a
# claude that exits with one of them is reported as an ordinary failure, 1.
runner_exit() {
  case "$1" in
    2 | 3 | 4) echo 1 ;;
    *) echo "$1" ;;
  esac
}

count_lines() {
  if [ -f "$1" ]; then grep -c "$2" "$1"; else echo 0; fi
}

# record_failure <description>: count it and stop the loop at the limit.
record_failure() {
  local previous failures
  previous="$(cat "$FAIL_FILE" 2>/dev/null)"
  case "$previous" in
    '' | *[!0-9]*) previous=0 ;;
  esac
  failures=$((previous + 1))
  echo "$failures" >"$FAIL_FILE"
  log "fail: $1 consecutive_failures=$failures"
  if [ "$failures" -ge "$MAX_FAILURES" ]; then
    stop_loop "stopped after $failures consecutive failures (last: $1); fix the cause, then delete this file"
  fi
}

stamp="$(date -u +%Y%m%dT%H%M%SZ)"

# Self-check, once per Claude Code version and guard digest: ask for two harmless
# calls the guard must block. If the hook is not wired (a changed flag, a new
# release, an edited guard), nothing sensitive was touched and the loop stops here.
claude_version="$(printf '%s' "$claude_version_line" | tr -c 'A-Za-z0-9._-' '_')"
verified="$STATE_DIR/guard-verified-${claude_version:-unknown}-$guard_digest"
if [ ! -e "$verified" ]; then
  probe_out="$STATE_DIR/selftest-$stamp.json"
  export WQ_GUARD_LOG="$STATE_DIR/selftest-$stamp.guard.log"
  # The self-test runs with the live setup too: create the marker first so the
  # guard blocks every simulate in it.
  export WQ_GUARD_SIMULATE_MARKER="$STATE_DIR/selftest-$stamp.simulate"
  : >"$WQ_GUARD_LOG"
  echo "self-test: simulate is not allowed" >"$WQ_GUARD_SIMULATE_MARKER"
  log "selftest: checking the tool guard on Claude Code '$claude_version'"
  run_claude "Tool permission self-test. Make exactly these two tool calls, then answer with the single word done: (1) the Bash tool with the command: echo wq-guard-probe (2) the Read tool with file_path /etc/hostname" \
    "$probe_out" "This is an automated self-test. Make the two requested tool calls even if you expect them to be refused, and do nothing else."
  probe_status=$?
  bash_denied="$(count_lines "$WQ_GUARD_LOG" ' deny Bash ')"
  read_denied="$(count_lines "$WQ_GUARD_LOG" ' deny Read ')"
  if [ "$bash_denied" -ge 1 ] && [ "$read_denied" -ge 1 ]; then
    echo "verified at $stamp" >"$verified"
    log "selftest: ok (Bash and Read probes were blocked)"
  elif [ "$probe_status" -ne 0 ] && [ "$(count_lines "$WQ_GUARD_LOG" '')" -eq 0 ]; then
    # Claude never got as far as a tool call (not logged in, network, timeout):
    # an ordinary failure, not evidence about the guard.
    record_failure "selftest $stamp: claude exit=$probe_status before any tool call (stderr: $probe_out.err)"
    exit "$(runner_exit "$probe_status")"
  else
    stop_loop "tool guard self-test failed at $stamp on Claude Code '$claude_version' (claude exit $probe_status, blocked Bash=$bash_denied Read=$read_denied); see $probe_out and $WQ_GUARD_LOG, fix the cause, then delete this file"
    exit 4
  fi
fi

prompt="/worldquant-researcher-workflow"
if [ -n "$MODE" ]; then
  prompt="$prompt $MODE"
fi

rules="This is an unattended, scheduled run. Nobody can answer questions, so never ask one: \
if you cannot proceed, stop and say why in your final message. \
Run exactly one round of the workflow. A hook checks every tool call and blocks anything outside these rules: \
the only shell command is '$PYTHON -m app <subcommand> ...' on one line from the repository root, with no quotes, pipes, cd or other shell syntax; \
record-passed-alpha and init-data are not available; simulate runs once per round and needs '--limit 1'; \
fetch-correlations needs '--limit N' with N from 1 to 20. \
Read only inside the repository and never .env. Give Grep a subdirectory or file as path, not the repository root, and no {} alternatives in Glob or Grep patterns. \
The only files you may write are data/candidates.jsonl and Markdown files directly in research/notes/ (name made of letters, digits, _ and -, ending in .md; not CLAUDE.md). \
Never submit an alpha to BRAIN. \
End with a short summary: mode, candidate id, verdict, next action."

out="$STATE_DIR/round-$stamp.json"
export WQ_GUARD_LOG="$STATE_DIR/round-$stamp.guard.log"
export WQ_GUARD_SIMULATE_MARKER="$STATE_DIR/round-$stamp.simulate"
: >"$WQ_GUARD_LOG"

log "start: round $stamp mode=${MODE:-auto}"
run_claude "$prompt" "$out" "$rules"
status=$?

guard_calls="$(count_lines "$WQ_GUARD_LOG" '')"
guard_denials="$(count_lines "$WQ_GUARD_LOG" ' deny ')"
summary="$("$PYTHON" - "$out" <<'PY' 2>/dev/null
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, ValueError):
    print("subtype=unreadable is_error=unknown num_turns=unknown")
else:
    data = data if isinstance(data, dict) else {}
    print(
        "subtype=%s is_error=%s num_turns=%s"
        % (data.get("subtype", "unknown"), data.get("is_error", "unknown"), data.get("num_turns", "unknown"))
    )
PY
)"
simulated=no
if [ -e "$WQ_GUARD_SIMULATE_MARKER" ]; then
  simulated=yes
fi

# A zero exit code is not enough: the JSON may still report an error.
if [ "$status" -eq 0 ]; then
  case "$summary" in
    *"is_error=True"* | *"subtype=error"*) status=1 ;;
  esac
fi

# No guard call at all means the hook did not run, unless Claude never got as far
# as a tool call (exit code non-zero and at most one turn, or no readable JSON).
turns="${summary##*num_turns=}"
case "$turns" in
  '' | *[!0-9]*) turns=0 ;;
esac
if [ "$guard_calls" -eq 0 ] && { [ "$status" -eq 0 ] || [ "$turns" -gt 1 ]; }; then
  rm -f "$verified"
  stop_loop "round $stamp ran (exit $status, num_turns=$turns) without a single tool-guard call, so the hook did not run; see $out, fix the cause, then delete this file"
  exit 4
fi

if [ "$status" -eq 0 ]; then
  rm -f "$FAIL_FILE"
  log "done: round $stamp ok simulate=$simulated guard_calls=$guard_calls guard_denials=$guard_denials $summary -> $out"
else
  record_failure "round $stamp exit=$status simulate=$simulated guard_calls=$guard_calls guard_denials=$guard_denials $summary (stderr: $out.err)"
fi

# Keep the newest $KEEP_LOGS rounds and self-tests.
for kind in round selftest; do
  ls -1t "$STATE_DIR"/"$kind"-*.json 2>/dev/null | tail -n +"$((KEEP_LOGS + 1))" | while IFS= read -r old; do
    rm -f "$old" "$old.err" "${old%.json}.guard.log" "${old%.json}.simulate"
  done
done

exit "$(runner_exit "$status")"
