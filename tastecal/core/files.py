"""Writing cache files safely when several runs share one cache folder."""
from __future__ import annotations

import os
import uuid


def atomic_write(path: str, text: str) -> bool:
    """Write `text` to `path` so that no reader ever sees half a file: write a temporary file with a name of its own,
    then move it into place. Two runs writing the same entry at once both succeed; the last one wins, and both wrote
    the same answer. Returns False (and leaves no temporary file) if the write failed."""
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:      # Windows: another run has the file open for reading right now
                import time
                time.sleep(0.05 * (attempt + 1))
        return False
    except OSError:
        return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
