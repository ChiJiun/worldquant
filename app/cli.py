from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from app.api import RateLimiter, build_client
from app.config import Settings
from app.logging_utils import configure_logging
from app.models import AlphaCandidate
from app.research import initialize_research_dir, summarize_workflow_state
from app.selection import run_selection_pipeline
from app.simulator import SimulateRunner, render_metrics
from app.validation import validate_candidate_from_memory


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal WorldQuant BRAIN API simulator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-data", help="Create editable data/output/research folders and sample files")
    subparsers.add_parser("init-research", help="Create researcher memory and append-only research logs")
    subparsers.add_parser("login-check", help="Check WorldQuant BRAIN login")

    simulate = subparsers.add_parser("simulate", help="Submit candidates and write JSONL results")
    simulate.add_argument("--input", default=None, help="JSONL or JSON candidate file. Defaults to WQ_CANDIDATE_FILE")
    simulate.add_argument("--limit", type=int, default=None, help="Optional max number of candidates to submit")
    simulate.add_argument("--expression", default=None, help="Submit one expression without editing the input file")
    simulate.add_argument("--family", default="manual", help="Family name for --expression")
    simulate.add_argument("--candidate-id", default="", help="Candidate id for --expression")
    simulate.add_argument("--current-run", action="store_true", help="Overwrite outputs/current_run instead of creating outputs/runs/<run_id>")

    result = subparsers.add_parser("result", help="Fetch one result/alpha by id and print metrics JSON")
    result.add_argument("result_id")

    validate = subparsers.add_parser("validate-candidate", help="Print deterministic validation report from research memory")
    validate.add_argument("--candidate-id", default=None, help="Candidate id to validate. Defaults to global best")
    validate.add_argument("--write-artifact", action="store_true", help="Append validation_reports files. Default prints only")

    research = subparsers.add_parser("research", help="Summarize the current research loop state")
    research.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "pass-alpha-search", "pass-alpha-improvement"],
        help="Force or inspect the current research loop mode",
    )

    subparsers.add_parser("settings", help="Print non-secret effective settings")
    select = subparsers.add_parser("select-alphas", help="Build low-correlation best alpha pool and submit queue")
    select.add_argument("--finalize-run", action="store_true", help="Persist a structured final selection state for the next workflow turn")
    select.add_argument("--clear-candidates", action="store_true", help="Clear the candidate input file after final selection succeeds")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    settings = Settings.load(Path.cwd())
    settings.ensure_directories()
    configure_logging(settings.log_dir)
    client = build_client(settings, RateLimiter(settings.rate_limit_seconds))

    if args.command == "init-data":
        _init_data(settings)
        print(settings.candidate_file)
        return 0

    if args.command == "init-research":
        initialize_research_dir(settings.research_dir)
        print(settings.research_dir)
        return 0

    if args.command == "settings":
        _print_settings(settings)
        return 0

    if args.command == "select-alphas":
        report = run_selection_pipeline(
            settings.research_dir,
            settings.output_dir,
            finalize=args.finalize_run,
            candidate_file=settings.candidate_file,
            clear_candidates=args.clear_candidates,
        )
        print(render_metrics_payload(report))
        return 0

    if args.command == "research":
        report = summarize_workflow_state(settings.research_dir, requested_mode=args.mode)
        print(render_metrics_payload(report))
        return 0

    if args.command == "login-check":
        client.login()
        mode = getattr(client, "last_login_mode", settings.client_mode)
        print(f"login-ok auth_mode={mode}")
        return 0

    if args.command == "simulate":
        if args.expression:
            candidate = AlphaCandidate(
                candidate_id=args.candidate_id,
                family=args.family,
                expression=args.expression,
            )
            temp_input = settings.output_dir / "manual_candidate.jsonl"
            temp_input.write_text(
                f'{{"candidate_id": "{candidate.candidate_id}", "family": "{candidate.family}", "expression": "{candidate.expression}"}}\n',
                encoding="utf-8",
            )
            input_path = temp_input
        else:
            input_path = Path(args.input) if args.input else settings.candidate_file
        run_dir = SimulateRunner(settings, client).run(input_path, limit=args.limit, archive_run=not args.current_run)
        print(run_dir)
        return 0

    if args.command == "result":
        metrics = client.fetch_result(args.result_id)
        print(render_metrics(metrics))
        return 0

    if args.command == "validate-candidate":
        report = validate_candidate_from_memory(settings.research_dir, args.candidate_id, persist=args.write_artifact)
        print(render_metrics_payload(report))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _init_data(settings: Settings) -> None:
    if not settings.candidate_file.exists():
        example_path = Path(__file__).resolve().parents[1] / "data" / "candidates.example.jsonl"
        settings.candidate_file.parent.mkdir(parents=True, exist_ok=True)
        settings.candidate_file.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    initialize_research_dir(settings.research_dir)


def _print_settings(settings: Settings) -> None:
    rows = {
        "api_base_url": settings.api_base_url,
        "auth_mode": settings.auth_mode,
        "client_mode": settings.client_mode,
        "dry_run": settings.dry_run,
        "request_timeout_seconds": settings.request_timeout_seconds,
        "rate_limit_seconds": settings.rate_limit_seconds,
        "max_poll_attempts": settings.max_poll_attempts,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "candidate_file": str(settings.candidate_file),
        "output_dir": str(settings.output_dir),
        "research_dir": str(settings.research_dir),
        "has_username": bool(settings.username),
        "has_password": bool(settings.password),
        "simulation_settings": settings.simulation_settings_payload(),
    }
    for key, value in rows.items():
        print(f"{key}={value}")


def render_metrics_payload(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
