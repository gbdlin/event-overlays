import json
from typing import Literal

from fastapi import Request
from pydantic_core import to_json

from ..models import Meeting, State, TimerState
from ..state import get_state_update_for
from ..template_renderer import renderer


async def scene_view(
    request: Request,
    scene: str,
    rig: str | None = None,
    path: str | None = None,
    state: str | None = None,
    display: str = "scene",
    presentation_bottom_bar: bool = True,
    presentation_sponsors: Literal["left", "right"] | None = None,
):
    if path is not None:
        state_obj = State(
            meeting=Meeting.get_meeting_config(path=path),
            timer=TimerState(target=15 * 60 * 1000),  # 15 minutes default, will be read at some point from config.
        )
        state_obj.move_to(state)
        scene_data = json.loads(
            to_json(
                {"status": "init", "role": f"scene-{scene}", **get_state_update_for(state_obj, f"scene-{scene}", "init")},
            ),
        )
    else:
        scene_data = None
    return renderer.TemplateResponse(
        "scene.html",
        {
            "request": request,
            "rig": rig,
            "scene": scene,
            "data": scene_data,
            "display_type": display,
            "presentation_bottom_bar": presentation_bottom_bar,
            "presentation_sponsors": presentation_sponsors,
        },
    )
