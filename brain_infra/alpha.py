import copy
import json
import os
import shutil
from enum import Enum


DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "db"))


class AlphaStage(Enum):
    NONE = "non_exist"
    PENDING = os.path.join(DB_PATH, "pending")
    COMPLETE = os.path.join(DB_PATH, "complete")
    ERROR = os.path.join(DB_PATH, "error")


def init_db() -> None:
    for stage in (AlphaStage.PENDING, AlphaStage.COMPLETE, AlphaStage.ERROR):
        os.makedirs(stage.value, exist_ok=True)


class Alpha:
    def __init__(
        self,
        name: str,
        payload: dict,
        alpha_stage: AlphaStage = AlphaStage.PENDING,
        result: dict = {},
    ) -> None:
        self._json = {
            "name": name,
            "payload": copy.deepcopy(payload),
            "stage": alpha_stage.value,
            "result": copy.deepcopy(result),
        }

    @property
    def name(self) -> str:
        return self._json["name"]

    @property
    def payload(self) -> dict:
        return self._json["payload"]

    @property
    def stage(self) -> AlphaStage:
        return AlphaStage(self._json["stage"])

    @property
    def result(self) -> dict:
        return self._json["result"]

    @property
    def filename(self) -> str:
        return f"{self.name}.json"

    @property
    def filepath(self) -> str:
        return os.path.join(self.stage.value, self.filename)

    @property
    def _tmp_filepath(self) -> str:
        return os.path.join(self.stage.value, f"tmp_{self.filename}")

    def dump(self) -> None:
        if self.stage is AlphaStage.NONE:
            raise ValueError("Cannot dump alpha with NONE stage.")
        os.makedirs(self.stage.value, exist_ok=True)
        with open(self._tmp_filepath, "w", encoding="utf-8") as handle:
            json.dump(self._json, handle, ensure_ascii=True, indent=2)
        shutil.move(self._tmp_filepath, self.filepath)

    @classmethod
    def load(cls, filepath: str) -> "Alpha":
        with open(filepath, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls(
            name=payload["name"],
            payload=payload["payload"],
            alpha_stage=AlphaStage(payload["stage"]),
            result=payload.get("result", {}),
        )

    def update_stage(self, new_stage: AlphaStage) -> None:
        if os.path.exists(self.filepath):
            os.remove(self.filepath)
        self._json["stage"] = new_stage.value
        self.dump()
