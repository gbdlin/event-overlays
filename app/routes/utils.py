from fastapi import Request
from ..template_renderer import renderer


async def schedule_table_view(request: Request, rig: str):
    return renderer.TemplateResponse(
        "schedule-table.html",
        {
            "request": request,
            "rig": rig,
        }
    )
