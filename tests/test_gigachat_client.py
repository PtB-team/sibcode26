import json
from dataclasses import replace
from uuid import UUID

import httpx
import pytest

from integrations.gigachat import GigaChatClient, GigaChatError, GigaChatSettings


@pytest.mark.parametrize("milliseconds", [True, False])
def test_oauth_headers_cache_and_expiry(milliseconds):
    now, auths, requests = [1800000000], [], []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/oauth"):
            assert request.headers["Authorization"] == "Basic test-authorization-key"
            assert UUID(request.headers["RqUID"]).version == 4
            assert request.content == b"scope=GIGACHAT_API_PERS"
            assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
            auths.append(request.headers["RqUID"])
            return httpx.Response(
                200,
                json={
                    "access_token": "test-token",
                    "expires_at": (now[0] + 1800) * (1000 if milliseconds else 1),
                },
            )
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["User-Agent"].startswith("sibcode26")
        return httpx.Response(200, json={"data": [{"id": "GigaChat"}]})

    client = GigaChatClient(
        GigaChatSettings(credentials="test-authorization-key"),
        transport=httpx.MockTransport(handler),
        clock=lambda: now[0],
    )
    try:
        assert client.models() == client.models() == ["GigaChat"]
        assert len(auths) == 1
        now[0] += 1745
        assert client.models() == ["GigaChat"]
        assert len(auths) == 2 and auths[0] != auths[1]
    finally:
        client.close()


@pytest.mark.parametrize("always_unauthorized", [False, True])
def test_401_refreshes_token_exactly_once(always_unauthorized):
    counts = {"auth": 0, "models": 0}

    def handler(request):
        if request.url.path.endswith("/oauth"):
            counts["auth"] += 1
            return httpx.Response(
                200, json={"access_token": f"token{counts['auth']}", "expires_at": 1800001800000}
            )
        counts["models"] += 1
        return httpx.Response(
            401 if always_unauthorized or counts["models"] == 1 else 200, json={"data": []}
        )

    client = GigaChatClient(
        GigaChatSettings(credentials="key"),
        transport=httpx.MockTransport(handler),
        clock=lambda: 1800000000,
    )
    try:
        if always_unauthorized:
            with pytest.raises(GigaChatError, match="учётные данные"):
                client.models()
        else:
            assert client.models() == []
        assert counts == {"auth": 2, "models": 2}
    finally:
        client.close()


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "AUTH_FAILED"),
        (402, "QUOTA_EXHAUSTED"),
        (403, "ACCESS_DENIED"),
        (429, "RATE_LIMITED"),
        (503, "UPSTREAM_ERROR"),
    ],
)
def test_http_errors_do_not_expose_credentials_or_response_body(status, expected, caplog):
    secret = "never-print-test-key"

    def handler(request):
        return httpx.Response(status, json={"error": secret})

    client = GigaChatClient(
        GigaChatSettings(credentials=secret), transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(GigaChatError) as error:
            client.models()
        assert error.value.code == expected
        assert secret not in str(error.value) + caplog.text + repr(client.settings)
    finally:
        client.close()


def test_timeout_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("never-print-this-token", request=request)

    client = GigaChatClient(
        GigaChatSettings(credentials="key"), transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(GigaChatError) as error:
            client.models()
        assert error.value.code == "TIMEOUT" and "never-print" not in str(error.value)
    finally:
        client.close()


def test_structured_chat_uses_gigachat_v1_format():
    schema = {"type": "object", "properties": {"reason": {"type": "string"}}}

    def handler(request):
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "token", "expires_at": 1800001800000})
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_schema", "schema": schema, "strict": True}
        assert body["messages"][0]["role"] == "system"
        assert json.loads(body["messages"][1]["content"]) == {"facts": {"readiness": 45}}
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"reason":"ok"}'}}],
                "model": "GigaChat:test",
                "usage": {"total_tokens": 20},
            },
        )

    client = GigaChatClient(
        GigaChatSettings(credentials="key"),
        transport=httpx.MockTransport(handler),
        clock=lambda: 1800000000,
    )
    try:
        result = client.generate(
            system="rules", context={"facts": {"readiness": 45}}, schema=schema
        )
        assert result["content"] == '{"reason":"ok"}' and result["model"] == "GigaChat:test"
    finally:
        client.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": None}}]},
    ],
)
def test_incomplete_chat_response_is_not_accepted(payload):
    def handler(request):
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "token", "expires_at": 1800001800000})
        return httpx.Response(200, json=payload)

    client = GigaChatClient(
        GigaChatSettings(credentials="key"),
        transport=httpx.MockTransport(handler),
        clock=lambda: 1800000000,
    )
    try:
        with pytest.raises(GigaChatError) as error:
            client.generate(system="rules", context={}, schema={})
        assert error.value.code == "INVALID_RESPONSE"
    finally:
        client.close()


def test_tls_cannot_be_disabled_and_missing_certificate_is_explicit(tmp_path):
    with pytest.raises(GigaChatError) as error:
        GigaChatClient(GigaChatSettings(credentials="key", ca_bundle=tmp_path / "missing.pem"))
    assert error.value.code == "TLS_CONFIGURATION_ERROR"
    for config in [
        GigaChatSettings(credentials="key", base_url="http://example.test/v1"),
        GigaChatSettings(credentials="key", scope="invalid"),
    ]:
        with pytest.raises(GigaChatError) as error:
            GigaChatClient(config)
        assert error.value.code == "CONFIGURATION_ERROR"


def test_public_configuration_contains_no_secret():
    config = GigaChatSettings(enabled=True, credentials="test-secret-key")
    assert "test-secret-key" not in repr(config) + json.dumps(config.public_status(False))
    assert config.public_status(False)["network_allowed"]
    assert not config.public_status(True)["network_allowed"]
    assert not replace(config, enabled=False).public_status(False)["network_allowed"]
