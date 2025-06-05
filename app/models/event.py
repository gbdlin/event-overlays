import tomllib
from datetime import datetime
from pathlib import Path, PurePath
from typing import Literal, TypeAlias
from urllib.parse import urljoin

from fastapi.utils import deep_dict_update
from pydantic import AnyHttpUrl, BaseModel, computed_field, ConfigDict, field_validator, HttpUrl, model_validator

from app.constants import EVENT_CONFIGS_ROOT

from .base import ContextualModel
from ..utils.file_sha import get_file_sha


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
    show_on_presentation: bool = True
    intermission_screen_number: int = 0


class Template(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""

    # TODO: figure out theme-specific settings
    sponsors_on_intermission: bool | None = None
    sponsors_on: list[Literal["presentation", "schedule", "next", "message"]] | None = None
    intermission_sponsor_slides: int = 1

    title: str = "{event.name}"
    schedule_length: int = 3
    default_display: str = "scene"
    ticker_source: Literal["manual", "schedule"] = "manual"
    schedule_ticker_leeway: int = 10
    schedule_header: str = "{next_word} in the schedule:"

    @model_validator(mode="after")
    def validate_sponsors_on(self):
        if self.sponsors_on_intermission is not None and self.sponsors_on is not None:
            raise ValueError("Only one of `sponsors_on` and `sponsor_on_intermission` can be provided")

        if self.sponsors_on is None:
            self.sponsors_on = ["presentation"] + ["schedule", "next", "message"] if self.sponsors_on_intermission else []
            self.sponsors_on_intermission = None

        return self


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
    sponsor_groups: list[EventSponsorGroup] = []
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
        return max(group.intermission_screen_number for group in self.sponsor_groups) + 1

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
