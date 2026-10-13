from datetime import datetime, UTC
import tomllib
from pathlib import Path

from .base import ContextualModel
from app.constants import RIG_CONFIGS_ROOT


class RigConfig(ContextualModel):
    slug: str

    control_password: str
    event_path: str | None = None

    events_schedule: list[tuple[datetime, str]] | None = None

    def get_current_event_path(self) -> str:
        event_path = None
        now = datetime.now(tz=UTC)
        if self.events_schedule:
            for start_date, path in self.events_schedule:
                if start_date is not None and start_date > now:
                    break
                event_path = path
        elif self.event_path is not None:
            event_path = self.event_path
        if event_path is None:
            raise ValueError("No event path set")

        return event_path

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
