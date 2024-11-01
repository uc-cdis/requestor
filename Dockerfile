ARG AZLINUX_BASE_VERSION=master

FROM quay.io/cdis/python-nginx-al:feat_python-nginx AS base

# FROM 707767160287.dkr.ecr.us-east-1.amazonaws.com/gen3/python-nginx-al2:feat_python-nginx AS base

ENV appname=requestor

WORKDIR /${appname}

RUN chown -R gen3:gen3 /$appname

# Builder stage
FROM base AS builder

USER gen3

COPY poetry.lock pyproject.toml alembic.ini README.md /${appname}/

RUN poetry install -vv --only main --no-interaction

COPY --chown=gen3:gen3 ./src /$appname
COPY --chown=gen3:gen3 ./migrations /$appname/migrations
COPY --chown=gen3:gen3 ./deployment/wsgi/wsgi.py /$appname/deployment/wsgi/wsgi.py
COPY --chown=gen3:gen3 ./deployment/wsgi/gunicorn.conf.py /$appname/deployment/wsgi/gunicorn.conf.py
COPY --chown=gen3:gen3 ./dockerrun.bash /$appname/dockerrun.bash

# Run poetry again so this app itself gets installed too
RUN poetry install --no-interaction

# Final stage
FROM base

COPY --from=builder /$appname /$appname

# Switch to non-root user 'gen3' for the serving process
USER gen3

WORKDIR /$appname

CMD ["/bin/bash", "-c", "/requestor/dockerrun.bash"]
