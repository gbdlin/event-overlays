from base64 import urlsafe_b64encode
from time import time_ns
from typing import Annotated
from hashlib import sha256

from fastapi import Depends
from fastapi.websockets import WebSocket, WebSocketDisconnect
from pydantic_core import to_json

from ..models import Event, RigConfig, State, StateException
from ..state import ConnectionManager, get_state_update_for, get_ws_state, managers, rig_views

from app.config import config


async def notify_roles(
    notify: set[str],
    manager: ConnectionManager,
    state: State,
    command: str,
    rig_assigned_views: dict | None = None,
) -> None:
    for target_role in (
        "scene-brb",
        "scene-title",
        "scene-schedule",
        "scene-presentation",
        "timer",
        "control",
        "schedule",
    ):
        if target_role in notify:
            await manager.broadcast_targeted_json(
                get_state_update_for(state, target_role, command, rig_assigned_views),
                notify & {target_role, "debug"},
            )



async def ws_view(
    websocket: WebSocket,
    role: str,
    state_and_manager: Annotated[tuple[State, ConnectionManager, RigConfig] | None, Depends(get_ws_state)],
    view_name: str | None = None,
):
    if state_and_manager is None:
        return
    state, manager, rig = state_and_manager

    assigned_views = rig_views.setdefault(rig.slug, {})

    await manager.connect(websocket, role)
    if view_name is not None:
        stream_id = urlsafe_b64encode(
            sha256(f"{rig.slug}-{view_name}-{config.secret_key}".encode()).digest()
        ).decode().rstrip("=").replace("-", "").replace("_", "")
        stream_pwd = urlsafe_b64encode(
            sha256(f"{rig.slug}-{view_name}-{rig.control_password}-{config.secret_key}".encode()).digest()
        ).decode().rstrip("=").replace("-", "").replace("_", "")
        assigned_views[view_name] = (
            websocket,
            role,
            stream_id,
            stream_pwd,
        )

        await notify_roles({"control", "debug"}, manager, state, "views.assigned", assigned_views)
    else:
        stream_id = None
        stream_pwd = None
    await websocket.send_text(
        to_json(
            {
                "status": "init",
                "rig": rig.slug,
                "role": role,
                **get_state_update_for(
                    state,
                    role,
                    "init",
                    assigned_views,
                ),
                **({
                    "stream": {
                        "id": stream_id,
                        "pwd": stream_pwd,
                    },
                } if view_name is not None and role == "timer" else {})
            },
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
                            case {"action": "event.tick"}:
                                notify.add("schedule")
                                if state.increment()[1]:
                                    notify.add("scene-schedule")
                                else:
                                    notify.add("scene-presentation")
                                    notify.add("scene-title")
                            case {"action": "event.untick"}:
                                notify.add("schedule")
                                if state.decrement()[1]:
                                    notify.add("scene-presentation")
                                    notify.add("scene-title")
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
                            case {"action": "config.refresh"}:
                                notify.add("scene-brb")
                                notify.add("scene-title")
                                notify.add("scene-schedule")
                                notify.add("scene-presentation")
                                notify.add("schedule")
                                notify.add("control")
                                state.event = Event.get_event_config(path=str(state.event.path))
                                state.fix_ticker()
                            case {"action": "config.force-reload"}:
                                notify.add("scene-brb")
                                notify.add("scene-title")
                                notify.add("scene-schedule")
                                notify.add("scene-presentation")
                                notify.add("schedule")
                                notify.add("control")
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
                        await notify_roles(notify, manager, state, command, assigned_views)
                        await update_schedule_ticker()
            except StateException as ex:
                await websocket.send_json(
                    {"status": "error", "detail": ex.detail},
                )
    except WebSocketDisconnect:
        print("Connection closed by remote host")
        manager.disconnect(websocket)
        if view_name is not None:
            assigned_views.pop(view_name, None)

        await notify_roles({"control", "debug"}, manager, state, "views.unassigned", assigned_views)


async def update_schedule_ticker():
    notify = {"schedule", "scene-schedule", "scene-presentation", "scene-title"}

    for event_path, manager in managers.items():
        state = State.get_event_state(path=event_path)
        await notify_roles(notify, manager, state, "event.tick")
