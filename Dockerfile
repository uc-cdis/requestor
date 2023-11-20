ARG AZLINUX_BASE_VERSION=master

FROM 707767160287.dkr.ecr.us-east-1.amazonaws.com/gen3/python-build-base:${AZLINUX_BASE_VERSION} as base

ENV appname=requestor
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1

FROM base as builder

RUN source /venv/bin/activate

WORKDIR /$appname

COPY poetry.lock pyproject.toml /$appname/
RUN pip install --upgrade poetry \
    && poetry install --without dev --no-interaction

COPY . /$appname
RUN poetry install --without dev --no-interaction

FROM base
RUN source /venv/bin/activate

COPY --from=builder /venv /venv
COPY --from=builder /$appname /$appname

WORKDIR /$appname

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8

COPY --from=builder /venv /venv
COPY --from=builder /$appname /$appname

WORKDIR /$appname
CMD ["gunicorn", "requestor.asgi:app", "-b", "0.0.0.0:80", "-k", "uvicorn.workers.UvicornWorker"]
