# Requestor

Requestor exposes an API to manage access requests.

[View API Documentation](http://petstore.swagger.io/?url=https://raw.githubusercontent.com/uc-cdis/requestor/master/docs/openapi.yaml)

The server is built with [FastAPI](https://fastapi.tiangolo.com/) and packaged with [Poetry](https://poetry.eustace.io/).

## Local installation

### Install Requestor

Install required software:

*   [PostgreSQL](PostgreSQL) 9.6 or above
*   [Python](https://www.python.org/downloads/) 3.7 or above
*   [Poetry](https://poetry.eustace.io/docs/#installation)

Then use `poetry install` to install the dependencies. Before that,
a [virtualenv](https://virtualenv.pypa.io/) is recommended.
If you don't manage your own, Poetry will create one for you
during `poetry install`, and you must activate it with `poetry shell`.

### Create configuration file

Requestor requires a configuration file to run. We have a command line
utility to help you create one based on a default configuration.

The configuration file itself will live outside of this repo (to
prevent accidentally checking in sensitive information like database passwords).

To create a new configuration file from the default configuration:

```bash
python cfg_help.py create
```

This file will be placed in one of the default search directories for Requestor.

To get the exact path where the new configuration file was created, use:

```bash
python cfg_help.py get
```

The file should have detailed information about each of the configuration
variables. **Remember to fill out the new configuration file!**

To use a configuration file in a custom location, you can set the `REQUESTOR_CONFIG_PATH` environment variable.

### Run Requestor

Run database schema migration:

```bash
alembic upgrade head
```

Run the server with auto-reloading:

```bash
python run.py
OR
uvicorn requestor.asgi:app --reload
```

Try out the API at: <http://localhost:8000/docs>.
