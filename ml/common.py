"""Общие пути и чтение разметки для скриптов ml/."""

from __future__ import annotations

import csv
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CLASSES_YAML = REPO / "configs" / "classes.yaml"
ANNOTATIONS = REPO / "ml" / "annotations"
LABELS_DIR = ANNOTATIONS / "labels"
MANIFEST = ANNOTATIONS / "manifest.csv"

VIEWS = ["N", "E", "S", "W", "top_low", "top_high"]


def load_classes() -> list[dict]:
    """Классы из configs/classes.yaml, отсортированные по id без пропусков."""
    classes = yaml.safe_load(CLASSES_YAML.read_text(encoding="utf-8"))["classes"]
    classes.sort(key=lambda c: c["id"])
    if [c["id"] for c in classes] != list(range(len(classes))):
        raise ValueError(f"{CLASSES_YAML}: id классов должны идти подряд с 0")
    return classes


def read_manifest() -> list[dict]:
    with MANIFEST.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_manifest(rows: list[dict]) -> None:
    with MANIFEST.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def label_path(image: str) -> Path:
    """dataset/4/DJI_x.JPG -> ml/annotations/labels/4/DJI_x.txt"""
    p = Path(image)
    return LABELS_DIR / p.parent.name / f"{p.stem}.txt"


def read_labels(image: str) -> list[tuple[int, float, float, float, float]]:
    """Рамки YOLO: (class_id, cx, cy, w, h), координаты в долях кадра."""
    path = label_path(image)
    if not path.exists():
        return []
    boxes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c, *xywh = line.split()
            boxes.append((int(c), *map(float, xywh)))
    return boxes


def write_labels(image: str, boxes: list[tuple[int, float, float, float, float]]) -> None:
    path = label_path(image)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for c, cx, cy, w, h in boxes), encoding="utf-8")
