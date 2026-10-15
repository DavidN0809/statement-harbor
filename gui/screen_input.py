"""Authenticated manual paste transport. No text is persisted or returned."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import server_mode

_BUSY = set()


async def insert_text(meta, account, text):
    import app as panel
    env = panel._run_env(meta)
    for key in list(env):
        if key in {"DEBUG", "PWDEBUG"} or key.startswith("PLAYWRIGHT_"):
            env.pop(key, None)
    expected = server_mode.profile_for(Path(meta["dir"]).name, account)
    process = await asyncio.create_subprocess_exec(
        meta["python"], "-P", "-m", "paperpull_core.screen_input",
        meta["script"], account, expected, cwd=meta["dir"], env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(process.communicate(text.encode("utf-8")), 10)
        if process.returncode != 0:
            raise ValueError("paste unavailable")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def install(panel):
    def active(request):
        token = request.cookies.get(server_mode.SESSION_COOKIE, "")
        return (server_mode.enabled() and server_mode.session_valid(token)
                and server_mode.INTERACTIVE_TOKENS.get(token, 0) > 0)

    @panel.app.get("/api/screen/accounts", dependencies=[Depends(panel._same_origin_only)])
    def accounts():
        if not server_mode.enabled():
            raise HTTPException(404)
        return JSONResponse({"accounts": [{"app": app, "account": account}
                              for app, meta in panel.discover_apps().items()
                              if meta.get("runnable", True)
                              for account in meta["accounts"]]}, headers={"Cache-Control": "no-store"})

    @panel.app.post("/api/screen/paste", dependencies=[Depends(panel._same_origin_only)])
    async def paste(request: Request):
        if not server_mode.enabled():
            raise HTTPException(404)
        headers = {"Cache-Control": "no-store"}
        if not active(request):
            raise HTTPException(409, "Connect the sign-in screen first.", headers=headers)
        token = request.cookies.get(server_mode.SESSION_COOKIE, "")
        if token in _BUSY:
            raise HTTPException(409, "A paste is already in progress.", headers=headers)
        _BUSY.add(token)
        worker = watcher = None
        try:
            # Bound the streamed request as well as its decoded text. Never
            # include submitted data or exception text in a response or log.
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 131072:
                    raise ValueError("oversized request")
            value = json.loads(raw)
            raw.clear()
            if not isinstance(value, dict) or value.keys() != {"app", "account", "text"}:
                raise ValueError("invalid fields")
            from paperpull_core.screen_input import validate_text
            text = validate_text(value["text"])
            meta = panel.discover_apps().get(value["app"])
            if not meta or not meta.get("runnable", True) or value["account"] not in meta["accounts"]:
                raise ValueError("unknown account")
            if not active(request):
                raise ValueError("screen disconnected")
            worker = asyncio.create_task(insert_text(meta, value["account"], text))

            async def watch():
                while active(request):
                    await asyncio.sleep(0.05)
                raise ValueError("screen or request ended")

            watcher = asyncio.create_task(watch())
            await asyncio.wait({worker, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if watcher.done() or not active(request):
                raise ValueError("screen ended")
            await worker
        except Exception:
            raise HTTPException(400, "Paste was not completed. Select the account and focus its sign-in field.", headers=headers) from None
        finally:
            _BUSY.discard(token)
            for task in (worker, watcher):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (worker, watcher) if task), return_exceptions=True)
        return JSONResponse({"ok": True}, headers=headers)
