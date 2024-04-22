from fastapi.templating import Jinja2Templates

from .utils.file_sha import get_file_sha


def global_ctx(request):
    return {
        "get_file_sha": get_file_sha,
    }


renderer = Jinja2Templates(directory="templates", context_processors=[global_ctx])
