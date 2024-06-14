from fastapi import APIRouter
from fastapi.routing import APIRoute, APIWebSocketRoute

from .control import control_view
from .scenes import scene_view
from .timers import speaker_timer_view, timer_redirect
from .utils import schedule_table_view
from .websocket import ws_view

routes = [
    APIRoute("/--/s/{path:path}/{state:str}/scene-{scene:str}.html", scene_view),
    APIRoute("/{rig:str}/scene-{scene:str}.html", scene_view),

    APIWebSocketRoute("/{rig_slug:str}/ws/{role:str}", ws_view),

    APIRoute("/t/{timer_slug:str}/speaker.html", timer_redirect),
    APIRoute("/{rig:str}/speaker-timer.html", speaker_timer_view),

    APIRoute("/{rig:str}/control.html", control_view),

    APIRoute("/{rig:str}/schedule-table.html", schedule_table_view),
]

router = APIRouter(routes=routes)
