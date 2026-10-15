import subprocess
import sys
import os
import signal

from paperpull_core.process_lock import ProcessLock, account_busy, account_lock_path


def test_orphaned_worker_still_excludes_replacement_until_exit(tmp_path):
    path = account_lock_path(tmp_path, "Synthetic Bank", "primary")
    code = "from paperpull_core.process_lock import ProcessLock; import os,sys,time; lock=ProcessLock(sys.argv[1]); print(os.getpid(),flush=True); time.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
    pid = None
    try:
        pid = int(child.stdout.readline().strip())
        assert account_busy(tmp_path, "Synthetic Bank", "primary")
        assert not account_busy(tmp_path, "Synthetic Bank", "second")
    finally:
        # Windows' venv executable may be a launcher. Kill the interpreter
        # which actually owns the lock, then wait for its launcher as well.
        if pid is not None:
            os.kill(pid, signal.SIGTERM)
        else:
            child.terminate()
        child.wait(timeout=10)
        child.stdout.close()
    assert not account_busy(tmp_path, "Synthetic Bank", "primary")
    with ProcessLock(path):
        assert account_busy(tmp_path, "Synthetic Bank", "primary")
