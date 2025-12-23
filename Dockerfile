ARG AZLINUX_BASE_VERSION=3.13-pythonnginx

FROM quay.io/cdis/amazonlinux-base:${AZLINUX_BASE_VERSION} AS base

ENV appname=requestor

WORKDIR /${appname}

RUN chown -R gen3:gen3 /${appname}

# Builder stage
FROM base AS builder

USER gen3

COPY poetry.lock pyproject.toml alembic.ini README.md /${appname}/

RUN poetry install -vv --without dev --no-interaction

COPY --chown=gen3:gen3 ./src /${appname}
COPY --chown=gen3:gen3 ./migrations /${appname}/migrations
COPY --chown=gen3:gen3 ./deployment/wsgi/wsgi.py /${appname}/deployment/wsgi/wsgi.py
COPY --chown=gen3:gen3 ./deployment/wsgi/gunicorn.conf.py /${appname}/deployment/wsgi/gunicorn.conf.py
COPY --chown=gen3:gen3 ./dockerrun.bash /${appname}/dockerrun.bash

# Run poetry again so this app itself gets installed too
RUN poetry install --no-interaction --without dev

# Final stage
FROM base

COPY --from=builder /${appname} /${appname}
COPY --from=builder /venv /venv

# Switch to non-root user 'gen3' for the serving process
USER gen3

WORKDIR /${appname}

CMD ["/bin/bash", "-c", "/requestor/dockerrun.bash"]
