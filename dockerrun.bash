#!/bin/bash

nginx
gunicorn -c "/requestor/deployment/wsgi/gunicorn.conf.py" requestor.asgi:app
