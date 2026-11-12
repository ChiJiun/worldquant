from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from app.api import RateLimiter, build_client
from app.attribution import build_attribution
from app.config import Settings
from app.correlations import fetch_correlations
from app.logging_utils import configure_logging
from app.models import AlphaCandidate
from app.research import (
    PASSED_METRIC_FIELDS,
    initialize_research_dir,
    load_family_memory,
    record_passed_alpha,
    summarize_workflow_state,
)
from app.research_paths import research_paths
from app.selection import load_passed_alpha_records, run_selection_pipeline
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
    simulate.add_argument("--instrument-type", default=None, help="Override BRAIN instrumentType for this simulation")
    simulate.add_argument("--region", default=None, help="Override BRAIN region for this simulation")
    simulate.add_argument("--universe", default=None, help="Override BRAIN universe for this simulation")
    simulate.add_argument("--language", default=None, help="Override BRAIN expression language for this simulation")
    simulate.add_argument("--decay", type=int, default=None, help="Override BRAIN decay for this simulation")
    simulate.add_argument("--delay", type=int, default=None, help="Override BRAIN delay for this simulation")
    simulate.add_argument("--truncation", type=float, default=None, help="Override BRAIN truncation for this simulation")
    simulate.add_argument("--neutralization", default=None, help="Override BRAIN neutralization for this simulation")
    simulate.add_argument("--pasteurization", default=None, help="Override BRAIN pasteurization for this simulation")
    simulate.add_argument("--lookback", type=int, default=None, help="Override BRAIN lookback for this simulation")
    simulate.add_argument("--max-trade", default=None, help="Override BRAIN maxTrade for this simulation")
    simulate.add_argument("--max-position", default=None, help="Override BRAIN maxPosition for this simulation")

    result = subparsers.add_parser("result", help="Fetch one result/alpha by id and print metrics JSON")
    result.add_argument("result_id")

    validate = subparsers.add_parser("validate-candidate", help="Print deterministic validation report from research memory")
    validate.add_argument("--candidate-id", default=None, help="Candidate id to validate. Defaults to global best")
    validate.add_argument("--write-artifact", action="store_true", help="Append validation_reports files. Default prints only")
    validate.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch the alpha and its self-correlation from BRAIN before judging (needs a live client)",
    )

    attribute = subparsers.add_parser(
        "attribute",
        help="Compare one candidate's metrics against its parent, family best, and global best",
    )
    attribute.add_argument("--candidate-id", default=None, help="Candidate id to attribute. Defaults to global best")

    research = subparsers.add_parser("research", help="Summarize the current research loop state")
    research.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "pass-alpha-search", "pass-alpha-improvement"],
        help="Force or inspect the current research loop mode",
    )

    subparsers.add_parser("settings", help="Print non-secret effective settings")

    record = subparsers.add_parser(
        "record-passed-alpha",
        help="Append one verified alpha to research/logs/passed_alphas.csv without hand-editing the CSV",
    )
    record.add_argument("--candidate-id", required=True, help="Candidate id, e.g. BLUE_SYNERGY_001")
    record.add_argument("--family", required=True, help="Alpha family / hypothesis name")
    record.add_argument("--expression", required=True, help="BRAIN expression")
    record.add_argument("--result-id", required=True, help="BRAIN alpha id returned by the platform")
    record.add_argument("--sharpe", type=float, default=None)
    record.add_argument("--fitness", type=float, default=None)
    record.add_argument("--returns", type=float, default=None)
    record.add_argument("--drawdown", type=float, default=None)
    record.add_argument("--turnover", type=float, default=None)
    record.add_argument(
        "--decision",
        default="validate_best_candidate",
        choices=["validate_best_candidate", "promote_candidate"],
        help="Pass-gate decision stored with the row",
    )
    record.add_argument("--recorded-at", default=None, help="ISO-8601 UTC timestamp. Defaults to now")
    record.add_argument(
        "--fetch-metrics",
        action="store_true",
        help="Fill metrics that were not passed on the command line from BRAIN using --result-id (needs a live client)",
    )
    record.add_argument("--allow-duplicate", action="store_true", help="Append even if result_id already exists in the CSV")

    corr = subparsers.add_parser(
        "fetch-correlations",
        help="Fetch BRAIN self/prod correlation for alphas and cache them for select-alphas",
    )
    corr.add_argument(
        "--alpha-id",
        action="append",
        default=None,
        help="Alpha id to fetch; repeat for several. Defaults to every result_id in research/logs/passed_alphas.csv",
    )
    corr.add_argument("--kind", choices=["self", "prod", "both"], default="self", help="Which correlation endpoint(s) to call")
    corr.add_argument("--refresh", action="store_true", help="Refetch alphas that are already cached")
    corr.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of API calls this run, failed calls included (alphas skipped as cached do not count)",
    )
    corr.add_argument(
        "--allow-mock",
        action="store_true",
        help="Smoke-test only: let the mock client write empty (valueless) entries into the cache under WQ_DRY_RUN=true",
    )

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

    if args.command == "fetch-correlations":
        mock_client = settings.dry_run or settings.client_mode.lower() == "mock"
        if mock_client and not args.allow_mock:
            parser.error(
                "fetch-correlations needs a live BRAIN client: the mock client would cache empty results and disable the "
                "submitted-alpha gate; set WQ_DRY_RUN=false and WQ_CLIENT_MODE=requests, or pass --allow-mock for a smoke run"
            )
        paths = research_paths(settings.research_dir)
        alpha_ids = args.alpha_id or [record.alpha_id for record in load_passed_alpha_records(paths.passed_alphas)]
        if not alpha_ids:
            parser.error("no alpha ids: pass --alpha-id or record passed alphas first")
        kinds = ("self", "prod") if args.kind == "both" else (args.kind,)
        report = fetch_correlations(
            client,
            alpha_ids,
            paths.alpha_correlations,
            kinds=kinds,
            refresh=args.refresh,
            limit=args.limit,
        )
        report["client_mode"] = getattr(client, "last_login_mode", None) or settings.client_mode
        report["dry_run"] = settings.dry_run
        report["mock_cache"] = mock_client
        print(render_metrics_payload(report))
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

    if args.command == "record-passed-alpha":
        row = {
            "recorded_at": args.recorded_at,
            "candidate_id": args.candidate_id,
            "family": args.family,
            "expression": args.expression,
            "result_id": args.result_id,
            "sharpe": args.sharpe,
            "fitness": args.fitness,
            "returns": args.returns,
            "drawdown": args.drawdown,
            "turnover": args.turnover,
            "decision": args.decision,
        }
        if args.fetch_metrics:
            if settings.dry_run or settings.client_mode.lower() == "mock":
                parser.error("--fetch-metrics needs a live BRAIN client; set WQ_DRY_RUN=false and WQ_CLIENT_MODE=requests")
            row = merge_fetched_metrics(row, client.fetch_result(args.result_id).as_dict())
        written = record_passed_alpha(settings.research_dir, row, allow_duplicate=args.allow_duplicate)
        print(render_metrics_payload(written))
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
        _apply_simulation_overrides(settings, args)
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
        if args.refresh and (settings.dry_run or settings.client_mode.lower() == "mock"):
            parser.error("--refresh needs a live BRAIN client; set WQ_DRY_RUN=false and WQ_CLIENT_MODE=requests")
        report = validate_candidate_from_memory(
            settings.research_dir,
            args.candidate_id,
            persist=args.write_artifact,
            refresh=args.refresh,
            client=client if args.refresh else None,
        )
        print(render_metrics_payload(report))
        return 0

    if args.command == "attribute":
        paths = research_paths(settings.research_dir)
        report = build_attribution(
            load_family_memory(settings.research_dir),
            args.candidate_id,
            decisions_path=paths.experiment_decisions,
            csv_paths=(paths.passed_alphas, paths.failed_alphas),
        )
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
        "api_self_corr_path": settings.api_self_corr_path,
        "api_prod_corr_path": settings.api_prod_corr_path,
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


def _apply_simulation_overrides(settings: Settings, args: argparse.Namespace) -> None:
    overrides = {
        "instrument_type": args.instrument_type,
        "region": args.region,
        "universe": args.universe,
        "language": args.language,
        "decay": args.decay,
        "delay": args.delay,
        "truncation": args.truncation,
        "neutralization": args.neutralization,
        "pasteurization": args.pasteurization,
        "lookback": args.lookback,
        "max_trade": args.max_trade,
        "max_position": args.max_position,
    }
    for key, value in overrides.items():
        if value is not None:
            setattr(settings, key, value)


def merge_fetched_metrics(row: dict, fetched: dict) -> dict:
    """Fill metrics missing from the CLI row with values fetched from BRAIN.

    Explicit command-line values always win so a researcher can correct a
    platform number without re-fetching.
    """
    merged = dict(row)
    for name in PASSED_METRIC_FIELDS:
        if merged.get(name) is None:
            merged[name] = fetched.get(name)
    return merged


def render_metrics_payload(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
