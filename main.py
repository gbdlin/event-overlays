import json
from time import time_ns
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic_core import to_json
from starlette.responses import RedirectResponse

from models import Meeting, RigConfig, State, StateException, TimerConfig, TimerState
from utils.file_sha import get_file_sha

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

def global_ctx(request):
    return {
        "get_file_sha": get_file_sha,
    }

templates = Jinja2Templates(directory="templates", context_processors=[global_ctx])


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.connection_roles: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, role: str):
        self.active_connections.append(websocket)
        self.connection_roles[websocket] = role

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast_targeted_json(self, data, target_roles):
        await self.broadcast(
            to_json(
                {
                    "status": "update",
                    "target_roles": list(target_roles),
                    **data
                }
            ).decode(),
            target_roles,
        )

    async def broadcast(self, text: str, roles_to_notify: set[str]):
        for connection in list(self.active_connections):
            role = self.connection_roles[connection]
            if role not in roles_to_notify:
                continue
            try:
                await connection.send_text(text)
            except RuntimeError:
                self.active_connections.remove(connection)


managers: dict[tuple[str, str], ConnectionManager] = {}


def get_state_update_for(state: State, target: str, command: str | None = None) -> dict:
    global_scene_context = {
        "current_state": state.current_state,
        "next_state": state.next_state,
        "previous_state": state.previous_state,
        "for": target,
        "timer": {
            "target": state.timer.target,
            "started_at": state.timer.started_at,
            "offset": state.timer.offset,
            "message": state.timer.message,
        },
        "command": command,
        "meeting": state.meeting,
    }
    match target:
        case "scene-title":
            next_template, next_context = state.title_screen_content
            return {
                "template": next_template,
                "context": next_context,
                **global_scene_context,
            }
        case "scene-brb":
            brb_template, brb_context = state.brb_screen_content
            return {
                "template": brb_template,
                "context": brb_context,
                **global_scene_context,
            }
        case "scene-hybrid":
            hybrid_template, hybrid_context = state.hybrid_screen_content
            return {
                "template": hybrid_template,
                "context": hybrid_context,
                **global_scene_context,
            }
        case "scene-schedule":
            schedule_template, schedule_context = state.schedule_screen_content
            return {
                "template": schedule_template,
                "context": schedule_context,
                **global_scene_context,
            }
        case "scene-presentation":
            presentation_template, presentation_context = state.presentation_screen_content
            return {
                "template": presentation_template,
                "context": presentation_context,
                **global_scene_context,
            }
        case "timer":
            return {
                **global_scene_context,
            }
        case "schedule":
            return {
                "schedule": state.schedule,
                "extra_columns": state.schedule_extra_columns,
                **global_scene_context,
            }
        case ("control" | "debug"):
            return {
                "scene-brb": get_state_update_for(state, "scene-brb", "d"),
                "scene-title": get_state_update_for(state, "scene-title", "d"),
                "scene-hybrid": get_state_update_for(state, "scene-hybrid", "d"),
                "scene-schedule": get_state_update_for(state, "scene-schedule", "c"),
                "scene-presentation": get_state_update_for(state, "scene-presentation", "b"),
                "speaker-timer": get_state_update_for(state, "timer", "a"),
                "message": state.message,
                **global_scene_context,
            }
    return global_scene_context


@app.get("/t/{timer_slug:str}/speaker.html")
async def redirect(timer_slug: str):
    timer_config = TimerConfig.get_timer_config(timer_slug)
    return RedirectResponse(f"/{timer_config.rig}/speaker-timer.html")


async def get_ws_state(
    websocket: WebSocket,
    role: str,
    rig_slug: str | None = None,
    control_password: str | None = None,
) -> tuple[State, ConnectionManager, RigConfig] | None:
    rig = RigConfig.get_rig_config(rig_slug)
    if rig is None:
        await websocket.close(code=4404, reason="NotFound")
        return None
    if role == "control" and control_password != rig.control_password:
        await websocket.close(code=4401, reason="Unauthorized")
        return None
    await websocket.accept()

    group, slug = rig.meeting_group, rig.meeting_slug
    state = State.get_meeting_state(group, slug)
    manager = managers.setdefault((group, state.meeting.slug), ConnectionManager())
    return state, manager, rig


