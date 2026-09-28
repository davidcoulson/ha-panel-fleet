"""Small JSON files in /data, written so a crash never leaves half of one."""

import json
import os
from pathlib import Path


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data, private=False):
    """Write beside the file, then swap it in: a reader sees the old file or
    the new one, never a torn one. `private` files (the fleet tokens) are
    created 0600 and stay that way, the temporary copy included."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(data, indent=1)
    if private:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
    else:
        tmp.write_text(text)
    tmp.replace(path)
