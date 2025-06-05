import tomllib
from pathlib import Path

from .base import ContextualModel
from app.constants import RIG_CONFIGS_ROOT


class RigConfig(ContextualModel):
    slug: str

    control_password: str
    event_path: str | None

    @staticmethod
    def get_rig_dict(path: Path) -> dict | None:
        try:
            with path.open("rb") as rig_fd:
                return {**tomllib.load(rig_fd)["rig"], "slug": path.stem}
        except FileNotFoundError:
            return None

    @classmethod
    def get_rig_config(cls, slug: str) -> "RigConfig | None":
        path = RIG_CONFIGS_ROOT / f"{slug}.toml"

        rig_dict = cls.get_rig_dict(path)

        if rig_dict is None:
            return None

        return cls.model_validate(rig_dict)
