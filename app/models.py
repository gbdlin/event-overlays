import re
import tomllib
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, UTC
from pathlib import Path, PurePath
from typing import Annotated, Any, Literal, Self, TypeAlias
from urllib.parse import urljoin

from fastapi.utils import deep_dict_update
from pydantic import AnyHttpUrl, BaseModel, computed_field, ConfigDict, Field, field_validator, HttpUrl, model_validator

from .utils.file_sha import get_file_sha

CONFIG_ROOT = Path("config")

EVENT_CONFIGS_ROOT = Path("config/events")
TIMER_CONFIGS_ROOT = CONFIG_ROOT / "timers"
RIG_CONFIGS_ROOT = CONFIG_ROOT / "rigs"

states: dict[str, "State"] = {}


class ContextualModel(BaseModel):
    _current_instance: ContextVar

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        cls._current_instance = ContextVar("_current_instance")

    @classmethod
    def get_current_instance(cls) -> Self | None:
        return cls._current_instance.get(None)

    @contextmanager
    def _bind(self):
        token = self._current_instance.set(self)
        try:
            yield self
        finally:
            self._current_instance.reset(token)

    def __init__(self, /, **data):
        with self._bind():
            super().__init__(**data)


def natural_sort_key(s: str, _nsre: re.Pattern = re.compile(r'([0-9]+)')) -> list[int | str]:
    return [int(text) if text.isdigit() else text.lower()
            for text in _nsre.split(s)]


class EventScheduleAuthor(BaseModel):
    name: str
    picture_url: AnyHttpUrl | None = None


class EventScheduleEntryBase(BaseModel):
    model_config = ConfigDict(extra="allow")

    start: datetime | None = None
    classes: list[str] = []


class EventTalkBase(EventScheduleEntryBase):

    type: Literal["talk"]
    title: str
    language: str


class EventTalkLegacy(EventTalkBase):
    author: EventScheduleAuthor

    @computed_field()
    @property
    def authors(self) -> list[EventScheduleAuthor]:
        return [self.author]


class EventTalk(EventTalkBase):
    authors: list[EventScheduleAuthor] = []

    @computed_field()
    @property
    def author(self) -> EventScheduleAuthor:
        return EventScheduleAuthor(
            name=", ".join(author.name for author in self.authors),
            picture_url=self.authors[0].picture_url if len(self.authors) == 1 else None,
        )


class EventAnnouncement(EventScheduleEntryBase):
    type: Literal["announcement"]
    title: str


class EventBreak(EventScheduleEntryBase):
    type: Literal["break"]
    title: str | None = "Break"


class EventLightningTalks(EventScheduleEntryBase):
    type: Literal["lightning-talks"]

    @computed_field
    @property
    def title(self) -> str:
        return "Lightning talks"


class EventSocial(BaseModel):
    type: Literal["discord", "youtube", "meetup", "website", "slido"]
    url: AnyHttpUrl
    code: str | None = None
    img: HttpUrl | Path | None = None


class EventSponsor(BaseModel):
    name: str
    logo: AnyHttpUrl | Path
    url: AnyHttpUrl | None = None
    classes: list[str] = []

    @computed_field
    @property
    def logo_url(self) -> str:
        return urljoin("/static/", str(self.logo))


