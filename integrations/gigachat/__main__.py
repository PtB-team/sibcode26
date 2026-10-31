import argparse
import json

from api.config import Settings
from integrations.gigachat import GigaChatClient, GigaChatError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check GigaChat authorization without printing tokens"
    )
    parser.add_argument(
        "--check", action="store_true", required=True, help="Request available model IDs"
    )
    parser.parse_args()
    settings = Settings.from_env()
    status = settings.gigachat.public_status(settings.mock)
    if not status["network_allowed"]:
        print(
            json.dumps(
                {
                    **status,
                    "ok": False,
                    "message": "Set MOCK=0, GIGACHAT_ENABLED=1 and GIGACHAT_CREDENTIALS",
                }
            )
        )
        return 2
    client = None
    try:
        client = GigaChatClient(settings.gigachat)
        models = client.models()
        print(
            json.dumps(
                {
                    "ok": True,
                    "models": models,
                    "selected_model_available": settings.gigachat.model in models,
                }
            )
        )
        return 0 if settings.gigachat.model in models else 1
    except GigaChatError as error:
        print(
            json.dumps(
                {"ok": False, "code": error.code, "message": error.message}, ensure_ascii=True
            )
        )
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
