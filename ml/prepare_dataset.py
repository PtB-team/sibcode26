"""Сборка датасета YOLO из dataset/ и ml/annotations/ с делением train/val по объектам.

    python ml/prepare_dataset.py                       # val = объекты 6 и 13
    python ml/prepare_dataset.py --val-objects 7,10    # другой состав val
    python ml/prepare_dataset.py --exclude-objects 12  # без объекта 12 (супермаркет)

Снимки одного дома не попадают в обе выборки (BACKEND.md, раздел 3.7).
Результат — data/yolo/{images,labels}/{train,val} и data/yolo/data.yaml; папка генерируется заново.
"""

from __future__ import annotations

import argparse
import os
import shutil
from collections import Counter
from pathlib import Path

import yaml

from common import REPO, label_path, load_classes, read_labels, read_manifest

OUT_DIR = REPO / "data" / "yolo"
DEFAULT_VAL_OBJECTS = "6,13"


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)  # жёсткая ссылка: без копии 600 МБ снимков
    except OSError:
        shutil.copy2(src, dst)


def build(val_objects: set[str], exclude_objects: set[str] = frozenset(), out: Path = OUT_DIR) -> Path:
    """Собирает датасет и возвращает путь к data.yaml."""
    names = [c["name"] for c in load_classes()]
    rows = [r for r in read_manifest() if r["object"] not in exclude_objects]
    unknown = val_objects - {r["object"] for r in rows}
    if unknown:
        raise ValueError(f"объектов {sorted(unknown)} нет в manifest.csv (или они исключены)")

    for split in ("train", "val"):
        for kind in ("images", "labels"):
            shutil.rmtree(out / kind / split, ignore_errors=True)
            (out / kind / split).mkdir(parents=True)

    stats = {"train": Counter(), "val": Counter()}
    images = Counter()
    for row in rows:
        split = "val" if row["object"] in val_objects else "train"
        src = REPO / row["image"]
        name = f"{row['object']}_{src.stem}"
        _link_or_copy(src, out / "images" / split / f"{name}{src.suffix}")
        if label_path(row["image"]).exists():
            shutil.copyfile(label_path(row["image"]), out / "labels" / split / f"{name}.txt")
        stats[split].update(names[c] for c, *_ in read_labels(row["image"]))
        images[split] += 1

    data_yaml = out / "data.yaml"
    data_yaml.write_text(
        yaml.safe_dump(
            {"path": str(out), "train": "images/train", "val": "images/val", "names": dict(enumerate(names))},
            allow_unicode=True, sort_keys=False,
        ),
        encoding="utf-8",
    )

    train_objects = sorted({r["object"] for r in rows} - val_objects, key=int)
    print(f"train: {images['train']} снимков, объекты {', '.join(train_objects)}")
    print(f"val:   {images['val']} снимков, объекты {', '.join(sorted(val_objects, key=int))}")
    print(f"{'класс':<18}{'train':>7}{'val':>7}")
    for n in names:
        mark = "  <- нет примеров в train" if not stats["train"][n] else ""
        print(f"{n:<18}{stats['train'][n]:>7}{stats['val'][n]:>7}{mark}")
    print(data_yaml)
    return data_yaml


def parse_objects(value: str) -> set[str]:
    return {x.strip() for x in value.split(",") if x.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--val-objects", default=DEFAULT_VAL_OBJECTS, help="номера папок dataset/ для val через запятую")
    parser.add_argument("--exclude-objects", default="", help="номера папок, которые не берём вовсе")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    build(parse_objects(args.val_objects), parse_objects(args.exclude_objects), args.out)


if __name__ == "__main__":
    main()