class Template(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""

    # TODO: figure out theme-specific settings
    sponsors_on_intermission: bool = False

    title: str = "{event.name}"
    schedule_length: int = 3
    default_display: str = "scene"
    ticker_source: Literal["manual", "schedule"] = "manual"
    schedule_ticker_leeway: int = 10

    schedule_header: str = "{next_word} in the schedule:"


class EventFarewell(BaseModel):
    message: str = "See you next time!"


class EventQuestionsIntegration(BaseModel):
    name: str
    qr_code: HttpUrl | Path
    url: str | None = None

    @computed_field
    @property
    def qr_code_url(self) -> str:
        return urljoin("/static/", str(self.qr_code))


EventScheduleItem: TypeAlias = EventTalkLegacy | EventTalk | EventBreak | EventAnnouncement | EventLightningTalks



class Event(ContextualModel):
    model_config = ConfigDict(extra="allow")

    path: PurePath  # this is injected by config loader
    name: str
    logo_url: HttpUrl | Path
    starts: datetime
    branding: str | None = None
    sponsors: list[EventSponsor] = []
    schedule: list[EventScheduleItem] = []
    socials: list[EventSocial] = []
    farewell: EventFarewell = EventFarewell()
    questions_integration: EventQuestionsIntegration | None = None

    template: Template = Template()

    control_password: str | None = None

    @field_validator("schedule", mode="before")
    @classmethod
    def add_schedule_entries_lp(cls, value: list[dict]):
        if isinstance(value, list):
            return [
                {**el, "lp": i} if isinstance(el, dict) else el
                for i, el in enumerate(value)
            ]
        return value

    @computed_field
    @property
    def title(self) -> str:
        return self.template.title.format(event=self)

    def get_schedule_header(self, state, next_word) -> str:
        return self.template.schedule_header.format(event=self, state=state, next_word=next_word)

    @computed_field
    @property
    def group(self) -> str:
        return str(self.path.parent)

    @computed_field
    @property
    def slug(self) -> str:
        return self.path.stem

    @computed_field
    @property
    def branding_sha(self) -> str | None:
        return get_file_sha(f"static/branding/{self.branding}.css")

    @staticmethod
    def get_event_dict(path: PurePath) -> "dict":

        def get_table_from_toml(path_node: PurePath):
            config_path = (EVENT_CONFIGS_ROOT / path_node).resolve().with_suffix(".toml")
            with config_path.open("rb") as event_fd:
                toml_data = tomllib.load(event_fd)

            return toml_data.get("event") or {}

        config_dict = {}
        for node in reversed(path.parents):
            try:
                deep_dict_update(config_dict, get_table_from_toml(node))
            except IOError:
                pass

        deep_dict_update(config_dict, get_table_from_toml(path))

        return {**config_dict, "path": path}

    @classmethod
    def get_event_config(cls, *, path: str) -> "Event":
        path = PurePath(path)

        return cls.model_validate(cls.get_event_dict(path))


class StateException(Exception):
    detail = "Something wrong happened"


class StateIncrementOverflow(StateException):
    detail = "Cannot tick. Already at the end of event."


class StateDecrementOverflow(StateException):
    detail = "Cannot untick. Already at the start of event."


class StateNotManual(StateException):
    detail = "Cannot modify state, not manually controlled."


class TimerState(BaseModel):
    target: int
    started_at: int | None = None
    offset: int = 0

    message: str = ""


class State(BaseModel):
    event: Event
    _manual_ticker: int = 0

    message: str = ""

    timer: TimerState

    @property
    def _schedule_ticker(self):
        now = datetime.now(tz=UTC)
        leeway = timedelta(minutes=self.event.template.schedule_ticker_leeway)
        current = 0
        for i, entry in enumerate(self.event.schedule):
            if entry.start is not None and entry.start <= now:
                current = i
        entry = self.event.schedule[current]
        mid_talk = entry.start is not None and entry.start + leeway <= now
        return current * 2 + mid_talk

    @property
    def _ticker(self) -> int:
        return self._manual_ticker if self.event.template.ticker_source == "manual" else self._schedule_ticker

    @staticmethod
    def _schedule_position(ticker: int) -> int:
        return ticker // 2

    @staticmethod
    def _is_mid_talk(ticker: int) -> bool:
        return bool(ticker % 2)

    @classmethod
    def get_state_for(cls, ticker) -> tuple[int, bool]:
        return cls._schedule_position(ticker), cls._is_mid_talk(ticker)

    def fix_ticker(self):
        if self._manual_ticker >= len(self.event.schedule) * 2:
            self._manual_ticker = len(self.event.schedule) * 2 - 1

    def increment(self) -> tuple[int, bool]:
        if self.event.template.ticker_source != "manual":
            raise StateNotManual()
        if self._manual_ticker + 1 >= len(self.event.schedule) * 2:
            raise StateIncrementOverflow()
        self._manual_ticker += 1

        return self.current_state

    def decrement(self) -> tuple[int, bool]:
        if self.event.template.ticker_source != "manual":
            raise StateNotManual()
        if self._manual_ticker - 1 < 0:
            raise StateDecrementOverflow()
        self._manual_ticker -= 1

        return self.current_state

    def move_to(self, new_state: str | tuple[int, bool]) -> None:
        if isinstance(new_state, str):
            new_state = new_state.split("-")
            new_state = int(new_state[0]), new_state[1] == "mid"

        self._manual_ticker = new_state[0] * 2 + int(new_state[1])

    @property
    def _schedule_screen_ticker(self) -> int:
        return self._schedule_position(self._ticker) + self._is_mid_talk(self._ticker)

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
        if predicted_state[0] >= len(self.event.schedule):
            return None, None
        return predicted_state

    @property
    def current_schedule_item(self) -> EventScheduleItem:
        return self.event.schedule[self._schedule_position(self._ticker)]

    @property
    def remaining_schedule(self) -> list[EventScheduleItem]:
        return self.event.schedule[self._schedule_screen_ticker:]

    @property
    def global_context(self) -> dict:
        return {"message": self.message, "socials": self.event.socials, "sponsors": self.event.sponsors}

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
            return "message", {**self.global_context, "info": self.event.farewell.message}
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
        return [{**item.model_dump(), "state": get_state_for(item)} for index, item in enumerate(self.event.schedule)]

    @computed_field
    @property
    def schedule_header(self) -> str:
        return self.event.get_schedule_header(
            state=self,
            next_word="Today" if self._ticker == 0 else "Next",
        )

    @computed_field
    @property
    def schedule_extra_columns(self) -> list[str]:
        columns = set()
        for item in self.event.schedule:
            if item.model_extra:
                columns |= set(item.model_extra.keys())
        return list(columns)

    @classmethod
    def get_event_state(cls, *, path: str) -> "State":
        if path not in states:
            states[path] = cls(
                event=Event.get_event_config(path=path),
                timer=TimerState(target=15 * 60 * 1000),  # 15 minutes default, will be read at some point from config.
            )

        return states[path]


class RigChecklistItem(BaseModel):
    name: str
    hint: str | None = None
    warning: str | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_pure_string(cls, data: Any):
        if isinstance(data, str):
            return {"name": data}
        return data


class RigChecklistItemGroup(BaseModel):
    name: str
    items: list["RigChecklistItem | RigChecklistItemGroup"]


class RigChecklist(RigChecklistItemGroup):
    _rig: "RigConfig | None"

    slug: str  # injected by RigConfig validator
    links_to_slugs: Annotated[list[str], Field(alias="links_to")] = []

    def model_post_init(self, __context: Any):
        self._rig = RigConfig.get_current_instance()

    @property
    def links_to(self) -> list["RigChecklist"]:
        return [self._rig.checklists[other_checklist] for other_checklist in self.links_to_slugs]



class RigConfig(ContextualModel):
    slug: str

    control_password: str
    event_path: str | None

    checklists: dict[str, RigChecklist] = {}

    @field_validator("checklists", mode="before")
    @classmethod
    def inject_checklist_slugs(cls, value: dict) -> dict:
        if isinstance(value, dict):
            return {slug: {**checklist, "slug": slug} for slug, checklist in value.items()}
        return value

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
