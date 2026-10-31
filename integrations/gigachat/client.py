import json
import math
import ssl
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from integrations.gigachat.config import GigaChatSettings


class GigaChatError(Exception):
    """Public errors never contain response bodies, credentials or access tokens."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class GigaChatClient:
    def __init__(
        self,
        settings: GigaChatSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        clock=time.time,
    ):
        self.settings = settings
        self._clock = clock
        self._token = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()
        self._credentials = settings.credentials.removeprefix("Basic ").strip()
        for url in (settings.base_url, settings.auth_url):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise GigaChatError(
                    "CONFIGURATION_ERROR", "Для GigaChat требуется корректный HTTPS-адрес"
                )
        if settings.scope not in {"GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"}:
            raise GigaChatError("CONFIGURATION_ERROR", "Неизвестный GIGACHAT_SCOPE")
        if not self._credentials or any(ch.isspace() for ch in self._credentials):
            raise GigaChatError(
                "CONFIGURATION_ERROR", "Задайте Authorization Key без префикса Basic"
            )
        if (
            not math.isfinite(settings.timeout_seconds)
            or not 1 <= settings.timeout_seconds <= 120
            or not 1 <= settings.max_tokens <= 4096
        ):
            raise GigaChatError(
                "CONFIGURATION_ERROR", "Проверьте тайм-аут и лимит токенов GigaChat"
            )
        try:
            context = ssl.create_default_context()
            if settings.ca_bundle is not None:
                context.load_verify_locations(cafile=settings.ca_bundle)
        except (OSError, ssl.SSLError):
            raise GigaChatError(
                "TLS_CONFIGURATION_ERROR", "Не удалось загрузить сертификат GIGACHAT_CA_BUNDLE"
            ) from None
        self._http = httpx.Client(
            verify=context,
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(settings.timeout_seconds, connect=10),
            headers={"Accept": "application/json", "User-Agent": "sibcode26-inspection/0.4"},
        )

    def close(self) -> None:
        self._http.close()
        self._token = ""

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, url, **kwargs)
        except httpx.TimeoutException:
            raise GigaChatError("TIMEOUT", "GigaChat не ответил вовремя") from None
        except httpx.TransportError:
            raise GigaChatError(
                "CONNECTION_ERROR", "Не удалось установить защищённое соединение с GigaChat"
            ) from None

    @staticmethod
    def _raise_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        code, message = {
            400: ("BAD_REQUEST", "GigaChat отклонил формат запроса"),
            401: ("AUTH_FAILED", "GigaChat отклонил учётные данные"),
            402: ("QUOTA_EXHAUSTED", "Недостаточно токенов выбранной модели GigaChat"),
            403: ("ACCESS_DENIED", "Нет доступа к GigaChat или выбранной модели"),
            429: ("RATE_LIMITED", "Превышен лимит запросов GigaChat"),
        }.get(response.status_code, ("UPSTREAM_ERROR", "GigaChat временно недоступен"))
        raise GigaChatError(code, message, response.status_code)

    @staticmethod
    def _json(response: httpx.Response):
        try:
            return response.json()
        except (ValueError, UnicodeError):
            raise GigaChatError("INVALID_RESPONSE", "GigaChat вернул некорректный ответ") from None

    def _access_token(self, *, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and self._clock() < self._expires_at - 60:
                return self._token
            response = self._send(
                "POST",
                self.settings.auth_url,
                headers={"Authorization": "Basic " + self._credentials, "RqUID": str(uuid4())},
                data={"scope": self.settings.scope},
            )
            self._raise_status(response)
            data = self._json(response)
            try:
                token, expiry = data["access_token"], float(data["expires_at"])
                # Responses in the field use epoch milliseconds; accept epoch seconds too.
                if expiry >= 10**12:
                    expiry /= 1000
                if (
                    not isinstance(token, str)
                    or not token
                    or any(ch.isspace() for ch in token)
                    or not math.isfinite(expiry)
                    or expiry <= self._clock()
                ):
                    raise ValueError
            except (TypeError, KeyError, ValueError, OverflowError):
                raise GigaChatError(
                    "INVALID_RESPONSE", "Не удалось прочитать токен доступа GigaChat"
                ) from None
            self._token, self._expires_at = token, expiry
            return token

    def _authorized(self, method: str, path: str, **kwargs) -> httpx.Response:
        for attempt in range(2):
            token = self._access_token(force=attempt == 1)
            response = self._send(
                method,
                self.settings.base_url + path,
                headers={"Authorization": "Bearer " + token},
                **kwargs,
            )
            if response.status_code == 401 and attempt == 0:
                continue
            self._raise_status(response)
            return response
        raise AssertionError("Unreachable")

    def models(self) -> list[str]:
        data = self._json(self._authorized("GET", "/models"))
        try:
            values = [item["id"] for item in data["data"]]
            if any(not isinstance(value, str) for value in values):
                raise ValueError
            return values
        except (TypeError, KeyError, ValueError):
            raise GigaChatError(
                "INVALID_RESPONSE", "Не удалось прочитать список моделей GigaChat"
            ) from None

    def generate(self, *, system: str, context: dict, schema: dict) -> dict:
        response = self._authorized(
            "POST",
            "/chat/completions",
            json={
                "model": self.settings.model,
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps(context, ensure_ascii=False, allow_nan=False),
                    },
                ],
                "stream": False,
                "temperature": 0.1,
                "max_tokens": self.settings.max_tokens,
                "response_format": {"type": "json_schema", "schema": schema, "strict": True},
            },
        )
        data = self._json(response)
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") != "stop" or not isinstance(content, str) or not content:
                raise ValueError
        except (TypeError, KeyError, IndexError, ValueError):
            raise GigaChatError("INVALID_RESPONSE", "GigaChat вернул неполный ответ") from None
        return {
            "content": content,
            "model": data.get("model", self.settings.model),
            "usage": data.get("usage", {}),
        }
