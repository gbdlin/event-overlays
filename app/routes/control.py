from fastapi import APIRouter, Request
from ..template_renderer import renderer

router = APIRouter()


async def control_view(request: Request, rig: str, control_password: str):
    return renderer.TemplateResponse(
        "control.html",
        {
            "request": request,
            "rig": rig,
            "control_password": control_password,
        },
    )
