import copy
import random
from abc import ABC, abstractmethod
from typing import Dict, List

import numpy as np

from brain_infra.alpha import Alpha
from brain_infra.alpha_list import AlphaList


class ResearchProcessBase(ABC):
    def __init__(self, process_name, scorer, additional_scorers=[]):
        self.process_name = process_name
        self.scorer = scorer
        self.additional_scorers = list(additional_scorers)
        self._alpha_lists = []
        self._score_lists = []

    def generate_alpha_name(self, gen, i) -> str:
        return f"{self.process_name}_{gen}_{i}"

    def sim_alphas(self, alphas):
        alpha_list = AlphaList(alphas, [a.name for a in alphas])
        self._alpha_lists.append(alpha_list)
        alpha_list.sim_and_wait()
        scored_alphas = alpha_list.get_alphas()
        score_dict = {name: self.scorer.score(alpha) for name, alpha in scored_alphas.items()}
        self._score_lists.append(score_dict)

    @abstractmethod
    def run(self):
        raise NotImplementedError


class GeneticAlgorithmProcess(ResearchProcessBase):
    def __init__(
        self,
        name,
        scorer,
        alpha_template,
        alpha_space,
        alpha_settings,
        ga_config={
            "generation": 15,
            "population": 50,
            "select_rate": 0.5,
            "mutation_prob": 0.05,
        },
    ):
        super().__init__(name, scorer)
        self.template = alpha_template
        self.alpha_space = alpha_space
        self.alpha_settings = alpha_settings
        self.ga_config = dict(ga_config)
        self._generation_genes: List[Dict[str, Dict[str, str]]] = []

    def _generate_expr(self, gene) -> str:
        expr = self.template
        for placeholder, value in gene.items():
            expr = expr.replace(placeholder, str(value))
        return expr

    def _init_population(self):
        self._generation_iter(gen_i=0, genes=[])

    def _generation_iter(self, gen_i, genes):
        if not genes:
            genes = []
            placeholders = list(self.alpha_space.keys())
            for _ in range(self.ga_config["population"]):
                gene = {
                    placeholder: random.choice(self.alpha_space[placeholder])
                    for placeholder in placeholders
                }
                genes.append(gene)

        generation_gene_map: Dict[str, Dict[str, str]] = {}
        alphas = []
        for i, gene in enumerate(genes):
            alpha_name = self.generate_alpha_name(gen_i, i)
            generation_gene_map[alpha_name] = copy.deepcopy(gene)
            payload = dict(self.alpha_settings)
            payload["expression"] = self._generate_expr(gene)
            alphas.append(Alpha(alpha_name, payload))
        self._generation_genes.append(generation_gene_map)
        self.sim_alphas(alphas)

    def _select(self, scores) -> List[str]:
        if not scores:
            return []
        threshold = np.quantile(list(scores.values()), self.ga_config["select_rate"])
        return [name for name, score in scores.items() if score >= threshold]

    def _crossover(self, parent_genes) -> dict:
        return {
            placeholder: random.choice(parent_genes)[placeholder]
            for placeholder in self.alpha_space.keys()
        }

    def _mutate(self, gene) -> dict:
        mutated = {}
        for placeholder, current_value in gene.items():
            if random.random() < self.ga_config["mutation_prob"]:
                mutated[placeholder] = random.choice(self.alpha_space[placeholder])
            else:
                mutated[placeholder] = current_value
        return mutated

    def run(self):
        self._init_population()
        for generation_index in range(1, self.ga_config["generation"]):
            scores = self._score_lists[-1]
            selected_names = self._select(scores)
            current_generation_genes = self._generation_genes[-1]
            surviving_genes = [
                current_generation_genes[name]
                for name in selected_names
                if name in current_generation_genes
            ]
            if not surviving_genes:
                surviving_genes = list(current_generation_genes.values())

            next_genes = []
            for _ in range(self.ga_config["population"]):
                parents = random.choices(surviving_genes, k=2)
                child_gene = self._crossover(parents)
                next_genes.append(self._mutate(child_gene))
            self._generation_iter(generation_index, next_genes)
