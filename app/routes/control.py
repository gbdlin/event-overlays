import secrets
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Path
from fastapi.params import Depends
from starlette.status import HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND

from ..models import RigConfig
from ..template_renderer import renderer

router = APIRouter()


async def get_rig(
    rig: Annotated[str, Path(validation_alias="rig")],
    control_password: str,
):
    rig_config = RigConfig.get_rig_config(rig)
    if rig_config is None:
        raise HTTPException(HTTP_404_NOT_FOUND, "rig not found")
    if not secrets.compare_digest(rig_config.control_password, control_password):
        raise HTTPException(HTTP_403_FORBIDDEN, "wrong password")

    return rig_config


async def control_view(request: Request, rig: str, control_password: str):
    return renderer.TemplateResponse(
        "control.html",
        {
            "request": request,
            "rig": rig,
            "control_password": control_password,
        },
    )


async def checklists_list_view(
    request: Request,
    rig: Annotated[RigConfig, Depends(get_rig)],
):
    return renderer.TemplateResponse(
        "checklists_list.html",
        {
            "request": request,
            "rig": rig,
        },
    )


async def checklist_view(
    request: Request,
    rig: Annotated[RigConfig, Depends(get_rig)],
    checklist: Annotated[str, Path(validation_alias="checklist")],
):
    return renderer.TemplateResponse(
        "checklist.html",
        {
            "request": request,
            "rig": rig,
            "checklist": rig.checklists[checklist]
        },
    )
