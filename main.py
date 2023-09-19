import json
from time import time_ns

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from models import Meeting, State, StateException

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.connection_roles: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, role: str):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.connection_roles[websocket] = role

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast_targeted_json(self, data, target_roles):
        await self.broadcast(
            json.dumps(
                {
                    "status": "update",
                    "target_roles": list(target_roles),
                    **data
                }
            ),
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
    }
    match target:
        case "scene-brb":
            brb_template, brb_context = state.brb_screen_content
            return {
                "template": brb_template,
                "context": brb_context,
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
            return {**global_scene_context}  # TODO
        case "timer":
            return {
                **global_scene_context,
            }
        case ("control" | "debug"):
            return {
                "scene-brb": get_state_update_for(state, "scene-brb", "d"),
                "scene-schedule": get_state_update_for(state, "scene-schedule", "c"),
                "scene-presentation": get_state_update_for(state, "scene-presentation", "b"),
                "speaker-timer": get_state_update_for(state, "timer", "a"),
                "message": state.message,
                **global_scene_context,
            }
    return global_scene_context


@app.websocket("/{group:str}/{slug:str}/ws/{role:str}")
async def ws_view(websocket: WebSocket, group: str, slug: str, role: str, control_password: str = None):
    state = State.get_meeting_state(group, slug)
    if role == "control" and control_password != state.meeting.control_password:
        await websocket.close(code=4401, reason="Unauthorized")
        return
    manager = managers.setdefault((group, state.meeting.slug), ConnectionManager())

    await manager.connect(websocket, role)
    await websocket.send_text(json.dumps({"status": "init", **get_state_update_for(state, role, "init")}))

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
                                notify.add("scene-brb")
                                if state.increment()[1]:
                                    notify.add("scene-schedule")
                                else:
                                    notify.add("scene-presentation")
                            case {"action": "meeting.untick"}:
                                notify.add("scene-brb")
                                if state.decrement()[1]:
                                    notify.add("scene-presentation")
                                else:
                                    notify.add("scene-schedule")
                            case {"action": "stream.set-message", "message": message}:
                                notify.add("scene-brb")
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
                        for target_role in ("scene-brb", "scene-schedule", "scene-presentation", "timer", "control"):
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


@app.get("/{group:str}/{slug:str}/scene-{scene:str}.html")
async def scene_view(request: Request, group: str, slug: str, scene: str):
    return templates.TemplateResponse(
        "scene.html",
        {
            "request": request,
            "meeting": Meeting.get_meeting_config(group, slug),
            "group": group,
            "slug": slug,
            "scene": scene,
        },
    )


@app.get("/{group:str}/{slug:str}/control.html")
async def control_view(request: Request, group: str, slug: str, control_password: str):
    return templates.TemplateResponse(
        "control.html",
        {
            "request": request,
            "meeting": Meeting.get_meeting_config(group, slug),
            "group": group,
            "slug": slug,
            "control_password": control_password,
        },
    )


@app.get("/{group:str}/{slug:str}/speaker-timer.html")
async def speaker_timer_view(request: Request, group: str, slug: str):
    return templates.TemplateResponse(
        "speaker-timer.html",
        {
            "request": request,
            "meeting": Meeting.get_meeting_config(group, slug),
            "group": group,
            "slug": slug,
        },
    )
