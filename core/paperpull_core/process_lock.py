"""An OS lock, released on exit even if the owning process is killed."""
from pathlib import Path
import os


class ProcessLock:
    def __init__(self, path):
        self.file = open(path, "a+b")
        try:
            self.file.seek(0)
            if not self.file.read(1):
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("another process owns this work") from None

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def account_lock_path(config, provider, account):
    import hashlib
    key = hashlib.sha256((provider + "\0" + account).encode()).hexdigest()
    return Path(config) / ("account-" + key + ".lock")


def account_busy(config, provider, account):
    path = account_lock_path(config, provider, account)
    if not path.exists():
        return False
    try:
        with ProcessLock(path):
            return False
    except (OSError, RuntimeError):
        return True
