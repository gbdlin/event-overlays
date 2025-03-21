from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Self

from pydantic import BaseModel


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
