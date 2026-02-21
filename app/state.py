import secrets
from asyncio import Event

from fastapi.websockets import WebSocket
from pydantic_core import to_json

from app.models import RigConfig, State


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


managers: dict[str, ConnectionManager] = {}
assignable_views: dict[str, tuple[WebSocket, Event]] = {}
rig_views: dict[str, dict[str, tuple[WebSocket, str, str, str]]] = {}


def get_state_update_for(
    state: State,
    target: str,
    command: str | None = None,
    rig_assigned_views: dict | None = None,
) -> dict:
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
        "state": state,
        "command": command,
        "event": state.event,
    }
    if rig_assigned_views is not None:
        prepared_views = {slug: (role, stream, pwd) for slug, (_, role, stream, pwd) in rig_assigned_views.items()}
    else:
        prepared_views = None
    match target:
        case "scene-title":
            next_template, next_context = state.title_screen_content
            return {
                "template": next_template,
                "context": next_context,
                "view": state.get_view_for("scene-title"),
                **global_scene_context,
            }
        case "scene-brb":
            brb_template, brb_context = state.brb_screen_content
            return {
                "template": brb_template,
                "context": brb_context,
                "view": state.get_view_for("scene-brb"),
                **global_scene_context,
            }
        case "scene-schedule":
            schedule_template, schedule_context = state.schedule_screen_content
            return {
                "template": schedule_template,
                "context": schedule_context,
                "view": state.get_view_for("scene-schedule"),
                **global_scene_context,
            }
        case "scene-presentation":
            presentation_template, presentation_context = state.presentation_screen_content
            return {
                "template": presentation_template,
                "context": presentation_context,
                "view": state.get_view_for("scene-presentation"),
                **global_scene_context,
            }
        case str(view) if view.startswith("scene-") or view.startswith("signage-"):
            return {
                "context": state.global_context,
                "view": state.get_view_for(view),
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
                "scene-schedule": get_state_update_for(state, "scene-schedule", "c"),
                "scene-presentation": get_state_update_for(state, "scene-presentation", "b"),
                "speaker-timer": get_state_update_for(state, "timer", "a"),
                "message": state.message,
                "assigned_views": prepared_views,
                "schedule": state.schedule,
                "extra_columns": state.schedule_extra_columns,
                **global_scene_context,
            }
    return global_scene_context


async def get_ws_state(
    websocket: WebSocket,
    role: str,
    rig_slug: str,
    control_password: str | None = None,
) -> tuple[State, ConnectionManager, RigConfig] | None:
    rig = RigConfig.get_rig_config(rig_slug)
    if rig is None:
        await websocket.close(code=4404, reason="NotFound")
        return None
    if role == "control" and not secrets.compare_digest(control_password, rig.control_password):
        await websocket.close(code=4401, reason="Unauthorized")
        return None
    await websocket.accept()

    manager = managers.setdefault(rig.event_path, ConnectionManager())
    state = State.get_event_state(path=rig.event_path)
    return state, manager, rig
