FROM quay.io/cdis/python:python3.9-buster-2.0.0 AS base

FROM base AS builder
RUN pip install --upgrade pip poetry
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential gcc make musl-dev libffi-dev libssl-dev git curl

COPY . /src/
WORKDIR /src
RUN python -m venv /env && . /env/bin/activate && pip install --upgrade pip && poetry install --no-dev --no-interaction

FROM base
COPY --from=builder /env /env
COPY --from=builder /src /src
WORKDIR /src
CMD ["/env/bin/gunicorn", "requestor.asgi:app", "-b", "0.0.0.0:80", "-k", "uvicorn.workers.UvicornWorker"]
