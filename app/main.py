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

app.mount("/static", StaticFiles(directory="static", follow_symlink=True), name="static")
app.include_router(v1_router, prefix="/v1")
app.include_router(old_router, prefix="")


