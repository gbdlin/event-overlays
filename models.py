import re
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

from pydantic import AnyHttpUrl, AnyUrl, BaseModel, computed_field, FileUrl, HttpUrl

CONFIG_ROOT = Path("config")

MEETING_CONFIGS_ROOT = Path("meetings")
TIMER_CONFIGS_ROOT = CONFIG_ROOT / "timers"

states: dict[tuple[str, str], "State"] = {}


def natural_sort_key(s: str, _nsre: re.Pattern = re.compile(r'([0-9]+)')) -> list[int, str]:
    return [int(text) if text.isdigit() else text.lower()
            for text in _nsre.split(s)]


def get_latest_meeting_slug(root_dir: Path, meeting: str) -> str:
    return sorted(
        [path.stem for path in (root_dir / meeting).glob("*.toml")],
        reverse=True,
        key=natural_sort_key,
    )[0]


class MeetingScheduleAuthor(BaseModel):
    name: str
    picture_url: AnyHttpUrl | None = None


class MeetingTalk(BaseModel):
    type: Literal["talk"]
    title: str
    language: str
    author: MeetingScheduleAuthor


class MeetingLightningTalks(BaseModel):
    type: Literal["lightning-talks"]


class MeetingSocial(BaseModel):
    type: Literal["discord", "youtube", "meetup", "website"]
    url: AnyHttpUrl


class MeetingSponsor(BaseModel):
    name: str
    logo: AnyHttpUrl | Path
    url: AnyHttpUrl | None = None

    @computed_field
    @property
    def logo_url(self) -> str:
        return urljoin("/static/", str(self.logo))


class Meeting(BaseModel):
    slug: str  # this is injected by config loader
    name: str
    logo_url: HttpUrl | Path
    type: str
    number: int
    starts: datetime
    branding: str | None = None
    sponsors: list[MeetingSponsor] = []
    schedule: list[MeetingTalk | MeetingLightningTalks] = []
    socials: list[MeetingSocial] = []

    control_password: str | None = None

    @property
    def full_title(self):
        return f"{self.type} #{self.number}"

    @staticmethod
    def get_meeting_dict(path: Path) -> "dict":
        with path.open("rb") as meeting_fd:
            return {**tomllib.load(meeting_fd)["meeting"], "slug": path.stem}

    @classmethod
    def get_meeting_config(cls, group: str, slug: str) -> "Meeting":
        if slug == "__latest__":
            slug = get_latest_meeting_slug(MEETING_CONFIGS_ROOT, group)
        path = MEETING_CONFIGS_ROOT / group / f"{slug}.toml"

        return cls.parse_obj(cls.get_meeting_dict(path))


class StateException(Exception):
    detail = "Something wrong happened"


class StateIncrementOverflow(StateException):
    detail = "Cannot tick. Already at the end of meeting."


class StateDecrementOverflow(StateException):
    detail = "Cannot untick. Already at the start of meeting."


class TimerState(BaseModel):
    target: int
    started_at: int | None = None
    offset: int = 0

    message: str = ""


class State(BaseModel):
    meeting: Meeting
    _ticker: int = 0

    message: str = ""

    timer: TimerState

    @staticmethod
    def _brb_ticker(ticker: int) -> int:
        return ticker // 2

    @staticmethod
    def _is_mid_talk(ticker: int) -> bool:
        return bool(ticker % 2)

    @classmethod
    def get_state_for(cls, ticker) -> tuple[int, bool]:
        return cls._brb_ticker(ticker), cls._is_mid_talk(ticker)

    def increment(self) -> tuple[int, bool]:
        if self._ticker + 1 >= len(self.meeting.schedule) * 2:
            raise StateIncrementOverflow()
        self._ticker += 1

        return self.current_state

    def decrement(self) -> tuple[int, bool]:
        if self._ticker - 1 < 0:
            raise StateDecrementOverflow()
        self._ticker -= 1

        return self.current_state

    @property
    def _schedule_ticker(self) -> int:
        return self._brb_ticker(self._ticker) + self._is_mid_talk(self._ticker)

    @property
    def current_state(self) -> tuple[int, bool]:
        return self.get_state_for(self._ticker)

    @property
    def previous_state(self) -> tuple[int, bool] | tuple[None, None]:
        predicted_state = self.get_state_for(self._ticker - 1)
        if predicted_state[0] < 0:
            return None, None
        return predicted_state

    @property
    def next_state(self) -> tuple[int, bool] | tuple[None, None]:
        predicted_state = self.get_state_for(self._ticker + 1)
        if predicted_state[0] >= len(self.meeting.schedule):
            return None, None
        return predicted_state

    @property
    def current_schedule_item(self) -> MeetingTalk | MeetingLightningTalks:
        return self.meeting.schedule[self._brb_ticker(self._ticker)]

    @property
    def remaining_schedule(self) -> list[MeetingTalk | MeetingLightningTalks]:
        return self.meeting.schedule[self._schedule_ticker:]

    @property
    def global_context(self) -> dict:
        return {"message": self.message, "socials": self.meeting.socials, "sponsors": self.meeting.sponsors}

    @computed_field
    @property
    def brb_screen_content(self) -> tuple[str, dict]:
        if self._is_mid_talk(self._ticker):  # we're mid talk
            return "brb", {**self.global_context, "info": "Back in a moment..."}
        else:  # we're between talks
            return "next", {**self.global_context, "entry": self.current_schedule_item.model_dump()}

    @computed_field
    @property
    def schedule_screen_content(self) -> tuple[str, dict]:
        schedule = [item.model_dump() for item in self.remaining_schedule]
        if not len(schedule):  # we're at the end, there is no next talk
            return "message", {**self.global_context, "info": "See you next time"}
        elif self._schedule_ticker == 0:
            message = "Starting soon..."
        else:
            message = "Will be back soon..."
        return "agenda", {**self.global_context, "schedule": schedule, "info": message}

    @computed_field
    @property
    def presentation_screen_content(self) -> tuple[str, dict]:
        return "presentation", {**self.global_context, "entry": self.current_schedule_item}

    @classmethod
    def get_meeting_state(cls, meeting: str, slug: str) -> "State":
        if slug == "__latest__":
            slug = get_latest_meeting_slug(MEETING_CONFIGS_ROOT, meeting)

        if (meeting, slug) not in states:
            states[meeting, slug] = cls(
                meeting=Meeting.get_meeting_config(meeting, slug),
                timer=TimerState(target=15 * 60 * 1000),  # 15 minutes default, will be read at some point from config.
            )

        return states[meeting, slug]


class TimerConfig(BaseModel):
    slug: str

    event: str | None = None
    station: str | None = None

    @staticmethod
    def get_timer_dict(path: Path) -> "dict":
        with path.open("rb") as timer_fd:
            return {**tomllib.load(timer_fd)["timer"], "slug": path.stem}

    @classmethod
    def get_timer_config(cls, slug: str) -> "TimerConfig":
        path = TIMER_CONFIGS_ROOT / f"{slug}.toml"

        return cls.model_validate(cls.get_timer_dict(path))
