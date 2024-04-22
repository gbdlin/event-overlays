from base64 import urlsafe_b64encode
from hashlib import sha256
from pathlib import PurePath


def get_file_sha(filename: PurePath | str, trim: int = 7) -> str:
    with open(filename, "rb") as fd:
        return urlsafe_b64encode(sha256(fd.read()).digest())[:trim].decode()