import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GigaChatSettings:
    enabled: bool = False
    credentials: str = field(default="", repr=False)
    scope: str = "GIGACHAT_API_PERS"
    base_url: str = "https://api.giga.chat/v1"
    auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    model: str = "GigaChat"
    ca_bundle: Path | None = None
    timeout_seconds: float = 60
    max_tokens: int = 1200
    auto_analyze: bool = True

    @classmethod
    def from_env(cls) -> "GigaChatSettings":
        return cls(
            enabled=os.getenv("GIGACHAT_ENABLED", "0") == "1",
            credentials=os.getenv("GIGACHAT_CREDENTIALS", "").strip(),
            scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            base_url=os.getenv("GIGACHAT_BASE_URL", "https://api.giga.chat/v1").rstrip("/"),
            auth_url=os.getenv(
                "GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
            ),
            model=os.getenv("GIGACHAT_MODEL", "GigaChat"),
            ca_bundle=Path(os.environ["GIGACHAT_CA_BUNDLE"]).resolve()
            if os.getenv("GIGACHAT_CA_BUNDLE")
            else None,
            timeout_seconds=float(os.getenv("GIGACHAT_TIMEOUT_SECONDS", "60")),
            max_tokens=int(os.getenv("GIGACHAT_MAX_TOKENS", "1200")),
            auto_analyze=os.getenv("GIGACHAT_AUTO_ANALYZE", "1") == "1",
        )

    def public_status(self, mock: bool) -> dict:
        return {
            "enabled": self.enabled,
            "configured": bool(self.credentials),
            "network_allowed": self.enabled and bool(self.credentials) and not mock,
            "mock": mock,
            "model": self.model,
            "scope": self.scope,
            "tls_verification": True,
            "ca_bundle_configured": self.ca_bundle is not None,
        }
