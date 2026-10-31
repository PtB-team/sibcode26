"""Manual image regions select a building; they do not prove cadastral identity."""


def overlap_fraction(box: tuple, region: tuple) -> float:
    x1, y1, x2, y2 = box
    a1, b1, a2, b2 = region
    area = (x2 - x1) * (y2 - y1)
    intersection = max(0, min(x2, a2) - max(x1, a1)) * max(0, min(y2, b2) - max(y1, b1))
    return intersection / area if area > 0 else 0.0


def exclusion_reason(box: tuple, image: dict) -> str | None:
    if image.get("target_bbox") is not None:
        # Conservatively discard detections crossing the selected boundary.
        return None if overlap_fraction(box, image["target_bbox"]) >= 0.9 else "OUTSIDE_TARGET"
    return None
