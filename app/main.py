from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi_utilities import repeat_at

from .routes import old_router, update_schedule_ticker, v1_router


app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/v1", v1_router, name="v1")
app.mount("", old_router, name="old")

app.on_event("startup")(repeat_at(cron="* * * * *")(update_schedule_ticker))
