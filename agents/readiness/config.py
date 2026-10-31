from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from schemas.material import Contract, Score
from schemas.readiness import DetectorClass, Stage

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"
ViewGroup = Literal["facade", "top_low", "top_high"]


class Label(Contract):
    id: str | int
    label: str


class ClassConfig(Contract):
    id: DetectorClass
    label: str
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    views: list[ViewGroup] = Field(min_length=1)


class ClassesConfig(Contract):
    version: str
    views: list[Label]
    top_high_min_relative_altitude_m: float | None = None
    facade_side_tolerance_deg: float | None = Field(default=None, gt=0, lt=45)
    classes: list[ClassConfig]

    @model_validator(mode="after")
    def validate_classes(self) -> "ClassesConfig":
        if [item.id for item in self.classes] != list(DetectorClass):
            raise ValueError("classes.yaml должен перечислять все классы детектора по порядку")
        return self

    def allowed(self, cls: str) -> set[str]:
        return next(set(item.views) for item in self.classes if item.id == cls)


class Weights(Contract):
    site_prep: int
    foundation: int
    walls: int
    roof: int
    windows: int
    door: int
    facade: int
    done: int

    @model_validator(mode="after")
    def validate_total(self) -> "Weights":
        if sum(self.model_dump().values()) - self.site_prep != 100:
            raise ValueError("Вклады этапов без site_prep должны давать 100")
        return self


class QualityConfig(Contract):
    working_size: int = Field(ge=256)
    blur_min_laplacian_var: float = Field(ge=0)
    max_clipped_share: Score


class StagesConfig(Contract):
    version: str
    present_threshold: Score
    low_confidence: Score
    min_facades: int = Field(ge=1, le=4)
    done_windows_ratio: Score
    parcel_buffer_m: float = Field(ge=0)
    quality: QualityConfig
    weights: Weights
    stages: list[Label]
    bank_readiness: list[Label]
    reshoot_reasons: dict[str, str]

    @model_validator(mode="after")
    def validate_stages(self) -> "StagesConfig":
        if [item.id for item in self.stages] != list(Stage):
            raise ValueError("stages.yaml должен перечислять все стадии по порядку")
        return self

    def stage_label(self, stage: Stage) -> str:
        return next(item.label for item in self.stages if item.id == stage)


def _load(name: str) -> dict:
    with (CONFIG_DIR / name).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


@lru_cache
def classes_config() -> ClassesConfig:
    return ClassesConfig.model_validate(_load("classes.yaml"))


@lru_cache
def stages_config() -> StagesConfig:
    return StagesConfig.model_validate(_load("stages.yaml"))

