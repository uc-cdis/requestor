#!/bin/bash

nginx
poetry run gunicorn -c "/requestor/deployment/wsgi/gunicorn.conf.py" requestor.asgi:app
