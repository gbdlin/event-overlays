from fastapi import APIRouter

from .control import checklist_view, control_view, checklists_list_view
from .demo import demo_view
from .scenes import old_scene_view, scene_view
from .timers import speaker_timer_view, timer_redirect
from .utils import schedule_table_view
from .websocket import update_schedule_ticker, ws_view

old_router = APIRouter()

old_router.add_api_route("/--/s/{path:path}/{state:str}/scene-{scene:str}.html", old_scene_view)
old_router.add_api_route("/{rig:str}/scene-{scene:str}.html", old_scene_view)

old_router.add_api_websocket_route("/{rig_slug:str}/ws/{role:str}", ws_view)

old_router.add_api_route("/t/{timer_slug:str}/speaker.html", timer_redirect)
old_router.add_api_route("/{rig:str}/speaker-timer.html", speaker_timer_view)

old_router.add_api_route("/{rig:str}/control.html", control_view)

old_router.add_api_route("/{rig:str}/schedule-table.html", schedule_table_view)


v1_router = APIRouter()

v1_router.add_api_route("/events/{path:path}/demo", demo_view)
v1_router.add_api_route("/events/{path:path}/views/{view:str}/{state:str}", scene_view)

v1_router.add_api_route("/rigs/{rig:str}/control", control_view)
v1_router.add_api_route("/rigs/{rig:str}/checklists", checklists_list_view)
v1_router.add_api_route("/rigs/{rig:str}/checklists/{checklist:str}", checklist_view)

v1_router.add_api_route("/rigs/{rig:str}/views/speaker-timer", speaker_timer_view)
v1_router.add_api_route("/rigs/{rig:str}/views/schedule-table", schedule_table_view)
v1_router.add_api_route("/rigs/{rig:str}/views/scene-{view:str}", scene_view)

v1_router.add_api_websocket_route("/rigs/{rig_slug:str}/control/ws", ws_view)
v1_router.add_api_websocket_route("/rigs/{rig_slug:str}/views/{role:str}/ws", ws_view)

v1_router.add_api_route("/views/{name:str}/timer", timer_redirect)
