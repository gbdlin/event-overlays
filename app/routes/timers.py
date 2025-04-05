from fastapi import Request
from fastapi.responses import RedirectResponse

from ..models import TimerConfig
from ..template_renderer import renderer


async def timer_redirect(timer_slug: str):
    timer_config = TimerConfig.get_timer_config(timer_slug)
    return RedirectResponse(f"/{timer_config.rig}/speaker-timer.html?preview={int(timer_config.with_preview)}")


async def speaker_timer_view(request: Request, rig: str, name: str | None = None, preview: bool = False):
    return renderer.TemplateResponse(
        "speaker-timer.html",
        {
            "request": request,
            "rig": rig,
            "name": name,
            "preview": preview,
        },
    )
