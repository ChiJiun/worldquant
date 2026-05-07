import os
import time
from typing import Dict, List, Tuple

from tqdm import tqdm

from brain_infra.alpha import Alpha, AlphaStage, init_db


class AlphaList:
    def __init__(self, alphas: List[Alpha], names: List[str]):
        self._alphas = alphas
        self._names = [alpha.filename for alpha in alphas]

    @staticmethod
    def check_alpha_stage(filename: str) -> AlphaStage:
        for stage in (AlphaStage.PENDING, AlphaStage.COMPLETE, AlphaStage.ERROR):
            if os.path.exists(os.path.join(stage.value, filename)):
                return stage
        return AlphaStage.NONE

    def update_and_check_status(self) -> Tuple[int, int, int, int]:
        counts = {
            AlphaStage.NONE: 0,
            AlphaStage.PENDING: 0,
            AlphaStage.COMPLETE: 0,
            AlphaStage.ERROR: 0,
        }
        for index, alpha in enumerate(self._alphas):
            stage = self.check_alpha_stage(alpha.filename)
            if stage != alpha.stage and stage is not AlphaStage.NONE:
                self._alphas[index] = Alpha.load(os.path.join(stage.value, alpha.filename))
                alpha = self._alphas[index]
            counts[stage] += 1
        return (
            counts[AlphaStage.NONE],
            counts[AlphaStage.PENDING],
            counts[AlphaStage.COMPLETE],
            counts[AlphaStage.ERROR],
        )

    def sim_and_wait(self) -> None:
        init_db()
        for alpha in self._alphas:
            if self.check_alpha_stage(alpha.filename) is AlphaStage.NONE:
                alpha.dump()

        progress = tqdm(total=len(self._alphas))
        last_finished = -1
        try:
            while True:
                _, _, complete_count, error_count = self.update_and_check_status()
                finished = complete_count + error_count
                if finished != last_finished:
                    progress.n = finished
                    progress.refresh()
                    last_finished = finished
                if finished == len(self._alphas):
                    break
                time.sleep(1)
        finally:
            progress.close()

    def get_alphas(self) -> Dict[str, Alpha]:
        self.update_and_check_status()
        return dict(zip(self._names, self._alphas))
