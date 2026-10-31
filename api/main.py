import json
from contextlib import asynccontextmanager
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from agents.readiness.config import classes_config, stages_config
from agents.readiness.views import assign_facade_sides, overhead_view
from api.config import Settings
from api.database import Database
from api.errors import ServiceError
from api.images import inspect_image
from schemas.material import (
    MATERIALS,
    TOP_VIEWS,
    ImageMeta,
    MaterialReview,
    ObjectCreate,
    View,
    utc_now,
)
from schemas.readiness import ReadinessReview


def parse_list(raw: str | None, count: int, name: str) -> list:
    if raw is None:
        return [None] * count
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ServiceError(
            400, "VALIDATION_ERROR", f"Поле {name} должно содержать JSON-массив"
        ) from exc
    if not isinstance(values, list) or len(values) != count:
        raise ServiceError(400, "VIEWS_MISMATCH", f"Длина {name} должна совпадать с числом файлов")
    return values


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        yield

    app = FastAPI(
        title="Мониторинг ИЖС: стадия строительства и материал стен",
        version="0.2.0",
        lifespan=lifespan,
        description=(
            "Загрузка снимков, стадия строительства и материал стен. "
            "В деморежиме обученные модели не вызываются."
        ),
    )
    app.state.settings = settings
    app.state.database = database
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(ServiceError)
    async def service_error(request, exc: ServiceError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": {},
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Проверьте поля запроса",
                    "details": {
                        "errors": [
                            {"loc": list(error["loc"]), "message": error["msg"]}
                            for error in exc.errors()
                        ]
                    },
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
                    "message": "Ресурс не найден" if exc.status_code == 404 else str(exc.detail),
                    "details": {},
                }
            },
        )

    prefix = "/api/v1"

    @app.get(prefix + "/health", tags=["Служебные"])
    def health():
        return {"status": "ok", "scope": "wall_material", "mock": settings.mock}

    @app.get(prefix + "/meta", tags=["Служебные"])
    def metadata():
        classes, stages = classes_config(), stages_config()
        return {
            "scope": "wall_material",
            "mock": settings.mock,
            "model_version": "demo-unavailable@v1" if settings.mock else "external-adapter",
            "material_model_version": "demo-unavailable@v1"
            if settings.mock
            else "external-adapter",
            "rules_version": stages.version,
            "materials": [
                {"id": key, "label": value[0], "group": value[1]}
                for key, value in MATERIALS.items()
            ],
            "views": [item.model_dump() for item in classes.views],
            "stages": [
                {**item.model_dump(), "order": order} for order, item in enumerate(stages.stages)
            ],
            "bank_readiness": [item.model_dump() for item in stages.bank_readiness],
            "classes": [
                {"id": item.id, "label": item.label, "color": item.color}
                for item in classes.classes
            ],
            "reshoot_reasons": [
                {"id": key, "label": value} for key, value in stages.reshoot_reasons.items()
            ],
        }

    @app.post(prefix + "/objects", status_code=201, tags=["Объекты"])
    def create_object(body: ObjectCreate):
        return database.create_object(body.model_dump(mode="json"))

    @app.get(prefix + "/objects", tags=["Объекты"])
    def list_objects(
        page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20
    ):
        return {
            **database.objects(page_size, (page - 1) * page_size),
            "page": page,
            "page_size": page_size,
        }

    @app.get(prefix + "/objects/{object_id}", tags=["Объекты"])
    def get_object(object_id: str):
        value = database.object(object_id)
        flights = database.flights(object_id)
        return {
            **value,
            "data_status": data_status(flights),
            "last_flight": flights[0] if flights else None,
        }

    @app.post(prefix + "/objects/{object_id}/flights", status_code=202, tags=["Облёты"])
    def upload_flight(
        object_id: str,
        files: Annotated[list[UploadFile], File()],
        views: Annotated[str | None, Form()] = None,
        meta: Annotated[str | None, Form()] = None,
        flown_at: Annotated[str | None, Form()] = None,
        target_confirmed: Annotated[bool, Form()] = False,
    ):
        directory: Path | None = None
        committed = False
        try:
            database.object(object_id)
            if not 1 <= len(files) <= settings.max_files:
                raise ServiceError(400, "VALIDATION_ERROR", "Нужно от 1 до 20 снимков")
            view_values = parse_list(views, len(files), "views")
            meta_values = parse_list(meta, len(files), "meta")
            try:
                parsed_views = [View(value) if value is not None else None for value in view_values]
                parsed_meta = [
                    ImageMeta.model_validate({} if value is None else value)
                    for value in meta_values
                ]
                timestamp = datetime.fromisoformat(flown_at) if flown_at else None
                if timestamp is not None and timestamp.utcoffset() is None:
                    raise ValueError("Нет часового пояса")
            except (ValueError, TypeError, ValidationError) as exc:
                raise ServiceError(
                    400, "VALIDATION_ERROR", "Проверьте ракурсы, GPS и дату облёта с часовым поясом"
                ) from exc

            flight_id = "fl_" + uuid4().hex
            directory = settings.storage_dir / "flights" / flight_id
            directory.mkdir(parents=True)
            images = []
            hashes = set()
            for incoming, view, manual_meta in zip(files, parsed_views, parsed_meta):
                image_id = "img_" + uuid4().hex
                path = directory / f"{image_id}.upload"
                digest, size = sha256(), 0
                with path.open("xb") as destination:
                    while chunk := incoming.file.read(1024 * 1024):
                        size += len(chunk)
                        if size > settings.max_file_bytes:
                            raise ServiceError(
                                413, "FILE_TOO_LARGE", "Снимок превышает лимит 30 МБ"
                            )
                        destination.write(chunk)
                        digest.update(chunk)
                metadata = inspect_image(path, settings)
                fingerprint = digest.hexdigest()
                if fingerprint in hashes:
                    raise ServiceError(
                        400, "DUPLICATE_IMAGE", "В одном облёте передан один и тот же снимок дважды"
                    )
                hashes.add(fingerprint)
                if not metadata["has_exif"] and view is None:
                    raise ServiceError(
                        400, "VIEWS_REQUIRED", "Без EXIF укажите ракурс снимка в views"
                    )
                if view is not None:
                    metadata.update(view=view.value, view_source="manual")
                elif metadata["is_overhead"] and (
                    role := overhead_view(metadata["relative_altitude"])
                ):
                    metadata.update(view=role, view_source="exif")
                if view in TOP_VIEWS:
                    metadata["is_overhead"] = True
                if manual_meta.gps is not None:
                    metadata.update(gps=list(manual_meta.gps), gps_source="meta")
                suffix = ".jpg" if metadata["format"] == "JPEG" else ".png"
                stored = directory / f"{image_id}{suffix}"
                path.rename(stored)
                images.append(
                    {
                        **metadata,
                        "id": image_id,
                        "flight_id": flight_id,
                        "filename": (incoming.filename or "image")
                        .replace("\\", "/")
                        .split("/")[-1],
                        "storage_name": stored.name,
                        "size_bytes": size,
                        "sha256": fingerprint,
                        "url": f"{prefix}/images/{image_id}/file",
                        "thumb_url": f"{prefix}/images/{image_id}/thumb",
                        "technical_ok": True,
                        "quality_ok": None,
                    }
                )
            assign_facade_sides(images)
            dates = [image["taken_at"] for image in images if image["taken_at"]]
            database.enqueue(
                {
                    "id": flight_id,
                    "object_id": object_id,
                    "flown_at": timestamp.isoformat()
                    if timestamp
                    else min(dates, key=datetime.fromisoformat, default=None),
                    "target_confirmed": target_confirmed,
                    "is_demo": settings.mock,
                },
                images,
            )
            committed = True
            return {"flight_id": flight_id, "status": "queued", "mock": settings.mock}
        finally:
            for incoming in files:
                incoming.file.close()
            if directory is not None and not committed:
                # Only this request's generated files are removed, never user source images.
                for generated in directory.iterdir():
                    generated.unlink()
                directory.rmdir()

    @app.get(prefix + "/objects/{object_id}/flights", tags=["Облёты"])
    def list_flights(object_id: str):
        return database.flights(object_id)

    @app.get(prefix + "/flights/{flight_id}", tags=["Облёты"])
    def get_flight(flight_id: str):
        return database.flight(flight_id)

    @app.get(prefix + "/flights/{flight_id}/images", tags=["Снимки"])
    def get_images(flight_id: str):
        detections = database.detections(flight_id)
        return [
            {
                **{key: value for key, value in image.items() if key != "storage_name"},
                "detections": detections.get(image["id"], []),
            }
            for image in database.images(flight_id)
        ]

    def image_path(image_id: str, kind: str) -> tuple[dict, Path]:
        image = database.image(image_id)
        name = image["storage_name"] if kind == "file" else f"{image_id}.thumb.jpg"
        path = settings.storage_dir / "flights" / image["flight_id"] / name
        if not path.is_file():
            raise ServiceError(409, "PREVIEW_NOT_READY", "Превью появится после обработки снимка")
        return image, path

    @app.get(prefix + "/images/{image_id}/file", tags=["Снимки"])
    def get_original(image_id: str):
        image, path = image_path(image_id, "file")
        return FileResponse(
            path,
            filename=image["filename"],
            media_type=("image/jpeg" if image["format"] == "JPEG" else "image/png"),
        )

    @app.get(prefix + "/images/{image_id}/thumb", tags=["Снимки"])
    def get_thumbnail(image_id: str):
        _, path = image_path(image_id, "thumb")
        return FileResponse(path, media_type="image/jpeg")

    @app.get(prefix + "/images/{image_id}/crops/{crop_index}", tags=["Снимки"])
    def get_crop(
        image_id: str,
        crop_index: int,
        revision: Annotated[str, Query(pattern=r"^[0-9a-f]{32}$")],
    ):
        image = database.image(image_id)
        path = (
            settings.storage_dir
            / "flights"
            / image["flight_id"]
            / f"{image_id}.crop.{revision}.{crop_index}.jpg"
        )
        if crop_index < 0 or not path.is_file():
            raise ServiceError(404, "NOT_FOUND", "Участок стены не найден")
        return FileResponse(path, media_type="image/jpeg")

    @app.post(prefix + "/flights/{flight_id}/material/review", status_code=201, tags=["Проверка"])
    def review_material(
        flight_id: str,
        body: MaterialReview,
        x_user: Annotated[str, Header(max_length=100)] = "demo",
    ):
        flight = database.flight(flight_id)
        if flight["status"] != "done":
            raise ServiceError(409, "FLIGHT_NOT_READY", "Дождитесь окончания обработки")
        result = flight["material_result"]
        material = body.material
        if body.action == "accept":
            if result["is_demo"] or result["material"] not in MATERIALS:
                raise ServiceError(
                    409, "MATERIAL_NOT_DETERMINED", "Нет результата модели, который можно принять"
                )
            material = result["material"]
        return database.add_review(
            flight_id,
            jsonable_encoder(
                {
                    **body.model_dump(),
                    "material": material,
                    "author": x_user,
                    "created_at": utc_now(),
                    "source": "employee",
                }
            ),
        )

    @app.post(prefix + "/flights/{flight_id}/review", status_code=201, tags=["Проверка"])
    def review_readiness(
        flight_id: str,
        body: ReadinessReview,
        x_user: Annotated[str, Header(max_length=100)] = "demo",
    ):
        flight = database.flight(flight_id)
        if flight["status"] != "done":
            raise ServiceError(409, "FLIGHT_NOT_READY", "Дождитесь окончания обработки")
        values = body.model_dump(mode="json", exclude={"action", "comment"})
        if body.action == "accept":
            result = flight["result"]
            if result is None or result["is_demo"] or result["stage"] is None:
                raise ServiceError(
                    409, "STAGE_NOT_DETERMINED", "Нет результата модели, который можно принять"
                )
            values = {key: result[key] for key in ("stage", "readiness_pct", "bank_readiness")}
        return database.add_readiness_review(
            flight_id,
            {
                "action": body.action,
                **values,
                "comment": body.comment,
                "author": x_user,
                "created_at": utc_now(),
                "source": "employee",
            },
        )

    return app


def data_status(flights: list[dict]) -> str:
    """Whether the latest usable flight can be trusted (API.md, section 6.1)."""
    latest = next((flight for flight in flights if flight["status"] != "failed"), None)
    if latest is None:
        return "no_data"
    if latest["status"] in {"queued", "processing"}:
        return "processing"
    result = latest["result"]
    if result is None or result["status"] == "model_unavailable":
        return "no_data"
    if latest["readiness_review"] is not None:
        return "ok"
    return {"needs_reshoot": "reshoot", "needs_review": "review"}.get(result["status"], "ok")


app = create_app()
