from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from app.api import RateLimiter, build_client
from app.config import Settings
from app.logging_utils import configure_logging
from app.models import AlphaCandidate
from app.simulator import SimulateRunner, render_metrics


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal WorldQuant BRAIN API simulator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-data", help="Create editable data/output folders and sample candidate file")
    subparsers.add_parser("login-check", help="Check WorldQuant BRAIN login")

    simulate = subparsers.add_parser("simulate", help="Submit candidates and write JSONL results")
    simulate.add_argument("--input", default=None, help="JSONL or JSON candidate file. Defaults to WQ_CANDIDATE_FILE")
    simulate.add_argument("--limit", type=int, default=None, help="Optional max number of candidates to submit")
    simulate.add_argument("--expression", default=None, help="Submit one expression without editing the input file")
    simulate.add_argument("--family", default="manual", help="Family name for --expression")
    simulate.add_argument("--candidate-id", default="", help="Candidate id for --expression")

    result = subparsers.add_parser("result", help="Fetch one result/alpha by id and print metrics JSON")
    result.add_argument("result_id")

    subparsers.add_parser("settings", help="Print non-secret effective settings")
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

    if args.command == "settings":
        _print_settings(settings)
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
        run_dir = SimulateRunner(settings, client).run(input_path, limit=args.limit)
        print(run_dir)
        return 0

    if args.command == "result":
        metrics = client.fetch_result(args.result_id)
        print(render_metrics(metrics))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _init_data(settings: Settings) -> None:
    if not settings.candidate_file.exists():
        settings.candidate_file.write_text(
            '{"candidate_id":"A_manual_001","family":"api_smoke","expression":"rank(close)","notes":"Replace with one expression per line."}\n',
            encoding="utf-8",
        )


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
        "has_username": bool(settings.username),
        "has_password": bool(settings.password),
        "simulation_settings": settings.simulation_settings_payload(),
    }
    for key, value in rows.items():
        print(f"{key}={value}")
