from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class WallMaterial(StrEnum):
    BRICK = "brick"
    AERATED_CONCRETE = "aerated_concrete"
    CERAMIC_BLOCK = "ceramic_block"
    TIMBER = "timber"
    FRAME = "frame"
    SIP = "sip"
    MONOLITH = "monolith"


class View(StrEnum):
    NORTH = "N"
    EAST = "E"
    SOUTH = "S"
    WEST = "W"
    TOP_LOW = "top_low"
    TOP_HIGH = "top_high"


MATERIALS = {
    "brick": ("Кирпич", "stone"),
    "aerated_concrete": ("Газобетон / пеноблок", "blocks"),
    "ceramic_block": ("Керамический блок", "blocks"),
    "timber": ("Брус / бревно", "wood"),
    "frame": ("Каркас", "wood"),
    "sip": ("СИП-панели", "wood"),
    "monolith": ("Монолит", "concrete"),
}
FACADES = {View.NORTH, View.EAST, View.SOUTH, View.WEST}
TOP_VIEWS = {View.TOP_LOW, View.TOP_HIGH}
Score = Annotated[float, Field(ge=0, le=1)]
BBox = tuple[Score, Score, Score, Score]


class Project(Contract):
    wall_material: WallMaterial | None = None


class ObjectCreate(Contract):
    address: str = Field(min_length=1, max_length=500)
    cadastral: str | None = Field(default=None, max_length=100)
    project: Project | None = None
    notes: str = Field(default="", max_length=4000)


class ImageMeta(Contract):
    gps: (
        tuple[Annotated[float, Field(ge=-90, le=90)], Annotated[float, Field(ge=-180, le=180)]]
        | None
    ) = None


class Observation(Contract):
    """What the ML adapter observed in one wall area; no bank decisions here."""

    image_id: str
    visibility: Literal["visible", "hidden", "no_walls", "unclear"]
    material: WallMaterial | None = None
    confidence: Score = 0
    crop_bbox: BBox | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> "Observation":
        if self.visibility == "visible":
            if self.material is None or self.crop_bbox is None:
                raise ValueError("Для видимой стены нужны материал и рамка")
        elif self.material is not None:
            raise ValueError("Скрытой или отсутствующей стене нельзя назначать материал")
        if self.crop_bbox:
            x1, y1, x2, y2 = self.crop_bbox
            if x2 <= x1 or y2 <= y1:
                raise ValueError("Рамка должна иметь положительную ширину и высоту")
        return self


class ViewObservation(Observation):
    view: View | None = None
    included: bool = False
    exclusion_reason: str | None = None
    crop_url: str | None = None


class MaterialResult(Contract):
    agent: Literal["material"] = "material"
    model: str
    is_demo: bool
    status: Literal[
        "determined",
        "hidden",
        "no_walls",
        "insufficient_data",
        "mixed",
        "needs_review",
        "model_unavailable",
    ]
    material: WallMaterial | Literal["hidden", "unclear"] = "unclear"
    material_label: str = "Не удалось определить"
    group: str | None = None
    confidence: Score = 0
    mixed: bool = False
    votes: dict[str, float] = Field(default_factory=dict)
    per_view: list[ViewObservation] = Field(default_factory=list)
    project_material: WallMaterial | None = None
    match: Literal["match", "deviation", "mismatch", "unclear", "no_project"]
    fixed_on_object: bool = False
    explanation: str
    needs_reshoot: bool = False
    review_reasons: list[str] = Field(default_factory=list)


class MaterialReview(Contract):
    action: Literal["accept", "correct"]
    material: WallMaterial | None = None
    comment: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_correction(self) -> "MaterialReview":
        if self.action == "correct" and (self.material is None or not self.comment.strip()):
            raise ValueError("Для исправления укажите материал и комментарий")
        if self.action == "accept" and self.material is not None:
            raise ValueError("При принятии материал берётся из результата модели")
        return self


def utc_now() -> str:
    from datetime import timezone

    return datetime.now(timezone.utc).isoformat()
