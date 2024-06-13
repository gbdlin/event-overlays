import json

from fastapi.templating import Jinja2Templates
from pydantic_core import to_jsonable_python

from .utils.file_sha import get_file_sha


def global_ctx(request):
    return {
        "get_file_sha": get_file_sha,
        "jsonable": to_jsonable_python,
    }


def json_dumps(obj, *args, **kwargs):
    return json.dumps(to_jsonable_python(obj), *args, **kwargs)


renderer = Jinja2Templates(directory="templates", context_processors=[global_ctx])
renderer.env.policies["json.dumps_function"] = json_dumps
renderer.env.policies["json.dumps_kwargs"] = {}
