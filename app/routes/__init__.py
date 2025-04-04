from fastapi import APIRouter
from fastapi.routing import APIRoute, APIWebSocketRoute

from .control import checklist_view, control_view, checklists_list_view
from .demo import demo_view
from .scenes import old_scene_view, scene_view
from .timers import speaker_timer_view, timer_redirect
from .utils import schedule_table_view
from .websocket import update_schedule_ticker, ws_view

old_routes = [
    APIRoute("/--/s/{path:path}/{state:str}/scene-{scene:str}.html", old_scene_view),
    APIRoute("/{rig:str}/scene-{scene:str}.html", old_scene_view),

    APIWebSocketRoute("/{rig_slug:str}/ws/{role:str}", ws_view),

    APIRoute("/t/{timer_slug:str}/speaker.html", timer_redirect),
    APIRoute("/{rig:str}/speaker-timer.html", speaker_timer_view),

    APIRoute("/{rig:str}/control.html", control_view),

    APIRoute("/{rig:str}/schedule-table.html", schedule_table_view),
]

old_router = APIRouter(routes=old_routes)

v1_routes = [
    APIRoute("/events/{path:path}/demo", demo_view),
    APIRoute("/events/{path:path}/views/{view:str}/{state:str}", scene_view),

    APIRoute("/rigs/{rig:str}/control", control_view),
    APIRoute("/rigs/{rig:str}/checklists", checklists_list_view),
    APIRoute("/rigs/{rig:str}/checklists/{checklist:str}", checklist_view),

    APIRoute("/rigs/{rig:str}/views/speaker-timer", speaker_timer_view),
    APIRoute("/rigs/{rig:str}/views/schedule-table", schedule_table_view),
    APIRoute("/rigs/{rig:str}/views/scene-{view:str}", scene_view),

    APIWebSocketRoute("/rigs/{rig_slug:str}/control/ws", ws_view),
    APIWebSocketRoute("/rigs/{rig_slug:str}/views/{role:str}/ws", ws_view),

    APIRoute("/views/{name:str}/timer", timer_redirect),
]

v1_router = APIRouter(
    routes=v1_routes,
)
