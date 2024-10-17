import json
from datetime import datetime, timedelta
from pathlib import Path

import tomlkit
from httpx import get

cache_time = timedelta(minutes=15)
schedule = None

CACHE = Path("programapi-cache.json")
if CACHE.exists():
    with CACHE.open() as cache_fd:
        data = json.load(cache_fd)
        if datetime.fromisoformat(data["fetch_time"]) >= datetime.now() + cache_time:
            schedule = data["schedule"]
            print("Got from cache")
        else:
            print("Cache old")
if not schedule:
    schedule = get("https://programapi24.europython.eu/2024/schedule.json").json()
    with CACHE.open("w") as cache_fd:
        json.dump({"fetch_time": datetime.now().isoformat(), "schedule": schedule}, cache_fd)
    print("Fetched")


days = {
    "2024-07-10": {},
    "2024-07-11": {},
    "2024-07-12": {},
}

avatar_blacklist = {
    "kuba_NsMw534.png",
    "d3da8160dd1848c1194e15df4fb1051c_bFs9Mv0.jpg",
    "Profile_small_qVJUTKd.jpg",
}


def add_to_rooms(day: str, rooms: list[str], event_data):
    for room in rooms:
        room_slug = room.lower().replace(" ", "-")
        days[day].setdefault(room_slug, []).append(event_data)


def add_speaker_session_to_rooms(day: str, rooms: list[str], event, speakers: list | None = None):
    if not speakers:
        speakers = event["speakers"]
    event_data = {
        "start": event["start"],
        "type": "talk",
        "title": event["title"],
        "language": "en",
        "authors": [
            {"name": speaker["name"], "picture_url": speaker.get("avatar") or None}
            for speaker in speakers
        ]
    }
    for author in event_data["authors"]:
        if author["picture_url"] is None or author["picture_url"].rsplit("/", 1)[1] in avatar_blacklist:
            del author["picture_url"]
    add_to_rooms(day, rooms, event_data)


def add_non_speaker_session_to_rooms(day: str, rooms: list[str], event):
    event_data = {
        "start": event["start"],
        "type": "talk",
        "title": event["title"],
        "language": "en",
    }
    add_to_rooms(day, rooms, event_data)


def add_special_to_rooms(special_type: str, day: str, rooms: list[str], event):
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
                            add_non_speaker_session_to_rooms(day, event["rooms"], event)
                    else:
                        add_speaker_session_to_rooms(day, event["rooms"], event)
                elif session_type == "Panel":
                    if len(event['speakers']) > 0:
                        add_speaker_session_to_rooms(day, event["rooms"], event, speakers=[{"name": "Panel"}])
                    else:
                        add_speaker_session_to_rooms(day, event["rooms"], event, speakers=[{"name": "Panel"}])
                else:
                    print(event)


def dump_to_toml(room, day, events, start_date: bool = True, **extra):
    path = Path("config/events/europython/2024") / room / f"{day}.toml"
    data = {
        "event": {
            "name": f"EuroPython 2024 {room} day {day}",
            "number": 2024,
            "schedule": events,
            **extra,
        }
    }
    if start_date:
        data["event"]["starts"] = f"{day}T09:00:00+02:00"

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as toml_fd:
        tomlkit.dump(data, toml_fd)


def dump_all_to_config():
    all_events = []
    for day, rooms in days.items():
        for room, events in rooms.items():
            dump_to_toml(room, day, events)
            all_events.append(
                {
                    "type": "break",
                    "title": f"{room} day {day}",
                }
            )
            all_events += events

    dump_to_toml(
        "",
        "test",
        all_events,
        start_date=False,
        template={"ticker_source": "manual"}
    )


seed_days()
dump_all_to_config()

