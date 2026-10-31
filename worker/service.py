import logging

from agents.material.aggregation import aggregate
from agents.material.model import MaterialPredictor, load_predictor
from agents.readiness import aggregation as readiness
from agents.readiness.model import Detector, load_detector
from agents.readiness.quality import quality_issues
from api.config import Settings
from api.database import Database
from api.images import load_oriented_image, save_crop, save_preview
from schemas.material import TOP_VIEWS, Observation, ViewObservation
from schemas.readiness import Detection

logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        settings: Settings,
        predictor: MaterialPredictor | None = None,
        detector: Detector | None = None,
    ) -> None:
        self.settings = settings
        self.database = Database(settings.database_path)
        self.database.initialize()
        # Load weights once for the process, not for every HTTP request or photograph.
        self.predictor = predictor if predictor is not None else load_predictor(settings)
        self.detector = detector if detector is not None else load_detector(settings)

    def process_one(self) -> bool:
        job = self.database.claim(self.settings.job_lease_seconds)
        if job is None:
            return False
        flight_id, token = job
        try:
            flight = self.database.flight(flight_id)
            object_data = self.database.object(flight["object_id"])
            images = self.database.images(flight_id)
            observations: list[ViewObservation] = []
            detections: list[Detection] = []
            for image_data in images:
                directory = self.settings.storage_dir / "flights" / flight_id
                with load_oriented_image(directory / image_data["storage_name"]) as image:
                    save_preview(image, directory / f"{image_data['id']}.thumb.jpg")
                    issues = quality_issues(image)
                    image_data.update(quality_ok=not issues, quality_issues=issues)
                    self.database.update_image(image_data)
                    # Construction elements are looked for on every view, overhead included.
                    for found in self.detector.detect(image, image_data["id"]):
                        detection = Detection.model_validate(found)
                        if detection.image_id != image_data["id"]:
                            raise ValueError("Детектор вернул результат для другого снимка")
                        detections.append(detection)
                    if image_data["is_overhead"] or image_data["view"] in TOP_VIEWS:
                        predictions = [Observation(image_id=image_data["id"], visibility="unclear")]
                    else:
                        predictions = self.predictor.predict(image, image_data["id"])
                    for index, prediction in enumerate(predictions):
                        observation = Observation.model_validate(prediction)
                        if observation.image_id != image_data["id"]:
                            raise ValueError("Адаптер вернул результат для другого снимка")
                        view = ViewObservation(**observation.model_dump())
                        if observation.crop_bbox is not None:
                            crop_name = f"{image_data['id']}.crop.{token}.{index}.jpg"
                            save_crop(image, observation.crop_bbox, directory / crop_name)
                            view.crop_url = (
                                f"/api/v1/images/{image_data['id']}/crops/{index}?revision={token}"
                            )
                        observations.append(view)
                self.database.renew(flight_id, token, self.settings.job_lease_seconds)
            project = object_data.get("project") or {}
            result = aggregate(
                observations,
                images,
                model=self.predictor.version,
                is_demo=self.predictor.is_demo,
                project_material=project.get("wall_material"),
                target_confirmed=flight["target_confirmed"],
            )
            stage = readiness.aggregate(
                detections,
                images,
                model=self.detector.version,
                is_demo=self.detector.is_demo,
                target_confirmed=flight["target_confirmed"],
                parcel=object_data.get("parcel_geojson"),
            )
            self.database.finish(
                flight_id,
                token,
                result=result.model_dump(mode="json"),
                readiness=stage.model_dump(mode="json"),
                detections=readiness.annotate(detections, images),
            )
            logger.info(
                "flight_done flight_id=%s model=%s detector=%s",
                flight_id,
                self.predictor.version,
                self.detector.version,
            )
        except Exception:
            logger.exception("flight_failed flight_id=%s", flight_id)
            self.database.finish(
                flight_id,
                token,
                error={
                    "code": "INFERENCE_FAILED",
                    "message": "Не удалось обработать снимки. Подробности сохранены в журнале воркера.",
                    "details": {},
                },
            )
        return True
