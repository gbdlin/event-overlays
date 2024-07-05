from time import time_ns
from typing import Annotated

from fastapi import Depends
from fastapi.websockets import WebSocket, WebSocketDisconnect
from pydantic_core import to_json

from ..models import Meeting, RigConfig, State, StateException
from ..state import ConnectionManager, get_state_update_for, get_ws_state, managers


async def notify_roles(notify: set[str], manager: ConnectionManager, state: State, command: str):
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
                                state.meeting = Meeting.get_meeting_config(path=str(state.meeting.path))
                                state.fix_ticker()
                            case {"action": "config.force-reload"}:
                                notify.add("scene-brb")
                                notify.add("scene-hybrid")
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
                        await notify_roles(notify, manager, state, command)
                        await update_schedule_ticker()
            except StateException as ex:
                await websocket.send_json(
                    {"status": "error", "detail": ex.detail},
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def update_schedule_ticker():
    notify = {"scene-hybrid", "schedule", "scene-schedule", "scene-presentation", "scene-title"}

    for meeting_path, manager in managers.items():
        state = State.get_meeting_state(path=meeting_path)
        await notify_roles(notify, manager, state, "meeting.tick")
