from fastapi import Request

from ..models import Event
from ..template_renderer import renderer


async def demo_view(request: Request, path: str):
    event = Event.get_event_config(path=path)

    return renderer.TemplateResponse(
        "demo.html",
        {
            "request": request,
            "event": event,
        }
    )