@app.websocket("/{rig_slug:str}/ws/{role:str}")
async def ws_view(
    websocket: WebSocket,
    role: str,
    state_and_manager: Annotated[tuple[State, ConnectionManager, RigConfig] | None, Depends(get_ws_state)],
):
    if state_and_manager is None:
        return
    state, manager, rig = state_and_manager

    await manager.connect(websocket, role)
    await websocket.send_text(
        to_json(
            {"status": "init", "role": role, **get_state_update_for(state, role, "init")},
        ).decode()
    )

    try:
        async for command in websocket.iter_json():
            notify = {"control", "debug"}
            server_time = time_ns() // 1_000_000
            try:
                match command:
                    case {"action": "ntc.sync", "client_time": client_time}:
                        await websocket.send_json(
                            {"status": "ntc.sync", "server_time": server_time, "offset": server_time - client_time},
                        )
                        continue  # we're not notifying others
                    case _ if role == "control":
                        match command:
                            case {"action": "meeting.tick"}:
                                notify.add("scene-hybrid")
                                notify.add("schedule")
                                if state.increment()[1]:
                                    notify.add("scene-schedule")
                                else:
                                    notify.add("scene-presentation")
                                    notify.add("scene-title")
                            case {"action": "meeting.untick"}:
                                notify.add("scene-hybrid")
                                notify.add("schedule")
                                if state.decrement()[1]:
                                    notify.add("scene-presentation")
                                    notify.add("scene-title")
                                else:
                                    notify.add("scene-schedule")
                            case {"action": "stream.set-message", "message": message}:
                                notify.add("scene-brb")
                                notify.add("scene-hybrid")
                                notify.add("scene-schedule")
                                notify.add("scene-presentation")
                                state.message = message
                            case {"action": "timer.set", "time": set_time}:
                                notify.add("timer")
                                state.timer.target = set_time
                            case {"action": "timer.start"}:
                                if state.timer.started_at is not None:
                                    await websocket.send_json({"status": "error", "error": f"Timer already started"})
                                    continue
                                notify.add("timer")
                                state.timer.started_at = server_time
                            case {"action": "timer.stop"}:
                                if state.timer.started_at is None:
                                    await websocket.send_json({"status": "error", "error": f"Timer already stopped"})
                                    continue
                                notify.add("timer")
                                state.timer.offset += server_time - state.timer.started_at
                                state.timer.started_at = None
                            case {"action": "timer.reset"}:
                                notify.add("timer")
                                state.timer.offset = 0
                                if state.timer.started_at is not None:
                                    state.timer.started_at = server_time
                            case {"action": "timer.set-message", "message": message}:
                                notify.add("timer")
                                state.timer.message = message
                            case {"action": "timer.flash"}:
                                await manager.broadcast_targeted_json(
                                    {
                                        "status": "timer.flash",
                                    },
                                    {"timer", "control", "debug"},
                                )
                                continue
                            case {"action": "config.refresh"}:
                                notify.add("scene-brb")
                                notify.add("scene-hybrid")
                                notify.add("scene-title")
                                notify.add("scene-schedule")
                                notify.add("scene-presentation")
                                notify.add("schedule")
                                notify.add("control")
                                state.meeting = Meeting.get_meeting_config(
                                    group=state.meeting.group,
                                    slug=state.meeting.slug,
                                )
                                state.fix_ticker()
                            case {"action": other}:
                                print(f"action {other} unknown")
                                await websocket.send_json({"status": "error", "error": f"Unknown action {other}"})
                                continue
                            case invalid:
                                print(f"invalid packet {invalid}")
                                await websocket.send_json(
                                    {"status": "error", "error": f"invalid packet", "packet": invalid},
                                )
                                continue
                        await websocket.send_json({"status": "success"})
                        for target_role in (
                            "scene-brb",
                            "scene-title",
                            "scene-hybrid",
                            "scene-schedule",
                            "scene-presentation",
                            "timer",
                            "control",
                            "schedule",
                        ):
                            if target_role in notify:
                                await manager.broadcast_targeted_json(
                                    get_state_update_for(state, target_role, command),
                                    notify & {target_role, "debug"},
                                )
            except StateException as ex:
                await websocket.send_json(
                    {"status": "error", "detail": ex.detail},
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/{rig:str}/scene-{scene:str}.html")
@app.get("/--/s/{path:path}/{state:str}/scene-{scene:str}.html")
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
    return templates.TemplateResponse(
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


@app.get("/{rig:str}/control.html")
async def control_view(request: Request, rig: str, control_password: str):
    return templates.TemplateResponse(
        "control.html",
        {
            "request": request,
            "rig": rig,
            "control_password": control_password,
        },
    )


@app.get("/{rig:str}/speaker-timer.html")
async def speaker_timer_view(request: Request, rig: str, name: str | None = None):
    return templates.TemplateResponse(
        "speaker-timer.html",
        {
            "request": request,
            "rig": rig,
            "name": name,
        },
    )


@app.get("/{rig:str}/schedule-table.html")
async def schedule_table_view(request: Request, rig: str):
    return templates.TemplateResponse(
        "schedule-table.html",
        {
            "request": request,
            "rig": rig,
        }
    )
