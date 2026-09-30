import os
from pathlib import Path


def set_file_mode(path: Path, mode: int) -> None:
    if os.name != "nt":
        os.chmod(path, mode)
