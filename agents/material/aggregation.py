from collections import defaultdict

from schemas.material import (
    FACADES,
    MATERIALS,
    TOP_VIEWS,
    MaterialResult,
    View,
    ViewObservation,
    WallMaterial,
)


def aggregate(
    observations: list[ViewObservation],
    images: list[dict],
    *,
    model: str,
    is_demo: bool,
    project_material: str | None,
    target_confirmed: bool,
) -> MaterialResult:
    """Combine wall evidence, keeping unavailable or conflicting results explicit."""
    image_by_id = {image["id"]: image for image in images}
    # One facade cannot get extra votes just because it was photographed more often.
    strongest: dict[tuple[str, str], tuple[float, float]] = {}
    facades: dict[str, set[str]] = defaultdict(set)
    non_top = []
    for observation in observations:
        image = image_by_id[observation.image_id]
        observation.view = View(image["view"]) if image["view"] else None
        if image["is_overhead"] or image["view"] in TOP_VIEWS:
            observation.exclusion_reason = "TOP_VIEW"
            continue
        non_top.append(observation)
        if observation.visibility != "visible":
            observation.exclusion_reason = observation.visibility.upper()
            continue
        if observation.confidence < 0.6:
            observation.exclusion_reason = "LOW_CONFIDENCE"
            continue
        observation.included = True
        material = str(observation.material)
        x1, y1, x2, y2 = observation.crop_bbox
        weight = observation.confidence * (x2 - x1) * (y2 - y1)
        facade = image["view"] if image["view"] in FACADES else image["sha256"]
        key = (facade, material)
        if weight > strongest.get(key, (0.0, 0.0))[0]:
            strongest[key] = (weight, observation.confidence)
        if image["view"] in FACADES:
            facades[material].add(image["view"])

    result = MaterialResult(
        model=model,
        is_demo=is_demo,
        status="insufficient_data",
        project_material=project_material,
        match="no_project" if project_material is None else "unclear",
        per_view=observations,
        explanation="Недостаточно данных для определения материала.",
    )
    if is_demo:
        result.status = "model_unavailable"
        result.explanation = (
            "Деморежим: снимки сохранены и подготовлены, обученная модель не подключена. "
            "Материал по фотографии пока не определялся."
        )
        return result

    if not strongest:
        visibility = {row.visibility for row in non_top}
        if visibility == {"no_walls"}:
            result.status = "no_walls"
            result.explanation = (
                "На доступных ракурсах модель не обнаружила стен для оценки материала."
            )
        elif visibility == {"hidden"}:
            result.status, result.material = "hidden", "hidden"
            result.material_label = "Скрыт отделкой"
            result.explanation = "Материал стены закрыт отделкой или мембраной."
        else:
            result.needs_reshoot = True
            result.review_reasons = ["NO_RELIABLE_WALL_VIEWS"]
        return result

    weights: dict[str, float] = defaultdict(float)
    confidence_sum: dict[str, float] = defaultdict(float)
    for (_, material), (weight, confidence) in strongest.items():
        weights[material] += weight
        confidence_sum[material] += weight * confidence
    total = sum(weights.values())
    ranking = sorted(weights, key=lambda key: (-weights[key], key))
    winner = ranking[0]
    result.votes = {material: round(weight / total, 6) for material, weight in weights.items()}
    mean_confidence = confidence_sum[winner] / weights[winner]
    result.confidence = round(min(weights[winner] / total, mean_confidence), 6)
    result.material = WallMaterial(winner)
    result.material_label, result.group = MATERIALS[winner]
    result.mixed = len(ranking) > 1 and weights[ranking[1]] / total >= 0.35
    if result.mixed:
        result.status = "mixed"
        result.review_reasons.append("CONFLICTING_MATERIALS")
    else:
        result.status = "determined"
    if len(facades[winner]) < 2:
        result.review_reasons.append("FEW_CONFIRMED_FACADES")
    if result.confidence < 0.8:
        result.review_reasons.append("LOW_CONFIDENCE")
    if not target_confirmed:
        result.review_reasons.append("TARGET_NOT_CONFIRMED")
    if result.review_reasons and not result.mixed:
        result.status = "needs_review"
    result.fixed_on_object = result.status == "determined"
    result.explanation = (
        f"Предполагаемый материал: {result.material_label}. "
        f"Подтверждённых фасадов: {len(facades[winner])}. "
        + (
            "Требуется проверка сотрудником."
            if result.review_reasons
            else "Материал согласуется на нескольких ракурсах."
        )
    )
    if project_material is not None and result.status == "determined":
        if winner == project_material:
            result.match = "match"
        elif MATERIALS[winner][1] == MATERIALS[project_material][1]:
            result.match = "deviation"
        else:
            result.match = "mismatch"
    return result
