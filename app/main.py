from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi_utilities import repeat_every

from .routes import old_router, update_schedule_ticker, v1_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await repeat_every(seconds=60)(update_schedule_ticker)()
    yield


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/v1", v1_router, name="v1")
app.mount("", old_router, name="old")


