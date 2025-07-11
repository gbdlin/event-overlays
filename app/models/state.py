from datetime import datetime, timedelta, UTC
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, computed_field, ConfigDict, field_validator

from .event import Event, EventScheduleItem

if TYPE_CHECKING:
    from app.models import RigConfig

states: dict[str, "State"] = {}
rig_states: dict[str, "State"] = {}


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
    model_config = ConfigDict(validate_assignment=True)

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

    def get_view_position(self, view: str, offset: int = 0) -> int | None:
        matrix = {
            "scene-schedule": self._schedule_screen_ticker,
        }
        position = matrix.get(view, self._schedule_position(self._ticker)) + offset

        return position if position >= 0 or position < len(self.event.schedule) else None

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

    @computed_field
    @property
    def current_schedule_item(self) -> EventScheduleItem:
        return self.event.schedule[self._schedule_position(self._ticker)]

    @property
    def remaining_schedule(self) -> list[EventScheduleItem]:
        return self.event.schedule[self._schedule_screen_ticker:]

    @property
    def global_context(self) -> dict:
        schedule = [item.model_dump() for item in self.remaining_schedule]

        return {
            "message": self.message,
            "socials": self.event.socials,
            "sponsors": self.event.all_sponsors,
            "sponsor_groups": self.event.sponsor_groups,
            "presentation_groups": self.event.presentation_sponsors,
            "current_entry": self.current_schedule_item,
            "schedule": schedule,
        }

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
    def schedule_screen_content(self) -> tuple[str, dict]:
        if self._schedule_screen_ticker == 0:
            message = "Starting soon..."
        elif len(self.remaining_schedule):
            message = "Be right back..."
        else:  # we're at the end, there is no next talk
            return "message", {**self.global_context, "info": self.event.farewell.message}
        return "schedule", {**self.global_context, "info": message}

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

    def get_view_for(self, view_name: str) -> dict:
        return self.event.views[view_name].model_dump() if view_name in self.event.views else None

    def replace_event(self, event: Event) -> None:
        self.event.remove_state()
        self.event = event
        self.event.inject_state(self)

    @classmethod
    def create_event_state(cls, *, path: str) -> "State":
        state =  cls(
            event=Event.get_event_config(path=path),
            timer=TimerState(target=15 * 60 * 1000),  # 15 minutes default, will be read at some point from config.
        )
        state.event.inject_state(state)
        return state

    @classmethod
    def get_event_state(cls, *, path: str) -> "State":
        if path not in states:
            states[path] = cls.create_event_state(path=path)

        return states[path]

    @classmethod
    def get_rig_state(cls, *, rig: "RigConfig") -> "State":
        if rig.slug not in rig_states:
            rig_states[rig.slug] = cls.create_event_state(path=rig.event_path)

        return rig_states[rig.slug]