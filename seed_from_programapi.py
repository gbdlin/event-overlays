import json
from pathlib import Path

import tomlkit
from httpx import get

CACHE = Path("programapi-cache.json")
if CACHE.exists():
    with CACHE.open() as cache_fd:
        schedule = json.load(cache_fd)
else:
    schedule = get("https://programapi24.europython.eu/2024/schedule.json").json()
    with CACHE.open("w") as cache_fd:
        json.dump(schedule, cache_fd)


days = {
    "2024-07-10": {},
    "2024-07-11": {},
    "2024-07-12": {},
}


def add_to_rooms(day: str, rooms: list[str], event_data):
    for room in rooms:
        room_slug = room.lower().replace(" ", "-")
        days[day].setdefault(room_slug, []).append(event_data)


def add_speaker_session_to_rooms(day: str, rooms: list[str], event):
    event_data = {
        "start": event["start"],
        "type": "talk",
        "title": event["title"],
        "language": "en",
        "authors": [
            {"name": speaker["name"], "picture_url": speaker["avatar"] or None}
            for speaker in event["speakers"]
        ]
    }
    for author in event_data["authors"]:
        if author["picture_url"] is None:
            del author["picture_url"]
    add_to_rooms(day, rooms, event_data)


def add_non_speaker_session_to_rooms(day: str, rooms: list[str], event):
    ...
    # add_to_rooms(day, rooms, event_data)


def add_special_to_rooms(special_type: str, day: str, rooms: list[str], event):
    ...
    event_data = {
        "start": event["start"],
        "type": special_type,
        "title": event["title"],
    }
    add_to_rooms(day, rooms, event_data)


def seed_days():
    for day in days:
        for event in schedule['days'][day]['events']:
            event_type = event.get("event_type")
            session_type = event.get('session_type')

            if event_type == 'break':
                add_special_to_rooms("break", day, event["rooms"], event)
            else:
                if session_type == "Poster":
                    continue
                elif session_type == "Announcements":
                    if "Registration & Welcome" in event["title"]:
                        continue
                    else:
                        add_special_to_rooms("announcement", day, event["rooms"], event)
                elif session_type in ("Keynote", "Talk", "Talk (long session)", "Sponsored"):
                    if len(event['speakers']) == 0:
                        if "lightning" in event["title"].lower():
                            add_special_to_rooms("lightning-talks", day, event["rooms"], event)
                        else:
                            print(event)
                    else:
                        add_speaker_session_to_rooms(day, event["rooms"], event)
                elif session_type == "Panel":
                    if len(event['speakers']) > 0:
                        print(event)
                        continue
                    else:
                        add_non_speaker_session_to_rooms(day, event["rooms"], event)
                else:
                    print(event)


def dump_to_toml(room, day, events):
    path = Path("config/events/europython/2024") / room / f"{day}.toml"
    data = {
        "meeting": {
            "name": "EuroPython 2024 Forum Hall day 1",
            "number": 2024,
            "starts": f"{day}T09:00:00+02:00",
            "schedule": events,
        }
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as toml_fd:
        tomlkit.dump(data, toml_fd)


def dump_all_to_config():
    for day, rooms in days.items():
        for room, events in rooms.items():
            dump_to_toml(room, day, events)


seed_days()
dump_all_to_config()

