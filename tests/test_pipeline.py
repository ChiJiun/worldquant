from app.api import MockBrainClient, RateLimiter
from app.dedupe import DedupeService
from app.models import AlphaCandidate, ExpressionNode
from app.pipeline import AlphaPipeline
from app.scoring import ResultScorer
from app.search import GeneticSearchEngine
from app.storage import StorageRepository
from app.templates import TemplateEngine


def build_pipeline(settings):
    storage = StorageRepository(settings.storage_path, settings.output_dir)
    template_engine = TemplateEngine(settings.load_fields(), settings.load_template_specs())
    search_engine = GeneticSearchEngine(
        template_engine,
        settings.population_size,
        settings.elite_count,
        settings.mutation_rate,
        settings.crossover_rate,
        immigrant_ratio=settings.immigrant_ratio,
    )
    pipeline = AlphaPipeline(
        settings=settings,
        template_engine=template_engine,
        search_engine=search_engine,
        storage=storage,
        client=MockBrainClient(RateLimiter(0.0)),
        scorer=ResultScorer(),
        dedupe=DedupeService(storage.iter_fingerprints()),
    )
    return pipeline, storage


def test_pipeline_run_search_persists_best_alpha(settings):
    settings.sharpe_threshold = 0.0
    settings.fitness_threshold = 0.0
    settings.ensure_directories()
    pipeline, storage = build_pipeline(settings)

    records = pipeline.run_search(generations=1)
    storage.close()

    assert len(records) == settings.batch_size
    assert (settings.output_dir / "run_summary.csv").exists()
    reopened = StorageRepository(settings.storage_path, settings.output_dir)
    try:
        completed = reopened.list_completed_behavior_profiles()
        assert len(completed) >= 1
    finally:
        reopened.close()


def test_pipeline_run_mining_session_accumulates_cycles(settings):
    settings.sharpe_threshold = 0.0
    settings.fitness_threshold = 0.0
    settings.ensure_directories()
    pipeline, storage = build_pipeline(settings)

    records = pipeline.run_mining_session(cycles=2, sleep_seconds=0.0)
    storage.close()

    assert len(records) == settings.batch_size * settings.generations * 2
    reopened = StorageRepository(settings.storage_path, settings.output_dir)
    try:
        sessions = reopened.list_recent_sessions(1)
        assert len(sessions) == 1
        assert int(sessions[0]["cycles_completed"]) == 2
        assert (settings.output_dir / "session_dashboard.md").exists()
    finally:
        reopened.close()


def test_pipeline_filters_low_quality_candidate(settings):
    settings.ensure_directories()
    pipeline, storage = build_pipeline(settings)
    bad_tree = ExpressionNode(
        kind="operator",
        value="rank",
        children=[
            ExpressionNode(
                kind="operator",
                value="sub",
                children=[
                    ExpressionNode(kind="field", value="close"),
                    ExpressionNode(kind="field", value="close"),
                ],
            )
        ],
    )
    bad = AlphaCandidate(expression=bad_tree.to_expression(), tree=bad_tree, template_type="momentum", params={}, wrappers=["rank"])
    record = pipeline._process_candidate(bad)
    storage.close()

    assert record.api_status == "filtered"


def test_pipeline_resume_uses_existing_session(settings):
    settings.sharpe_threshold = 0.0
    settings.fitness_threshold = 0.0
    settings.ensure_directories()
    pipeline, storage = build_pipeline(settings)
    session_id = storage.start_session(3)
    storage.update_session(
        session_id,
        cycles_completed=1,
        submitted_count=4,
        completed_count=4,
        best_count=1,
        avg_reward=0.5,
        checkpoint={"last_cycle": 1, "template_weights": {"momentum": 1.2}},
    )

    records = pipeline.resume_mining_session(sleep_seconds=0.0)
    storage.close()

    assert len(records) == settings.batch_size * settings.generations * 2
    reopened = StorageRepository(settings.storage_path, settings.output_dir)
    try:
        sessions = reopened.list_recent_sessions(1)
        assert int(sessions[0]["id"]) == session_id
        assert int(sessions[0]["cycles_completed"]) == 3
    finally:
        reopened.close()
