import tomllib
from datetime import datetime
from functools import cached_property
from pathlib import Path, PurePath
from typing import Annotated, Any, Literal, TYPE_CHECKING, TypeAlias
from urllib.parse import urljoin

import jinja2
from fastapi.utils import deep_dict_update
from pydantic import AnyHttpUrl, BaseModel, computed_field, ConfigDict, Field, field_validator, HttpUrl, model_validator

from app.constants import EVENT_CONFIGS_ROOT

from .base import ContextualModel
from ..utils.file_sha import get_file_sha

if TYPE_CHECKING:
    from .state import State


class ReferencingEvent:
    _event: "Event | None" = None
    _jinja_env: jinja2.Environment | None = None

    def model_post_init(self, __context: Any) -> None:
        self._event = Event.get_current_instance()
        self._jinja_env = jinja2.Environment()

    def render_template(self, template: str, **extra_context) -> str:
        if self._event is None or self._event.get_state() is None:
            return ""
        return self._jinja_env.from_string(template).render(
            **{**self.template_context(), **extra_context},
        )

    def template_context(self) -> dict[str, Any]:
        return {
            "event": self._event,
            "state": self._event.get_state(),
        }


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
    show_on_presentation: bool = True

    @computed_field
    @property
    def logo_url(self) -> str:
        return urljoin("/static/", str(self.logo))


class EventSponsorGroup(BaseModel):
    name: str= ""
    sponsors: list[EventSponsor] = []
    classes: list[str] = []
    sponsor_classes: list[str] = []
    show_on_presentation: bool = True
    intermission_screen_number: int = 0


class BaseViewScreen(ReferencingEvent, BaseModel):
    model_config = ConfigDict(extra="allow")

    logo: bool = True
    condition: str = "True"


class PresentationTitleViewScreen(BaseViewScreen):
    type: Literal["presentation-title"]


class MessageViewScreen(BaseViewScreen):
    type: Literal["message"]


class NextViewScreen(BaseViewScreen):
    type: Literal["next"]


class ScheduleViewScreen(BaseViewScreen):
    type: Literal["schedule"]

    header_template: Annotated[str | None, Field(validation_alias="header", exclude=True)] = None
    subheader_template: Annotated[str | None, Field(validation_alias="subheader", exclude=True)] = None

    raw_length: Annotated[int | None, Field(validation_alias="length", exclude=True)] = None

    show_start_time: bool = True
    show_end_time: bool = False
    skip_breaks: bool = False

    @computed_field()
    @property
    def header(self) -> str:
        if self._event.get_state() is None:
            return None

        if self.header_template is None:
            return self._event.get_state().schedule_header

        return self.render_template(self.header_template)

    @computed_field()
    @property
    def subheader(self) -> str:
        if self.subheader_template is None:
            return None
        return self.render_template(self.subheader_template)

    @computed_field()
    @property
    def length(self) -> int:
        if self.raw_length is not None:
            return self.raw_length

        if self._event is None:
            return 3

        return self._event.template.schedule_length

    @computed_field()
    @property
    def schedule(self) -> list["EventScheduleItem"]:
        if self._event.get_state() is None:
            return []
        return self._event.get_state().remaining_schedule


class OtherScheduleViewScreen(ScheduleViewScreen):
    type: Literal["other-event-schedule"]

    event_path: Annotated[str, Field(validation_alias="event")]

    @cached_property
    def other_event_state(self):
        from .state import State
        return State.get_event_state(path=self.event_path)

    @computed_field()
    @property
    def schedule(self) -> list["EventScheduleItem"]:
        if self.other_event_state is None:
            return []
        return self.other_event_state.remaining_schedule


class OtherSchedulesViewScreen(ScheduleViewScreen):
    type: Literal["other-events-schedule"]

    event_paths: Annotated[list[str], Field(validation_alias="events")]
    other_event_name_template: Annotated[str, Field(validation_alias="other_event_name", exclude=True)]

    @cached_property
    def other_event_states(self):
        from .state import State
        return [
            State.get_event_state(path=event_path)
            for event_path in self.event_paths
        ]

    def create_other_event_name(self, other_event_state: "State") -> str:
        return self.render_template(
            self.other_event_name_template,
            state=other_event_state,
            event=other_event_state.event,
        )

    @computed_field()
    @property
    def schedule(self) -> list[dict]:
        return [
            {**state.remaining_schedule[0].model_dump(), "event_name": self.create_other_event_name(state)}
            for state in self.other_event_states
            if state is not None and len(state.remaining_schedule)
        ]


