from schemas.material import compare_materials

MATERIAL_STATUSES = {
    "determined": "Материал определён",
    "hidden": "Скрыт отделкой",
    "no_walls": "Стен не обнаружено",
    "insufficient_data": "Недостаточно данных",
    "mixed": "Противоречивые материалы",
    "needs_review": "Нужна проверка",
    "model_unavailable": "Модель недоступна",
}


def material_result_response(result: dict | None) -> dict | None:
    """Add the shared API fields without changing stored ML observations."""
    if result is None:
        return None
    observations = []
    for observation in result.get("per_view", []):
        observations.append(
            {
                **observation,
                "class": observation.get("material")
                or ("hidden" if observation.get("visibility") == "hidden" else "unclear"),
                "conf": observation.get("confidence", 0),
            }
        )
    return {**result, "per_view": observations}


def fixed_material_response(material: dict | None, project_material: str | None) -> dict | None:
    if material is None:
        return None
    return {
        **material,
        "project": project_material,
        "match": compare_materials(material["observed"], project_material),
    }


def material_data_status(flight: dict | None) -> str:
    """Summarize material processing; this does not assess construction readiness."""
    if flight is None:
        return "no_data"
    if flight["status"] in {"queued", "processing"}:
        return "processing"
    if flight["status"] == "failed":
        return "review"
    if flight["review"] is not None:
        return "ok"
    result = flight["material_result"]
    if result is None or result["status"] == "model_unavailable":
        return "no_data"
    if result["status"] == "determined":
        return "ok"
    return "reshoot" if result.get("needs_reshoot") else "review"
