import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from api.errors import ServiceError
from api.presentation import (
    fixed_material_response,
    material_data_status,
    material_result_response,
)
from schemas.material import utc_now


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class Database:
    """SQLite stores both records and the durable processing queue."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS objects (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL, material TEXT
                );
                CREATE TABLE IF NOT EXISTS flights (
                    id TEXT PRIMARY KEY, object_id TEXT NOT NULL REFERENCES objects(id),
                    status TEXT NOT NULL, uploaded_at TEXT NOT NULL, flown_at TEXT,
                    target_confirmed INTEGER NOT NULL, is_demo INTEGER NOT NULL,
                    result TEXT, error TEXT, lease_token TEXT, lease_until REAL,
                    attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS flights_queue ON flights(status, uploaded_at);
                CREATE INDEX IF NOT EXISTS flights_object_uploaded
                    ON flights(object_id, uploaded_at DESC);
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, flight_id TEXT NOT NULL REFERENCES flights(id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS material_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    flight_id TEXT NOT NULL REFERENCES flights(id), payload TEXT NOT NULL
                );
            """)

    def create_object(self, payload: dict) -> dict:
        object_id, created_at = "obj_" + uuid4().hex, utc_now()
        with self.connection() as db:
            db.execute(
                "INSERT INTO objects(id,payload,created_at) VALUES (?,?,?)",
                (object_id, encode(payload), created_at),
            )
        return self.object(object_id)

    def object(self, object_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
            latest = db.execute(
                "SELECT id FROM flights WHERE object_id=? "
                "ORDER BY uploaded_at DESC, rowid DESC LIMIT 1",
                (object_id,),
            ).fetchone()
        if row is None:
            raise ServiceError(404, "NOT_FOUND", "Объект не найден")
        payload = json.loads(row["payload"])
        project_material = (payload.get("project") or {}).get("wall_material")
        material = json.loads(row["material"]) if row["material"] else None
        last_flight = self.flight(latest["id"]) if latest else None
        result = last_flight["material_result"] if last_flight else None
        return {
            **payload,
            "id": row["id"],
            "created_at": row["created_at"],
            "material": fixed_material_response(material, project_material),
            "last_flight": last_flight,
            "last_flight_id": last_flight["flight_id"] if last_flight else None,
            "last_flight_at": last_flight["flown_at"] if last_flight else None,
            "material_status": result["status"] if result else None,
            "data_status": material_data_status(last_flight),
        }

    def objects(self, limit: int, offset: int) -> dict:
        with self.connection() as db:
            ids = db.execute(
                "SELECT id FROM objects ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            total = db.execute("SELECT count(*) FROM objects").fetchone()[0]
        return {"items": [self.object(row["id"]) for row in ids], "total": total}

    def enqueue(self, flight: dict, images: list[dict]) -> None:
        with self.connection() as db:
            db.execute(
                """INSERT INTO flights
                (id,object_id,status,uploaded_at,flown_at,target_confirmed,is_demo)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    flight["id"],
                    flight["object_id"],
                    "queued",
                    utc_now(),
                    flight["flown_at"],
                    flight["target_confirmed"],
                    flight["is_demo"],
                ),
            )
            db.executemany(
                "INSERT INTO images(id,flight_id,payload) VALUES (?,?,?)",
                [(image["id"], flight["id"], encode(image)) for image in images],
            )

    def flight(self, flight_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM flights WHERE id=?", (flight_id,)).fetchone()
            count = db.execute(
                "SELECT count(*) FROM images WHERE flight_id=?", (flight_id,)
            ).fetchone()[0]
            review = db.execute(
                "SELECT payload FROM material_reviews WHERE flight_id=? ORDER BY id DESC LIMIT 1",
                (flight_id,),
            ).fetchone()
        if row is None:
            raise ServiceError(404, "NOT_FOUND", "Облёт не найден")
        return {
            "flight_id": row["id"],
            "object_id": row["object_id"],
            "status": row["status"],
            "uploaded_at": row["uploaded_at"],
            "flown_at": row["flown_at"],
            "target_confirmed": bool(row["target_confirmed"]),
            "mock": bool(row["is_demo"]),
            "images_count": count,
            "result": None,
            "land_result": None,
            "material_result": material_result_response(
                json.loads(row["result"]) if row["result"] else None
            ),
            "error": json.loads(row["error"]) if row["error"] else None,
            "review": json.loads(review["payload"]) if review else None,
        }

    def flights(self, object_id: str) -> list[dict]:
        self.object(object_id)
        with self.connection() as db:
            ids = db.execute(
                "SELECT id FROM flights WHERE object_id=? ORDER BY uploaded_at DESC, rowid DESC",
                (object_id,),
            ).fetchall()
        return [self.flight(row["id"]) for row in ids]

    def images(self, flight_id: str) -> list[dict]:
        self.flight(flight_id)
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM images WHERE flight_id=? ORDER BY rowid", (flight_id,)
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def image(self, image_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM images WHERE id=?", (image_id,)).fetchone()
        if row is None:
            raise ServiceError(404, "NOT_FOUND", "Снимок не найден")
        return json.loads(row["payload"])

    def claim(self, lease_seconds: int) -> tuple[str, str] | None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            expired = "status='processing' AND lease_until < ?"
            db.execute(
                f"UPDATE flights SET status='failed',error=? WHERE {expired} AND attempts>=3",
                (
                    encode(
                        {"code": "WORKER_INTERRUPTED", "message": "Обработка прерывалась трижды"}
                    ),
                    time.time(),
                ),
            )
            row = db.execute(
                f"SELECT id FROM flights WHERE status='queued' OR ({expired}) "
                "ORDER BY uploaded_at LIMIT 1",
                (time.time(),),
            ).fetchone()
            if row is None:
                return None
            token = uuid4().hex
            db.execute(
                "UPDATE flights SET status='processing',lease_token=?,lease_until=?,"
                "attempts=attempts+1 WHERE id=?",
                (token, time.time() + lease_seconds, row["id"]),
            )
            return row["id"], token

    def renew(self, flight_id: str, token: str, lease_seconds: int) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE flights SET lease_until=? WHERE id=? AND lease_token=?",
                (time.time() + lease_seconds, flight_id, token),
            )

    def finish(
        self, flight_id: str, token: str, *, result: dict | None = None, error: dict | None = None
    ) -> bool:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute(
                "SELECT object_id FROM flights WHERE id=? AND "
                "status='processing' AND lease_token=?",
                (flight_id, token),
            ).fetchone()
            if job is None:
                return False
            if result and result["fixed_on_object"]:
                previous = db.execute(
                    "SELECT material FROM objects WHERE id=?", (job["object_id"],)
                ).fetchone()[0]
                if previous:
                    result = {**result, "fixed_on_object": False}
                    if json.loads(previous)["observed"] != result["material"]:
                        result.update(
                            status="needs_review",
                            match=(
                                "no_project" if result["project_material"] is None else "unclear"
                            ),
                        )
                        result["review_reasons"] = [
                            *result["review_reasons"],
                            "PREVIOUS_MATERIAL_CONFLICT",
                        ]
                        result["explanation"] += (
                            " Результат расходится с сохранённым материалом: нужна проверка."
                        )
            changed = db.execute(
                "UPDATE flights SET status=?,result=?,error=?,is_demo=COALESCE(?,is_demo),lease_until=NULL "
                "WHERE id=? AND status='processing' AND lease_token=?",
                (
                    "failed" if error else "done",
                    encode(result) if result else None,
                    encode(error) if error else None,
                    bool(result["is_demo"]) if result else None,
                    flight_id,
                    token,
                ),
            ).rowcount
            if changed and result and result["fixed_on_object"]:
                object_id = db.execute(
                    "SELECT object_id FROM flights WHERE id=?", (flight_id,)
                ).fetchone()[0]
                current = db.execute(
                    "SELECT material FROM objects WHERE id=?", (object_id,)
                ).fetchone()[0]
                if current is None:
                    db.execute(
                        "UPDATE objects SET material=? WHERE id=?",
                        (
                            encode(
                                {
                                    "observed": result["material"],
                                    "confidence": result["confidence"],
                                    "fixed_at_flight_id": flight_id,
                                    "reviewed": False,
                                }
                            ),
                            object_id,
                        ),
                    )
            return bool(changed)

    def add_review(self, flight_id: str, review: dict) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT object_id,status FROM flights WHERE id=?", (flight_id,)
            ).fetchone()
            if row is None:
                raise ServiceError(404, "NOT_FOUND", "Облёт не найден")
            if row["status"] != "done":
                raise ServiceError(409, "FLIGHT_NOT_READY", "Дождитесь окончания обработки")
            db.execute(
                "INSERT INTO material_reviews(flight_id,payload) VALUES (?,?)",
                (flight_id, encode(review)),
            )
            db.execute(
                "UPDATE objects SET material=? WHERE id=?",
                (
                    encode(
                        {
                            "observed": review["material"],
                            "confidence": None,
                            "fixed_at_flight_id": flight_id,
                            "reviewed": True,
                            "author": review["author"],
                            "comment": review["comment"],
                        }
                    ),
                    row["object_id"],
                ),
            )
        return review