class SponsorGroupsViewScreen(BaseViewScreen):
    type: Literal["sponsor-groups"]
    group_numbers: Annotated[list[int], Field(alias="groups")]

    @computed_field()
    @property
    def groups(self) -> list[EventSponsorGroup]:
        if self._event is None:
            return []
        return [self._event.sponsor_groups[no] for no in self.group_numbers]


class SponsorsViewScreen(BaseViewScreen):
    type: Literal["sponsors"]


class VideoViewScreen(BaseViewScreen):
    type: Literal["video"]


type ViewScreen = Annotated[
    PresentationTitleViewScreen | MessageViewScreen | NextViewScreen | ScheduleViewScreen | OtherScheduleViewScreen | OtherSchedulesViewScreen | SponsorsViewScreen | SponsorGroupsViewScreen | VideoViewScreen,
    Field(discriminator="type"),
]


class View(BaseModel):
    model_config = ConfigDict(extra="allow")
    _event: "Event | None" = None

    screens: list[ViewScreen]

    def model_post_init(self, __context: Any) -> None:
        self._event = Event.get_current_instance()

    def get_active_screens(self, state: "State") -> list[ViewScreen]:
        jinja_env = jinja2.Environment()
        return [
            screen
            for screen in self.screens
            if jinja_env.from_string(screen.condition).render(state=state) == "True"
        ]

    @computed_field
    @property
    def active_screens(self) -> list[ViewScreen]:
        if self._event is None or self._event.get_state() is None:
            return []

        return self.get_active_screens(self._event.get_state())


class Template(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""

    # TODO: figure out theme-specific settings
    sponsors_on: list[Literal["presentation", "schedule", "next", "message"]] | None = None
    default_screen_timeout: int = 5000

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

    _state: "State | None" = None

    path: PurePath  # this is injected by config loader
    name: str
    logo_url: HttpUrl | Path
    starts: datetime
    branding: str | None = None
    sponsors: list[EventSponsor] = []
    sponsor_groups: list[EventSponsorGroup] = []
    schedule: list[EventScheduleItem] = []
    socials: list[EventSocial] = []
    farewell: EventFarewell = EventFarewell()
    questions_integration: EventQuestionsIntegration | None = None

    template: Template = Template()

    views: dict[str, View] = {}

    control_password: str | None = None

    def inject_state(self, state: "State") -> None:
        self._state = state

    def get_state(self) -> "State":
        return self._state

    def remove_state(self) -> None:
        self._state = None

    @field_validator("schedule", mode="before")
    @classmethod
    def add_schedule_entries_lp(cls, value: list[dict]):
        if isinstance(value, list):
            return [
                {**el, "lp": i} if isinstance(el, dict) else el
                for i, el in enumerate(value)
            ]
        return value

    @model_validator(mode="after")
    def validate_sponsor_groups(self):
        if self.sponsors and self.sponsor_groups:
            raise ValueError("Only one of `sponsors` and `sponsor_groups` can be provided")

        if self.sponsors:
            self.sponsor_groups.append(
                EventSponsorGroup(
                    sponsors=self.sponsors,
                )
            )
            self.sponsors = []

        return self

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
    def all_sponsors(self) -> list[EventSponsor]:
        return [sponsor for group in self.sponsor_groups for sponsor in group.sponsors]

    @computed_field
    @property
    def presentation_sponsors(self) -> list[EventSponsor]:
        return [
            sponsor
            for group in self.sponsor_groups if group.show_on_presentation
            for sponsor in group.sponsors if sponsor.show_on_presentation
        ]

    @computed_field
    @property
    def intermission_screens_count(self) -> int:
        return max((group.intermission_screen_number for group in self.sponsor_groups), default=0) + 1

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
