import json
from typing import Literal

from fastapi import Request
from pydantic_core import to_json

from ..models import Event, State, TimerState
from ..state import get_state_update_for
from ..template_renderer import renderer


async def old_scene_view(
    request: Request,
    scene: str,
    rig: str | None = None,
    path: str | None = None,
    state: str | None = None,
    display: str = None,
    presentation_bottom_bar: bool = True,
    presentation_sponsors: Literal["left", "right"] | None = None,
):
    return await scene_view(
        request=request,
        view=scene,
        rig=rig,
        path=path,
        state=state,
        display=display,
        presentation_bottom_bar=presentation_bottom_bar,
        presentation_sponsors=presentation_sponsors,
    )


async def scene_view(
    request: Request,
    view: str,
    rig: str | None = None,
    path: str | None = None,
    state: str | None = None,
    display: str = None,
    presentation_bottom_bar: bool = True,
    presentation_sponsors: Literal["left", "right"] | None = None,
):
    if path is not None:
        state_obj = State.create_event_state(path=path)
        state_obj.move_to(state)
        scene_data = json.loads(
            to_json(
                {"status": "init", "role": f"scene-{view}", **get_state_update_for(state_obj, f"scene-{view}", "init")},
            ),
        )
    else:
        scene_data = None
    return renderer.TemplateResponse(
        "scene.html",
        {
            "request": request,
            "rig": rig,
            "scene": view,
            "data": scene_data,
            "display_type": display,
            "presentation_bottom_bar": presentation_bottom_bar,
            "presentation_sponsors": presentation_sponsors,
        },
    )
