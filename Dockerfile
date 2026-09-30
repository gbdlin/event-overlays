# SCSS builder
FROM michalklempa/dart-sass:latest as scss-builder

RUN mkdir -p /code/static
WORKDIR /code
COPY ./static /code/static

RUN ["/opt/dart-sass/sass", "/code/static/"]

# Python app
FROM python:3.14-slim-trixie

ENV PYTHONBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT="/usr/local"
ENV UV_SYSTEM_PYTHON=true

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/

WORKDIR /code

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
  uv sync --no-dev --no-install-project --locked

ARG BUILD_COMMIT_SHA
ENV BUILD_COMMIT_SHA ${BUILD_COMMIT_SHA:-}

#RUN --mount=type=cache,target=/root/.cache/uv \
#    --mount=type=bind,source=uv.lock,target=uv.lock \
#    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
#  if [ "${BUILD_COMMIT_SHA}" = "localdev" ]; then \
#    poetry install --no-interaction --no-root --only=dev; \
#  fi

# All directories are unpacked. Due to it, each file must be specified separately!
COPY . /code
COPY --from=scss-builder /code/static/*.css static/
COPY --from=scss-builder /code/static/*.css.map static/

ENV PYTHONUNBUFFERED=0

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
