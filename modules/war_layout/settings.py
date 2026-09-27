import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class WarLayoutSettings:
    authors: tuple[str, ...]
    x_bearer_token: str
    socialdata_api_key: str = ""
    source: str = "official"
    socialdata_user_ids: dict[str, str] = None
    socialdata_max_requests: int = 3
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    enabled: bool = False
    auto_mass_send: bool = False
    daily_time: str = "09:00"
    media_dir: Path = Path("/tmp/sky-admin-war-layout")
    db_path: Path = Path(__file__).resolve().parent / "runtime" / "war_layout.db"
    image_proxy_url: str = ""

    @classmethod
    def from_env(cls) -> "WarLayoutSettings":
        # Follow the repository convention: load only the root .env file.
        from shared.config.env_loader import load_env

        load_env()
        authors = tuple(item.strip().lstrip("@") for item in os.getenv("WAR_LAYOUT_X_AUTHORS", "").split(",") if item.strip())
        raw_ids = os.getenv("WAR_LAYOUT_X_USER_IDS", "")
        user_ids = {}
        for item in raw_ids.split(","):
            if "=" in item:
                name, uid = item.split("=", 1)
                if name.strip() and uid.strip():
                    user_ids[name.strip().lstrip("@")] = uid.strip()
        return cls(
            authors=authors,
            x_bearer_token=os.getenv("X_BEARER_TOKEN", ""),
            socialdata_api_key=os.getenv("SOCIALDATA_API_KEY", ""),
            source=os.getenv("WAR_LAYOUT_SOURCE", "official").strip().lower(),
            socialdata_user_ids=user_ids,
            socialdata_max_requests=int(os.getenv("SOCIALDATA_MAX_REQUESTS_PER_RUN", "3")),
            wechat_app_id=os.getenv("WECHAT_APP_ID", ""),
            wechat_app_secret=os.getenv("WECHAT_APP_SECRET", ""),
            enabled=os.getenv("WAR_LAYOUT_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on"),
            auto_mass_send=os.getenv("WAR_LAYOUT_AUTO_MASS_SEND", "false").strip().lower() in ("1", "true", "yes", "on"),
            daily_time=os.getenv("WAR_LAYOUT_DAILY_TIME", "09:00").strip(),
            media_dir=Path(os.getenv("WAR_LAYOUT_MEDIA_DIR", "/tmp/sky-admin-war-layout")),
            db_path=Path(os.getenv("WAR_LAYOUT_DB_PATH", str(Path(__file__).resolve().parent / "runtime" / "war_layout.db"))),
            image_proxy_url=os.getenv("WAR_LAYOUT_IMAGE_PROXY_URL", "").strip(),
        )

    def validate_x(self) -> None:
        if not self.authors:
            raise ValueError("WAR_LAYOUT_X_AUTHORS is required")
        if self.source == "official" and not self.x_bearer_token:
            raise ValueError("X_BEARER_TOKEN is required")
        if self.source == "socialdata" and not self.socialdata_api_key:
            raise ValueError("SOCIALDATA_API_KEY is required")
        if self.source == "socialdata":
            missing = [a for a in self.authors if a not in (self.socialdata_user_ids or {})]
            if missing:
                raise ValueError("WAR_LAYOUT_X_USER_IDS is required for all SocialData authors")
        if self.source not in ("official", "socialdata"):
            raise ValueError("WAR_LAYOUT_SOURCE must be official or socialdata")

    def validate_wechat(self) -> None:
        if not self.wechat_app_id or not self.wechat_app_secret:
            raise ValueError("WECHAT_APP_ID and WECHAT_APP_SECRET are required")

    def validate_schedule(self) -> None:
        try:
            hour, minute = (int(part) for part in self.daily_time.split(":"))
        except (TypeError, ValueError):
            raise ValueError("WAR_LAYOUT_DAILY_TIME must use HH:MM") from None
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("WAR_LAYOUT_DAILY_TIME must use HH:MM")

    def validate_image_proxy(self) -> None:
        if not self.image_proxy_url:
            return
        parsed = urlparse(self.image_proxy_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("WAR_LAYOUT_IMAGE_PROXY_URL must be an HTTP(S) URL")
