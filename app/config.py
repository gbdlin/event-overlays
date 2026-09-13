import tomllib

from pydantic import BaseModel
from pydantic_settings import BaseSettings

from app.constants import CONFIG_ROOT


class Config(BaseModel):
    secret_key: str

    @classmethod
    def load_config(cls):

        path = CONFIG_ROOT / "config.toml"

        with path.open("rb") as config_fd:
            toml_data = tomllib.load(config_fd)

        return cls.model_validate(toml_data["config"])


class Settings(BaseSettings):
    sentry_dsn: str | None = None


config = Config.load_config()
settings = Settings()
