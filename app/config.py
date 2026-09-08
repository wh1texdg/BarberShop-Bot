from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    database_url: str
    admin_ids: str = ""
    cancel_min_hours_before: int = 2
    timezone: str = "Europe/Moscow"
    slot_step_minutes: int = 30

    @property
    def admin_ids_list(self) -> list[int]:
        return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip()]

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def now_local(self):
        from datetime import datetime
        return datetime.now(self.tzinfo)


settings = Settings()
