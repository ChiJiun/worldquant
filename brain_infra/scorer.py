from abc import ABC, abstractmethod
from typing import List


class ScorerBase(ABC):
    @abstractmethod
    def get_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def score(self, alpha) -> float:
        raise NotImplementedError

    def score_list(self, alpha_list) -> List[float]:
        return [self.score(alpha) for alpha in alpha_list._alphas]


class SharpeScorer(ScorerBase):
    def get_name(self) -> str:
        return "sharpe"

    def score(self, alpha) -> float:
        return alpha.result.get("is", {}).get("sharpe", -100)


class FitnessScorer(ScorerBase):
    def get_name(self) -> str:
        return "fitness"

    def score(self, alpha) -> float:
        return alpha.result.get("is", {}).get("fitness", -100)
