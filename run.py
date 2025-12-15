"""
Usage:
- Run app: python run.py
- Generate openapi docs: python run.py openapi
"""

import os
import sys
import uvicorn
import yaml

from requestor.app import app_init


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))


# TODO get run.py working
#   File "/Users/paulineribeyre/Projects/requestor/src/requestor/models.py", line 119, in get_data_access_layer
#     async with async_sessionmaker_instance() as session:
#                ~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
# TypeError: 'NoneType' object is not callable
if __name__ == "__main__":
    if sys.argv[-1] == "openapi":
        schema = app_init().openapi()
        path = os.path.join(CURRENT_DIR, "docs/openapi.yaml")
        yaml.Dumper.ignore_aliases = lambda *args: True
        with open(path, "w+") as f:
            yaml.dump(schema, f, default_flow_style=False)
        print(f"Saved docs at {path}")
    else:
        uvicorn.run("requestor.asgi:app", reload=True)
