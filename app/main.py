from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import old_router, v1_router

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/v1", v1_router, name="v1")
app.mount("", old_router, name="old")
