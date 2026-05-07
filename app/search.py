from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence
import math
import random

from app.models import AlphaCandidate, SearchObservation
from app.templates import TemplateEngine


class SearchEngine(ABC):
    @abstractmethod
    def initialize(
        self,
        seed_candidates: Optional[Sequence[AlphaCandidate]] = None,
        constraints: Optional[Dict[str, object]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def propose(self, batch_size: int) -> List[AlphaCandidate]:
        raise NotImplementedError

    @abstractmethod
    def observe_result(self, observations: Sequence[SearchObservation]) -> None:
        raise NotImplementedError

    @abstractmethod
    def next_batch(self, history: Sequence[SearchObservation], batch_size: int) -> List[AlphaCandidate]:
        raise NotImplementedError


class GeneticSearchEngine(SearchEngine):
    def __init__(
        self,
        template_engine: TemplateEngine,
        population_size: int,
        elite_count: int,
        mutation_rate: float,
        crossover_rate: float,
        immigrant_ratio: float = 0.2,
        seed: int = 11,
    ) -> None:
        self.template_engine = template_engine
        self.population_size = population_size
        self.elite_count = elite_count
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.immigrant_ratio = immigrant_ratio
        self.random = random.Random(seed)
        self.population: List[AlphaCandidate] = []
        self.history: List[SearchObservation] = []
        self.constraints: Dict[str, object] = {}

    def initialize(
        self,
        seed_candidates: Optional[Sequence[AlphaCandidate]] = None,
        constraints: Optional[Dict[str, object]] = None,
    ) -> None:
        self.constraints = dict(constraints or {})
        population: List[AlphaCandidate] = []
        if seed_candidates:
            seen = set()
            for candidate in seed_candidates:
                if candidate.fingerprint in seen:
                    continue
                seen.add(candidate.fingerprint)
                population.append(candidate)
                if len(population) >= self.population_size:
                    break
        fresh_needed = max(self.population_size - len(population), 0)
        if fresh_needed:
            population.extend(self.template_engine.generate(fresh_needed, self.constraints))
        self.population = population[: self.population_size]

    def propose(self, batch_size: int) -> List[AlphaCandidate]:
        if not self.population:
            self.initialize()
        selected: List[AlphaCandidate] = []
        seen = set()
        for candidate in self.population:
            if candidate.fingerprint in seen:
                continue
            selected.append(candidate)
            seen.add(candidate.fingerprint)
            if len(selected) >= batch_size:
                break
        if len(selected) < batch_size:
            selected.extend(self.template_engine.generate(batch_size - len(selected), self.constraints))
        return selected[:batch_size]

    def observe_result(self, observations: Sequence[SearchObservation]) -> None:
        self.history.extend(observations)
        if observations:
            self.population = self._evolve()

    def next_batch(self, history: Sequence[SearchObservation], batch_size: int) -> List[AlphaCandidate]:
        if history:
            self.observe_result(history)
        return self.propose(batch_size)

    def _evolve(self) -> List[AlphaCandidate]:
        ranked = sorted(self.history, key=lambda item: item.reward.value, reverse=True)
        elites = [obs.candidate for obs in ranked[: self.elite_count]]
        next_population = list(elites)
        parent_pool = [obs.candidate for obs in ranked[: max(len(ranked), self.elite_count)]]
        immigrant_count = max(int(self.population_size * self.immigrant_ratio), 1)
        while len(next_population) < self.population_size:
            if len(next_population) >= self.population_size - immigrant_count:
                next_population.extend(self.template_engine.generate(1, self.constraints))
                continue
            if self.random.random() < self.crossover_rate and len(parent_pool) >= 2:
                parent_a, parent_b = self.random.sample(parent_pool, 2)
                child = self.template_engine.crossover(parent_a, parent_b)
            else:
                child = self.random.choice(parent_pool)
            if self.random.random() < self.mutation_rate:
                child = self.template_engine.mutate_candidate(child)
            next_population.append(child)
        return next_population


@dataclass
class MCTSNode:
    candidate: AlphaCandidate
    visits: int = 0
    value: float = 0.0
    children: List["MCTSNode"] = field(default_factory=list)

    def ucb_score(self, total_visits: int, exploration: float = 1.4) -> float:
        if self.visits == 0:
            return float("inf")
        return (self.value / self.visits) + exploration * math.sqrt(math.log(max(total_visits, 1)) / self.visits)


class MCTSSearchEngine(SearchEngine):
    def __init__(self, template_engine: TemplateEngine, seed: int = 19) -> None:
        self.template_engine = template_engine
        self.random = random.Random(seed)
        self.roots: List[MCTSNode] = []
        self.history: List[SearchObservation] = []

    def initialize(
        self,
        seed_candidates: Optional[Sequence[AlphaCandidate]] = None,
        constraints: Optional[Dict[str, object]] = None,
    ) -> None:
        candidates = list(seed_candidates or [])
        if len(candidates) < 4:
            candidates.extend(self.template_engine.generate(4 - len(candidates), constraints))
        self.roots = [MCTSNode(candidate) for candidate in candidates[:4]]

    def propose(self, batch_size: int) -> List[AlphaCandidate]:
        if not self.roots:
            self.initialize()
        selected = []
        for _ in range(batch_size):
            node = self._select_node()
            if not node.children:
                node.children.extend(MCTSNode(self.template_engine.mutate_candidate(node.candidate)) for _ in range(2))
            selected.append(self.random.choice(node.children or [node]).candidate)
        return selected

    def observe_result(self, observations: Sequence[SearchObservation]) -> None:
        self.history.extend(observations)
        for observation in observations:
            for root in self.roots:
                if root.candidate.template_type == observation.candidate.template_type:
                    root.visits += 1
                    root.value += observation.reward.value

    def next_batch(self, history: Sequence[SearchObservation], batch_size: int) -> List[AlphaCandidate]:
        if history:
            self.observe_result(history)
        return self.propose(batch_size)

    def _select_node(self) -> MCTSNode:
        total_visits = sum(root.visits for root in self.roots) + 1
        return max(self.roots, key=lambda node: node.ucb_score(total_visits))
