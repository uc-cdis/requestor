ARG AZLINUX_BASE_VERSION=master

# Base stage with python-build-base
FROM quay.io/cdis/python-build-base:${AZLINUX_BASE_VERSION} as base

# Comment this in, and comment out the line above, if quay is down
# FROM 707767160287.dkr.ecr.us-east-1.amazonaws.com/gen3/python-build-base:${AZLINUX_BASE_VERSION} as base

ENV appname=requestor
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1

WORKDIR /${appname}

# create gen3 user
# Create a group 'gen3' with GID 1000 and a user 'gen3' with UID 1000
RUN groupadd -g 1000 gen3 && \
    useradd -m -s /bin/bash -u 1000 -g gen3 gen3  && \
    chown -R gen3:gen3 /$appname && \
    chown -R gen3:gen3 /venv


# Builder stage
FROM base as builder

USER gen3


RUN python -m venv /venv

COPY poetry.lock pyproject.toml alembic.ini README.md /${appname}/

RUN pip install poetry && \
    poetry install -vv --only main --no-interaction

COPY --chown=gen3:gen3 ./src /$appname
COPY --chown=gen3:gen3 ./migrations /$appname/migrations
COPY --chown=gen3:gen3 ./deployment/wsgi/wsgi.py /$appname/deployment/wsgi/wsgi.py
COPY --chown=gen3:gen3 ./deployment/wsgi/gunicorn.conf.py /$appname/deployment/wsgi/gunicorn.conf.py

# Run poetry again so this app itself gets installed too
RUN poetry install --without dev --no-interaction

# Final stage
FROM base

COPY --from=builder /venv /venv
COPY --from=builder /$appname /$appname


# Switch to non-root user 'gen3' for the serving process
USER gen3

RUN source /venv/bin/activate

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8

CMD ["gunicorn", "-c", "deployment/wsgi/gunicorn.conf.py"]
