import re
import tomllib
from datetime import datetime
from pathlib import Path, PurePath
from typing import Literal, overload
from urllib.parse import urljoin

from pydantic import AnyHttpUrl, BaseModel, computed_field, ConfigDict, HttpUrl

from .utils.file_sha import get_file_sha

CONFIG_ROOT = Path("config")

MEETING_CONFIGS_ROOT = Path("config/events")
TIMER_CONFIGS_ROOT = CONFIG_ROOT / "timers"
RIG_CONFIGS_ROOT = CONFIG_ROOT / "rigs"

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
    model_config = ConfigDict(extra="allow")

    type: Literal["talk"]
    title: str
    language: str
    author: MeetingScheduleAuthor


class MeetingLightningTalks(BaseModel):
    type: Literal["lightning-talks"]


class MeetingSocial(BaseModel):
    type: Literal["discord", "youtube", "meetup", "website", "slido"]
    url: AnyHttpUrl
    code: str | None = None
    img: HttpUrl | Path | None = None


class MeetingSponsor(BaseModel):
    name: str
    logo: AnyHttpUrl | Path
    url: AnyHttpUrl | None = None

    @computed_field
    @property
    def logo_url(self) -> str:
        return urljoin("/static/", str(self.logo))


class MeetingTheme(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""

    # TODO: figure out theme-specific settings
    sponsors_on_intermission: bool = False


class MeetingFarewell(BaseModel):
    message: str = "See you next time!"


class MeetingQuestionsIntegration(BaseModel):
    name: str
    qr_code: HttpUrl | Path
    url: str | None = None

    @computed_field
    @property
    def qr_code_url(self) -> str:
        return urljoin("/static/", str(self.qr_code))


class Meeting(BaseModel):
    slug: str  # this is injected by config loader
    group: str  # this is injected by config loader
    name: str
    logo_url: HttpUrl | Path
    type: str
    number: int
    starts: datetime
    branding: str | None = None
    sponsors: list[MeetingSponsor] = []
    schedule: list[MeetingTalk | MeetingLightningTalks] = []
    socials: list[MeetingSocial] = []
    farewell: MeetingFarewell = MeetingFarewell()
    questions_integration: MeetingQuestionsIntegration | None = None

    theme: MeetingTheme = MeetingTheme()

    control_password: str | None = None

    @property
    def full_title(self):
        return f"{self.type} #{self.number}"

    @staticmethod
    def get_meeting_dict(path: Path) -> "dict":
        with path.open("rb") as meeting_fd:
            return {**tomllib.load(meeting_fd)["meeting"], "slug": path.stem}

    @computed_field
    @property
    def path(self) -> str:
        return f"{self.group}/{self.slug}"

    @computed_field
    @property
    def branding_sha(self) -> str:
        return get_file_sha(f"static/branding/{self.branding}.css")

    @overload
    @classmethod
    def get_meeting_config(cls, *, group: str, slug: str) -> "Meeting":
        pass

    @overload
    @classmethod
    def get_meeting_config(cls, *, path: str) -> "Meeting":
        pass

    @classmethod
    def get_meeting_config(cls, *, group: str = None, slug: str = None, path: str = None) -> "Meeting":
        if group and slug:
            if slug == "__latest__":
                slug = get_latest_meeting_slug(MEETING_CONFIGS_ROOT, group)
            path = MEETING_CONFIGS_ROOT / group / f"{slug}.toml"
        elif path:
            path = PurePath(path)
            group = str(path.parent)
            path = MEETING_CONFIGS_ROOT / f"{path}.toml"

        return cls.model_validate({**cls.get_meeting_dict(path), "group": group})


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
    def _schedule_ticker(ticker: int) -> int:
        return ticker // 2

    @staticmethod
    def _is_mid_talk(ticker: int) -> bool:
        return bool(ticker % 2)

    @classmethod
    def get_state_for(cls, ticker) -> tuple[int, bool]:
        return cls._schedule_ticker(ticker), cls._is_mid_talk(ticker)

    def fix_ticker(self):
        if self._ticker >= len(self.meeting.schedule) * 2:
            self._ticker = len(self.meeting.schedule) * 2 - 1

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

    def move_to(self, new_state: str | tuple[int, bool]) -> None:
        if isinstance(new_state, str):
            new_state = new_state.split("-")
            new_state = int(new_state[0]), new_state[1] == "mid"

        self._ticker = new_state[0] * 2 + int(new_state[1])

    @property
    def _schedule_screen_ticker(self) -> int:
        return self._schedule_ticker(self._ticker) + self._is_mid_talk(self._ticker)

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
        return self.meeting.schedule[self._schedule_ticker(self._ticker)]

    @property
    def remaining_schedule(self) -> list[MeetingTalk | MeetingLightningTalks]:
        return self.meeting.schedule[self._schedule_screen_ticker:]

    @property
    def global_context(self) -> dict:
        return {"message": self.message, "socials": self.meeting.socials, "sponsors": self.meeting.sponsors}

    @computed_field
    @property
    def title_screen_content(self) -> tuple[str, dict]:
        return "next", {**self.global_context, "entry": self.current_schedule_item.model_dump()}

    @computed_field
    @property
    def brb_screen_content(self) -> tuple[str, dict]:
        return "message", {**self.global_context, "info": "Back in a moment..."}

    @computed_field
    @property
    def hybrid_screen_content(self) -> tuple[str, dict]:
        if self._is_mid_talk(self._ticker):  # we're mid talk
            return self.brb_screen_content
        else:  # we're between talks
            return self.title_screen_content

    @computed_field
    @property
    def schedule_screen_content(self) -> tuple[str, dict]:
        schedule = [item.model_dump() for item in self.remaining_schedule]
        if self._schedule_screen_ticker == 0:
            message = "Starting soon..."
        elif len(schedule):
            message = "Be right back..."
        else:  # we're at the end, there is no next talk
            return "message", {**self.global_context, "info": self.meeting.farewell.message}
        return "schedule", {**self.global_context, "schedule": schedule, "info": message}

    @computed_field
    @property
    def presentation_screen_content(self) -> tuple[str, dict]:
        return "presentation", {**self.global_context, "entry": self.current_schedule_item}

    @computed_field
    @property
    def schedule(self) -> list[dict]:
        def get_state_for(item):
            if self._is_mid_talk(self._ticker) and item == self.current_schedule_item:
                return "current"
            if self.remaining_schedule and item == self.remaining_schedule[0]:
                return "next"
            if item in self.remaining_schedule:
                return "future"
            return "past"
        return [{**item.model_dump(), "state": get_state_for(item)} for index, item in enumerate(self.meeting.schedule)]

    @computed_field
    @property
    def schedule_extra_columns(self) -> list[str]:
        columns = set()
        for item in self.meeting.schedule:
            if item.model_extra:
                columns |= set(item.model_extra.keys())
        return list(columns)

    @classmethod
    def get_meeting_state(cls, group: str, slug: str) -> "State":
        if slug == "__latest__":
            slug = get_latest_meeting_slug(MEETING_CONFIGS_ROOT, group)

        if (group, slug) not in states:
            states[group, slug] = cls(
                meeting=Meeting.get_meeting_config(group=group, slug=slug),
                timer=TimerState(target=15 * 60 * 1000),  # 15 minutes default, will be read at some point from config.
            )

        return states[group, slug]


class RigConfig(BaseModel):
    slug: str

    control_password: str
    meeting_group: str | None
    meeting_slug: str | None

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


class TimerConfig(BaseModel):
    slug: str

    event: str | None = None
    rig: str | None = None

    @staticmethod
    def get_timer_dict(path: Path) -> "dict":
        with path.open("rb") as timer_fd:
            return {**tomllib.load(timer_fd)["timer"], "slug": path.stem}

    @classmethod
    def get_timer_config(cls, slug: str) -> "TimerConfig":
        path = TIMER_CONFIGS_ROOT / f"{slug}.toml"

        return cls.model_validate(cls.get_timer_dict(path))
