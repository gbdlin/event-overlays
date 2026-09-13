from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi_utilities import repeat_every

from .config import settings
from .routes import old_router, update_schedule_ticker, v1_router

if settings.sentry_dsn is not None:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info

        send_default_pii=True,
        enable_logs=True,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
        # Set profile_session_sample_rate to 1.0 to profile 100%
        # of profile sessions.
        profile_session_sample_rate=1.0,
        # Set profile_lifecycle to "trace" to automatically
        # run the profiler on when there is an active transaction
        profile_lifecycle="trace",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await repeat_every(seconds=60)(update_schedule_ticker)()
    yield


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static", follow_symlink=True), name="static")
app.include_router(v1_router, prefix="/v1")
app.include_router(old_router, prefix="")


