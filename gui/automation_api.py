"""Server-only automation routes, covered by the panel's existing auth gate."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.responses import Response

import server_mode


def install(panel):
    app = panel.app

    @asynccontextmanager
    async def lifespan(app):
        if not server_mode.enabled():
            yield
            return
        import automation
        path = server_mode.config_dir() / "automation.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = automation.ProcessLock(path.with_suffix(".lock"))
        store = automation.Store(path)
        store.recover()
        app.state.automation = store
        from paperpull_core.outbox import Outbox
        app.state.outbox = Outbox(server_mode.config_dir() / "delivery.sqlite3")
        from integration_worker import Integrations
        app.state.integrations = Integrations(store, app.state.outbox, panel)

        async def execute(row):
            # Recover completed PDFs from an interrupted attempt whose summary
            # never reached the post-run plug-in. Never scan before this job's
            # last attempt, so enabling automation does not replay old archives.
            if row["attempted"]:
                from paperpull_core.outbox import Outbox
                meta = panel.discover_apps()[row["app"]]
                root = panel._account_root(meta, row["account"])
                outbox = Outbox(server_mode.config_dir() / "delivery.sqlite3")
                await asyncio.to_thread(outbox.reconcile, root, row["app"], row["account"], row["attempted"])
            scope = panel._scope_flags(start=row.get("range_start", ""), end=row.get("range_end", ""))
            response = panel._start_run(row["app"], row["account"], "all", scope or (), scheduled=True)
            state, result, code = None, None, None
            async for chunk in response.body_iterator:
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8")
                for block in chunk.split("\n\n"):
                    event, _, data = block.partition("\ndata: ")
                    if event == "event: automation-state":
                        state = data
                    elif event == "event: result":
                        result = json.loads(data)
                    elif event == "event: done":
                        code = int(data)
            if state:
                return state, (result or {}).get("new_files", 0)
            if code != 0 or result is None:
                return "FAILED", 0
            if result.get("stopped"):
                # Unknown stops may be an unclassified authentication wall.
                # A person must inspect it, rather than retrying automatically.
                return "PAUSED", result["new_files"]
            if result.get("attention"):
                return "FAILED", result["new_files"]
            return ("COMPLETED" if result["new_files"] else "NO_NEW_DOCUMENTS"), result["new_files"]

        def busy(provider, account):
            return (server_mode.INTERACTIVE_SCREENS > 0 or panel._IMPORTING.locked()
                    or len(panel._RUNS) >= store.settings()["concurrency"]
                    or (provider, account) in panel._RUNS
                    or any(r.get("action") == "login" for r in panel._RUNS.values()))

        dispatcher = automation.Dispatcher(store, execute, busy)
        app.state.dispatcher = dispatcher

        async def pause():
            tasks = list(dispatcher.tasks)
            for running in tasks:
                running.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for row in store.rows():
                if row["state"] == "RUNNING":
                    store.finish(row["app"], row["account"], "PAUSED")

        app.state.pause_automation = pause
        task = asyncio.create_task(dispatcher.loop())
        async def delivery_loop():
            while True:
                await asyncio.to_thread(app.state.outbox.flush)
                try:
                    await asyncio.to_thread(app.state.integrations.tick)
                except Exception:
                    app.state.integrations.status = "UNAVAILABLE"
                await asyncio.sleep(60)

        delivery_task = asyncio.create_task(delivery_loop())
        app.state.automation_tasks = (task, delivery_task)
        try:
            yield
        finally:
            task.cancel()
            delivery_task.cancel()
            await asyncio.gather(task, delivery_task, return_exceptions=True)
            lock.close()
            del app.state.automation
            del app.state.pause_automation
            del app.state.outbox
            del app.state.dispatcher
            del app.state.automation_tasks
            del app.state.integrations

    app.router.lifespan_context = lifespan

    def store():
        if not server_mode.enabled() or not hasattr(app.state, "automation"):
            raise HTTPException(404, "automation is available on the server")
        return app.state.automation

    def account_exists(provider, account):
        meta = panel.discover_apps().get(provider)
        if not meta or not meta.get("runnable", True) or account not in meta["accounts"]:
            raise ValueError("unknown provider or account")

    @app.get("/healthz")
    def health():
        if not server_mode.enabled():
            raise HTTPException(404)
        tasks = getattr(app.state, "automation_tasks", ())
        dispatcher = getattr(app.state, "dispatcher", None)
        healthy = (dispatcher is not None and dispatcher.healthy
                   and len(tasks) == 2 and all(not task.done() for task in tasks))
        return Response("ok" if healthy else "unavailable", status_code=200 if healthy else 503,
                        media_type="text/plain", headers={"Cache-Control": "no-store"})

    @app.get("/automation", response_class=HTMLResponse)
    def dashboard():
        store()
        static = panel.HERE / "static"
        return (static / "automation.html").read_text(encoding="utf-8").replace(
            "__AUTOMATION_JS__", (static / "automation.js").read_text(encoding="utf-8"))

    @app.get("/api/automation", dependencies=[Depends(panel._same_origin_only)])
    def overview():
        value = store()
        return {"settings": value.settings(), "schedules": value.rows(), "events": value.events(),
                "accounts": {key: meta["accounts"] for key, meta in panel.discover_apps().items()
                             if meta.get("runnable", True)},
                "delivery": app.state.outbox.counts(), "documents": app.state.outbox.overview(),
                "integrations": app.state.integrations.overview()}

    @app.post("/api/automation/{operation}", dependencies=[Depends(panel._same_origin_only)])
    async def change(operation: str, request: Request):
        value = store()
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError("expected an object")
            if operation == "settings":
                value.settings(data)
            elif operation == "delivery":
                # Local disk operation only. Never starts a provider run.
                if data.get("id"):
                    app.state.outbox.retry(data["id"])
                await asyncio.to_thread(app.state.outbox.flush)
            else:
                provider, account = data.get("app"), data.get("account", "primary")
                account_exists(provider, account)
                if operation == "schedule":
                    if data.keys() - {"app", "account", "cron", "zone", "enabled"}:
                        raise ValueError("unknown field")
                    value.put(provider, account, data.get("cron", "0 9 10 * *"),
                              data.get("zone", "America/New_York"), data.get("enabled", False))
                elif operation == "provider":
                    value.provider(provider, data.get("enabled"))
                elif operation == "notifications":
                    app.state.integrations.notices.suppress(provider, data.get("disabled"))
                elif operation == "expectations":
                    app.state.integrations.put(provider, account, data.get("rules"))
                elif operation in {"run", "reauthenticated"}:
                    value.request(provider, account, operation == "reauthenticated")
                elif operation == "backfill":
                    value.request(provider, account, start=data["start"], end=data["end"])
                else:
                    raise ValueError("unknown operation")
        except (ValueError, TypeError, KeyError):
            # Zone names, account values and arbitrary submitted data never
            # appear in errors or access logs.
            raise HTTPException(400, "Invalid request. Check the schedule and account state.") from None
        return {"ok": True}
