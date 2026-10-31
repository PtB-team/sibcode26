"""Classify original-resolution wall crops provided by the shared detector."""

import os
from pathlib import Path

from agents.targeting import overlap_fraction
from schemas.material import MATERIALS, Observation

WALLS = {"walls_partial", "walls_full"}


def padded_bbox(box: tuple) -> tuple:
    x1, y1, x2, y2 = box
    mx, my = (x2 - x1) * 0.1, (y2 - y1) * 0.1
    return max(0, x1 - mx), max(0, y1 - my), min(1, x2 + mx), min(1, y2 + my)


class YoloMaterialPredictor:
    is_demo = False

    def __init__(self, weights: Path):
        if not weights.is_file():
            raise ValueError("Укажите существующий локальный файл MATERIAL_WEIGHTS")
        from ultralytics import YOLO

        self.model = YOLO(str(weights))
        self.names = (
            dict(enumerate(self.model.names))
            if isinstance(self.model.names, list)
            else self.model.names
        )
        if not self.names or not set(self.names.values()) <= set(MATERIALS) | {"hidden", "unclear"}:
            raise ValueError("Неизвестные имена материалов в весах классификатора")
        if getattr(self.model, "task", "classify") != "classify":
            raise ValueError("MATERIAL_WEIGHTS должны содержать классификатор")
        self.version = "yolo-material:" + weights.name

    def predict_walls(self, image, image_id: str, detections: list) -> list[Observation]:
        walls = [row for row in detections if row.cls in WALLS and row.target_included]
        if not walls:
            return [Observation(image_id=image_id, visibility="no_walls")]
        width, height = image.size
        observations = []
        for wall in walls:
            crop_box = padded_bbox(wall.bbox)
            x1, y1, x2, y2 = crop_box
            with image.crop((x1 * width, y1 * height, x2 * width, y2 * height)) as crop:
                probs = self.model.predict(source=crop, imgsz=384, verbose=False)[0].probs
            if probs is None:
                raise ValueError("Классификатор не вернул вероятности материала")
            material = self.names[int(probs.top1)]
            confidence = float(probs.top1conf)
            reasons = []
            if material == "brick" and any(
                row.cls == "facade_finish"
                and row.target_included
                and row.conf >= 0.6
                and overlap_fraction(wall.bbox, row.bbox) >= 0.5
                for row in detections
            ):
                reasons.append("CLADDING_MAY_HIDE_STRUCTURE")
            observations.append(
                Observation(
                    image_id=image_id,
                    cls=wall.cls,
                    bbox=wall.bbox,
                    crop_bbox=crop_box,
                    detector_confidence=wall.conf,
                    material_conf=confidence,
                    confidence=confidence,
                    material=material,
                    visibility=material if material in {"hidden", "unclear"} else "visible",
                    review_reasons=reasons,
                )
            )
        return observations


def create_predictor() -> YoloMaterialPredictor:
    return YoloMaterialPredictor(Path(os.getenv("MATERIAL_WEIGHTS", "")))
