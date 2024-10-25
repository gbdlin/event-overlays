from fastapi import Request

from ..models import Meeting
from ..template_renderer import renderer


async def demo_view(request: Request, path: str):
    meeting = Meeting.get_meeting_config(path=path)

    return renderer.TemplateResponse(
        "demo.html",
        {
            "request": request,
            "meeting": meeting,
        }
    )
