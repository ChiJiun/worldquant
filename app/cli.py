from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List, Optional

from app.api import RateLimiter, build_client
from app.catalog import BrainCatalogSync
from app.config import Settings
from app.dedupe import DedupeService
from app.logging_utils import configure_logging
from app.pipeline import AlphaPipeline
from app.scoring import ResultScorer
from app.search import GeneticSearchEngine, MCTSSearchEngine
from app.storage import StorageRepository
from app.templates import TemplateEngine
from app.workflow import AlphaDiscoveryWorkflow


def build_pipeline(settings: Settings, engine_name: str = "ga") -> AlphaPipeline:
    settings.ensure_directories()
    configure_logging(settings.log_dir)
    storage = StorageRepository(settings.storage_path, settings.output_dir)
    template_engine = TemplateEngine(settings.load_fields(), settings.load_template_specs())
    if engine_name == "mcts":
        search_engine = MCTSSearchEngine(template_engine)
    else:
        search_engine = GeneticSearchEngine(
            template_engine,
            population_size=settings.population_size,
            elite_count=settings.elite_count,
            immigrant_ratio=settings.immigrant_ratio,
            mutation_rate=settings.mutation_rate,
            crossover_rate=settings.crossover_rate,
        )
    dedupe = DedupeService(storage.iter_fingerprints())
    scorer = ResultScorer()
    client = build_client(settings, RateLimiter(settings.rate_limit_seconds))
    return AlphaPipeline(settings, template_engine, search_engine, storage, client, scorer, dedupe)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WorldQuant Brain alpha automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Generate candidate formulas only")
    generate.add_argument("--count", type=int, default=10)

    search = subparsers.add_parser("search", help="Run evolutionary search and simulate candidates")
    search.add_argument("--engine", choices=["ga", "mcts"], default="ga")
    search.add_argument("--generations", type=int, default=None)

    run = subparsers.add_parser("run", help="Alias for search")
    run.add_argument("--engine", choices=["ga", "mcts"], default="ga")
    run.add_argument("--generations", type=int, default=None)

    mine = subparsers.add_parser("mine", help="Continuously mine alpha candidates across cycles")
    mine.add_argument("--engine", choices=["ga", "mcts"], default="ga")
    mine.add_argument("--cycles", type=int, default=None)
    mine.add_argument("--sleep-seconds", type=float, default=None)
    resume = subparsers.add_parser("resume-mine", help="Resume mining from the latest checkpoint")
    resume.add_argument("--engine", choices=["ga", "mcts"], default="ga")
    resume.add_argument("--sleep-seconds", type=float, default=None)

    subparsers.add_parser("review", help="Print best alphas from storage")
    subparsers.add_parser("export-best", help="Export best alphas to stdout")
    subparsers.add_parser("template-list", help="Print manually reviewable alpha template families from storage")
    subparsers.add_parser("submittable-list", help="Print alphas that passed submission gates from storage")
    template_add = subparsers.add_parser("template-add", help="Manually add a seed expression to the template DB")
    template_add.add_argument("--family", required=True)
    template_add.add_argument("--expression", required=True)
    template_add.add_argument("--rationale", default="")
    template_add.add_argument("--hypothesis-id", default="manual")
    subparsers.add_parser("retry", help="Retry failed candidates")
    subparsers.add_parser("login-check", help="Check WorldQuant Brain login only")
    session_report = subparsers.add_parser("session-report", help="Show recent mining sessions")
    session_report.add_argument("--limit", type=int, default=10)
    dashboard = subparsers.add_parser("dashboard", help="Write a markdown session dashboard")
    dashboard.add_argument("--limit", type=int, default=10)
    catalog_sync = subparsers.add_parser("catalog-sync", help="Fetch WorldQuant BRAIN data fields/operators into config/fields.json")
    catalog_sync.add_argument("--output", default=None, help="Output catalog path, defaults to WQ_FIELDS_CONFIG")
    catalog_sync.add_argument("--limit", type=int, default=50)
    catalog_sync.add_argument("--no-operators", action="store_true")
    for command_name in ("workflow", "alpha-workflow"):
        workflow = subparsers.add_parser(command_name, help="Run agent-discovered hypotheses through simulate, quality tiering, and reporting")
        workflow.add_argument("--hypotheses", required=True, help="Path to JSON produced by the hypothesis scout")
        workflow.add_argument("--promote", action="store_true", help="Write high-tier families to outputs/promotable_families.json")
    return parser


def render_rows(rows: Iterable[object]) -> None:
    for row in rows:
        print(dict(row))


def main(argv: Optional[List[str]] = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    settings = Settings.load(Path.cwd())
    if args.command == "catalog-sync":
        path = Path(args.output) if args.output else settings.fields_config
        sync = BrainCatalogSync(settings, path, limit=args.limit)
        print(sync.run(include_operators=not args.no_operators))
        return 0
    if args.command in {"workflow", "alpha-workflow"}:
        runner = AlphaDiscoveryWorkflow(settings)
        try:
            path = runner.run(Path(args.hypotheses), promote=args.promote)
            print(path)
        finally:
            runner.close()
        return 0
    pipeline = build_pipeline(settings, getattr(args, "engine", "ga"))
    try:
        if args.command == "generate":
            generated = pipeline.generate_only(args.count)
            for candidate in generated:
                print(candidate.expression)
            return 0
        if args.command in {"search", "run"}:
            pipeline.run_search(args.generations)
            return 0
        if args.command == "mine":
            pipeline.run_mining_session(args.cycles, args.sleep_seconds)
            return 0
        if args.command == "resume-mine":
            pipeline.resume_mining_session(args.sleep_seconds)
            return 0
        if args.command == "retry":
            pipeline.retry_failed()
            return 0
        if args.command in {"review", "export-best"}:
            render_rows(pipeline.storage.list_best())
            return 0
        if args.command == "template-list":
            render_rows(pipeline.storage.list_alpha_templates())
            return 0
        if args.command == "submittable-list":
            render_rows(pipeline.storage.list_submittable_alphas())
            return 0
        if args.command == "template-add":
            pipeline.storage.save_alpha_template(
                family=args.family,
                hypothesis_id=args.hypothesis_id,
                seed_expression=args.expression,
                rationale=args.rationale,
                source="manual",
                status="candidate",
            )
            return 0
        if args.command == "session-report":
            render_rows(pipeline.storage.list_recent_sessions(args.limit))
            return 0
        if args.command == "dashboard":
            path = pipeline.storage.generate_session_dashboard(args.limit)
            print(path)
            return 0
        if args.command == "login-check":
            pipeline.client.login()
            mode = getattr(pipeline.client, "last_login_mode", None) or settings.client_mode
            print(f"login-ok auth_mode={mode}")
            return 0
        parser.error(f"Unknown command: {args.command}")
        return 2
    finally:
        pipeline.storage.close()
