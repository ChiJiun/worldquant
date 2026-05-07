from app.models import RewardBreakdown, SearchObservation, SimulationMetrics
from app.scoring import ResultScorer
from app.search import GeneticSearchEngine, MCTSSearchEngine


def test_genetic_search_engine_evolves_population(template_engine, settings):
    engine = GeneticSearchEngine(
        template_engine,
        settings.population_size,
        settings.elite_count,
        settings.mutation_rate,
        settings.crossover_rate,
        immigrant_ratio=settings.immigrant_ratio,
    )
    engine.initialize()
    batch = engine.propose(4)
    assert len(batch) == 4
    scorer = ResultScorer()
    history = [
        SearchObservation(candidate=candidate, reward=RewardBreakdown(1.0 + idx, 0.5, 0.4, 0.0), metrics=SimulationMetrics(sharpe=1.0, fitness=1.0), status="complete")
        for idx, candidate in enumerate(batch)
    ]
    next_batch = engine.next_batch(history, 4)
    assert len(next_batch) == 4
    assert all(candidate.expression for candidate in next_batch)
    assert engine.history


def test_mcts_search_engine_proposes_candidates(template_engine):
    engine = MCTSSearchEngine(template_engine)
    engine.initialize()
    batch = engine.propose(3)
    assert len(batch) == 3
    assert all(candidate.template_type for candidate in batch)
