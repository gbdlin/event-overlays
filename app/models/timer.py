import tomllib
from pathlib import Path

from pydantic import BaseModel

from app.constants import TIMER_CONFIGS_ROOT



class TimerConfig(BaseModel):
    slug: str

    event: str | None = None
    rig: str | None = None
    with_preview: bool = False

    @staticmethod
    def get_timer_dict(path: Path) -> "dict":
        with path.open("rb") as timer_fd:
            return {**tomllib.load(timer_fd)["timer"], "slug": path.stem}

    @classmethod
    def get_timer_config(cls, slug: str) -> "TimerConfig":
        path = TIMER_CONFIGS_ROOT / f"{slug}.toml"

        return cls.model_validate(cls.get_timer_dict(path))
