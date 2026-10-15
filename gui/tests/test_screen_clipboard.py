"""Remote browser paste uses synthetic secrets and an isolated browser only.

No personal clipboard, provider profile, or financial website is used here.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as panel  # noqa: E402
import server_mode  # noqa: E402


@pytest.fixture
def isolated_screen(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("PAPERPULL_CONFIG", str(tmp_path / "config"))
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("PAPERPULL_PASSWORD", raising=False)
    monkeypatch.delenv("PAPERPULL_HOSTS", raising=False)
    server_mode._SESSIONS.clear()
    server_mode._FAILS.clear()
    server_mode.set_password("synthetic clipboard test passphrase")
    yield tmp_path
    server_mode._SESSIONS.clear()


def test_screen_paste_page_requires_session_and_is_never_cached(isolated_screen):
    client = TestClient(panel.app, base_url="http://nas.local")
    assert client.get("/screen", follow_redirects=False).status_code == 303
    client.cookies.set(server_mode.SESSION_COOKIE, server_mode.new_session())
    answer = client.get("/screen")
    assert answer.status_code == 200
    assert "no-store" in answer.headers["cache-control"]
    assert "frame-ancestors 'self'" in answer.headers["content-security-policy"]


@pytest.mark.parametrize("signed_in,origin,expected", [
    (False, "http://nas.local", False),
    (True, "https://phishing.example", False),
    (True, "null", False),
    (True, "", False),
    (True, "http://nas.local", True),
])
def test_paste_connection_requires_own_origin_and_live_session(
        isolated_screen, signed_in, origin, expected):
    """The exact existing screen gate protects all keystrokes and paste bytes."""
    reached, sent = [], []

    async def downstream(scope, receive, send):
        reached.append(scope["path"])

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    headers = {"host": "nas.local", "origin": origin}
    if signed_in:
        headers["cookie"] = "%s=%s" % (server_mode.SESSION_COOKIE, server_mode.new_session())
    scope = {"type": "websocket", "path": "/screen/websockify",
             "headers": [(name.encode(), value.encode()) for name, value in headers.items()]}
    asyncio.run(server_mode.SignInGate(downstream)(scope, receive, send))
    assert bool(reached) is expected
    assert sent == ([] if expected else [{"type": "websocket.close", "code": 1008}])


@pytest.fixture
def paste_client(isolated_screen, monkeypatch):
    import screen_input

    meta = {"accounts": ["primary", "second"], "runnable": True,
            "dir": str(isolated_screen / "data" / "Synthetic Bank")}
    monkeypatch.setattr(panel, "discover_apps", lambda: {
        "Synthetic Bank": meta,
        "Unavailable Bank": {"accounts": ["primary"], "runnable": False}})
    calls = []

    async def insert_text(chosen, account, text):
        assert chosen is meta
        calls.append((account, text))

    monkeypatch.setattr(screen_input, "insert_text", insert_text)
    monkeypatch.setattr(screen_input, "_BUSY", set())
    token = server_mode.new_session()
    monkeypatch.setattr(server_mode, "INTERACTIVE_TOKENS", {token: 1})
    client = TestClient(panel.app, base_url="http://nas.local")
    client.cookies.set(server_mode.SESSION_COOKIE, token)
    yield client, calls, token


def paste(client, **override):
    return client.post("/api/screen/paste", headers={"Origin": "http://nas.local"},
                       json={"app": "Synthetic Bank", "account": "primary",
                             "text": "synthetic secret", **override})


def test_paste_preserves_unicode_symbols_newlines_and_never_echoes(paste_client):
    client, calls, _ = paste_client
    secret = "Synthetic-Canary-雪🔐\"'\\$&<script>\nsecond\tline"
    response = paste(client, text=secret)
    assert response.status_code == 200
    assert calls == [("primary", secret)]
    assert secret not in response.text
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("bad", ["", "contains\x00nul", 123, None, [], {},
                                  "a" * 16385, "雪" * 5462],
                         ids=["empty", "nul", "number", "null", "array", "object", "too-long-ascii", "too-long-utf8"])
def test_paste_rejects_invalid_text_before_remote_browser(paste_client, bad):
    client, calls, _ = paste_client
    assert paste(client, text=bad).status_code == 400
    assert calls == []


@pytest.mark.parametrize("override", [
    {"app": "Unknown Bank"}, {"app": "Unavailable Bank"},
    {"account": "unknown"}, {"app": "../Synthetic Bank"},
    {"account": "../primary"}, {"account": 123}, {"app": []},
])
def test_paste_only_allows_selected_existing_runnable_account(paste_client, override):
    client, calls, _ = paste_client
    assert paste(client, **override).status_code == 400
    assert calls == []


def test_only_safe_account_choices_are_returned(paste_client):
    client, _, _ = paste_client
    response = client.get("/api/screen/accounts")
    assert response.status_code == 200
    assert response.json() == {"accounts": [
        {"app": "Synthetic Bank", "account": "primary"},
        {"app": "Synthetic Bank", "account": "second"}]}
    assert "no-store" in response.headers["cache-control"]


def test_paste_requires_connected_screen_from_same_session(paste_client, monkeypatch):
    client, calls, token = paste_client
    monkeypatch.setattr(server_mode, "INTERACTIVE_TOKENS", {"another-session": 1})
    assert paste(client).status_code == 409
    assert calls == []
    monkeypatch.setattr(server_mode, "INTERACTIVE_TOKENS", {token: 1})
    assert paste(client).status_code == 200


def test_paste_rejects_anonymous_and_cross_origin_requests(paste_client):
    client, calls, _ = paste_client
    payload = {"app": "Synthetic Bank", "account": "primary", "text": "canary"}
    assert client.post("/api/screen/paste", json=payload,
                       headers={"Origin": "https://phishing.example"}).status_code == 403
    client.cookies.clear()
    assert client.post("/api/screen/paste", json=payload,
                       headers={"Origin": "http://nas.local"}).status_code == 401
    assert calls == []


def test_paste_body_limit_and_malformed_json_have_no_side_effects(paste_client):
    client, calls, _ = paste_client
    for content in [b"{" , b"x" * 131073]:
        response = client.post("/api/screen/paste", content=content,
                               headers={"Origin": "http://nas.local", "Content-Type": "application/json"})
        assert response.status_code in {400, 413}
    assert calls == []


def test_paste_secret_never_reaches_logs_or_state(paste_client, isolated_screen, caplog):
    client, _, _ = paste_client
    secret = "CANARY-never-store-password-525735"
    assert paste(client, text=secret).status_code == 200
    assert secret not in caplog.text
    for path in isolated_screen.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes(), path.name


def test_screen_disconnect_cancels_pending_paste(paste_client, monkeypatch):
    import screen_input

    client, _, _ = paste_client
    cancelled = []

    async def pending(meta, account, text):
        server_mode.INTERACTIVE_TOKENS.clear()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(screen_input, "insert_text", pending)
    assert paste(client).status_code == 400
    assert cancelled == [True]
    assert not screen_input._BUSY


def test_duplicate_concurrent_paste_is_rejected(paste_client):
    import screen_input

    client, calls, token = paste_client
    screen_input._BUSY.add(token)
    assert paste(client).status_code == 409
    assert calls == []


def test_remote_errors_never_echo_sensitive_protocol_details(paste_client, monkeypatch, caplog):
    import screen_input

    client, _, _ = paste_client
    secret = "Exception-Canary-private-value-725462"

    async def broken(meta, account, text):
        raise RuntimeError(secret)

    monkeypatch.setattr(screen_input, "insert_text", broken)
    response = paste(client, text=secret)
    assert response.status_code == 400
    assert secret not in response.text
    assert secret not in caplog.text


@pytest.fixture(scope="module")
def own_browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def paste_page(own_browser):
    """Run the shipped client against an in-memory, same-origin noVNC stand-in."""
    static = Path(__file__).resolve().parents[1] / "static"
    wrapper = (static / "screen.html").read_text(encoding="utf-8").replace(
        "__SCREEN_JS__", (static / "screen.js").read_text(encoding="utf-8"))
    child = """<!doctype html><title>Synthetic noVNC</title><input id=ordinary>
    <input id=password type=password><textarea id=multiline></textarea>
    <input id=noVNC_keyboardinput><script type=module>__BRIDGE__</script>""".replace(
        "__BRIDGE__", (static / "screen_bridge.js").read_text(encoding="utf-8"))
    context = own_browser.new_context()
    context.add_init_script("""window.clipboardReads = 0;
        Object.defineProperty(navigator, 'clipboard', {get() {
          window.clipboardReads++;
          throw new Error('Clipboard access must be an explicit user paste event');
        }});""")
    requests = []

    def serve(route):
        url = route.request.url
        if "/api/screen/accounts" in url:
            route.fulfill(json={"accounts": [{"app": "Synthetic Bank", "account": "primary"}]})
        elif "/api/screen/paste" in url:
            requests.append(route.request.post_data_json)
            route.fulfill(json={"ok": True})
        elif "/screen/novnc/app/ui.js" in url:
            route.fulfill(content_type="application/javascript", body="export default {connected:true,rfb:null}")
        elif "/screen/novnc/" in url:
            route.fulfill(content_type="text/html", body=child)
        elif url.endswith("/screen"):
            route.fulfill(content_type="text/html", body=wrapper)
        else:
            route.fulfill(status=404)

    context.route("http://harbor.test/**", serve)
    page = context.new_page()
    page.goto("http://harbor.test/screen")
    page.wait_for_function("document.getElementById('paste-account').options.length === 2")
    page.wait_for_function("document.getElementById('paste-status').textContent.includes('Select a destination')")
    yield page, requests
    context.close()


def choose_account(page):
    page.locator("#paste-account").select_option(
        json.dumps({"app": "Synthetic Bank", "account": "primary"}, separators=(",", ":")))


def user_paste(page, text):
    page.locator("#paste-text").evaluate("""(element, text) => {
      const data = new DataTransfer();
      data.setData('text/plain', text);
      element.dispatchEvent(new ClipboardEvent('paste', {clipboardData:data, bubbles:true, cancelable:true}));
    }""", text)


def child_message(page, data):
    page.frame_locator("#remote-screen").locator("body").evaluate(
        "(element, data) => parent.postMessage(data, location.origin)", data)


def test_client_never_reads_clipboard_or_sends_until_explicit_action(paste_page):
    page, requests = paste_page
    assert page.evaluate("window.clipboardReads") == 0
    assert requests == []
    assert page.locator("#paste-send").is_disabled()
    choose_account(page)
    secret = "UI-Canary-雪🔐\"'\\$&<>\nline two\tend"
    user_paste(page, secret)
    assert page.locator("#paste-text").get_attribute("type") == "password"
    assert requests == []
    page.locator("#paste-send").click()
    page.wait_for_function("document.getElementById('paste-status').textContent.startsWith('Text pasted')")
    assert requests == [{"app": "Synthetic Bank", "account": "primary", "text": secret}]
    assert page.locator("#paste-text").input_value() == ""
    assert secret not in page.content()
    assert page.evaluate("[localStorage.length, sessionStorage.length, window.clipboardReads]") == [0, 0, 0]


def test_disconnect_clears_masked_text_and_prevents_submission(paste_page):
    page, requests = paste_page
    choose_account(page)
    user_paste(page, "disconnect-Canary-secret")
    child_message(page, {"type": "harbor-screen-connection", "connected": False})
    page.wait_for_function("document.getElementById('paste-send').disabled")
    assert page.locator("#paste-text").input_value() == ""
    child_message(page, {"type": "harbor-user-paste", "text": "blocked"})
    page.wait_for_function("document.getElementById('paste-status').textContent.includes('Wait for')")
    assert requests == []


def test_messages_require_the_actual_same_origin_child(paste_page):
    page, requests = paste_page
    choose_account(page)
    page.evaluate("""() => {
      const data = {type:'harbor-user-paste', text:'untrusted'};
      window.postMessage(data, location.origin);
      window.dispatchEvent(new MessageEvent('message', {
        data, origin:'https://phishing.example',
        source:document.getElementById('remote-screen').contentWindow}));
    }""")
    user_paste(page, "verified-child-sentinel")
    page.locator("#paste-send").click()
    page.wait_for_function("document.getElementById('paste-status').textContent.startsWith('Text pasted')")
    assert [request["text"] for request in requests] == ["verified-child-sentinel"]


def test_child_native_paste_and_utf8_limit(paste_page):
    page, requests = paste_page
    choose_account(page)
    child_message(page, {"type": "harbor-user-paste", "text": "雪" * 5462})
    page.wait_for_function("document.getElementById('paste-status').textContent.includes('16 KB')")
    assert requests == []
    secret = "native-user-paste-雪\nsecond line"
    child_message(page, {"type": "harbor-user-paste", "text": secret})
    page.wait_for_function("document.getElementById('paste-status').textContent.startsWith('Text pasted')")
    assert [request["text"] for request in requests] == [secret]
    assert page.locator("#paste-text").input_value() == ""


def test_native_paste_event_in_novnc_forwards_once_without_clipboard_polling(paste_page):
    page, requests = paste_page
    choose_account(page)
    secret = "native-event-Canary-雪🔐\nsecond line"
    page.frame_locator("#remote-screen").locator("body").evaluate("""(element, text) => {
      const data = new DataTransfer(); data.setData('text/plain', text);
      element.dispatchEvent(new ClipboardEvent('paste', {clipboardData:data, bubbles:true, cancelable:true}));
    }""", secret)
    page.wait_for_function("document.getElementById('paste-status').textContent.startsWith('Text pasted')")
    assert [request["text"] for request in requests] == [secret]
    assert page.evaluate("window.clipboardReads") == 0
    assert page.frame_locator("#remote-screen").locator("body").evaluate("window.clipboardReads") == 0


def test_failed_paste_clears_input_without_echoing_server_response(paste_page):
    page, _ = paste_page
    choose_account(page)
    secret = "Failure-Canary-secret-625623"
    page.route("**/api/screen/paste", lambda route: route.fulfill(status=400, json={"detail": secret}))
    user_paste(page, secret)
    page.locator("#paste-send").click()
    page.wait_for_function("document.getElementById('paste-status').textContent.startsWith('Could not paste')")
    assert page.locator("#paste-text").input_value() == ""
    assert secret not in page.content()


def test_editing_masked_input_discards_old_raw_paste(paste_page):
    page, requests = paste_page
    choose_account(page)
    user_paste(page, "stale-Canary-secret\nsecond line")
    page.locator("#paste-text").fill("replacement secret")
    page.locator("#paste-send").click()
    page.wait_for_function("document.getElementById('paste-status').textContent.startsWith('Text pasted')")
    assert [request["text"] for request in requests] == ["replacement secret"]


@pytest.mark.parametrize("event", ["pagehide", "account-change"])
def test_navigation_and_account_change_clear_ephemeral_text(paste_page, event):
    page, requests = paste_page
    choose_account(page)
    user_paste(page, "short-lived-canary")
    if event == "pagehide":
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
    else:
        page.locator("#paste-account").select_option("")
    assert page.locator("#paste-text").input_value() == ""
    assert requests == []


def test_served_novnc_cannot_log_keys_or_synchronize_clipboards(
        isolated_screen, monkeypatch, own_browser):
    root = isolated_screen / "novnc"
    (root / "core" / "util").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "core" / "util" / "logging.js").write_text("console.log('stock logger')", encoding="utf-8")
    (root / "app" / "ui.js").write_text("""const UI = {
      clipboardReceive(){window.clipboardTouches++}, clipboardSend(){window.clipboardTouches++}
    }; export default UI;""", encoding="utf-8")
    (root / "vnc.html").write_text("<html><body>noVNC</body></html>", encoding="utf-8")
    monkeypatch.setenv("PAPERPULL_NOVNC", str(root))
    client = TestClient(panel.app, base_url="http://nas.local")
    client.cookies.set(server_mode.SESSION_COOKIE, server_mode.new_session())
    logging_response = client.get("/screen/novnc/core/util/logging.js?logging=debug")
    ui_response = client.get("/screen/novnc/app/ui.js")
    frame_response = client.get("/screen/novnc/vnc.html")
    assert all(response.status_code == 200 for response in [logging_response, ui_response, frame_response])
    assert "harbor-user-paste" in frame_response.text
    assert "no-store" in logging_response.headers["cache-control"]
    page = own_browser.new_page()
    logged = []
    page.on("console", lambda message: logged.append(message.text))
    try:
        result = page.evaluate("""async ([logger, ui]) => {
          const load = source => import(URL.createObjectURL(new Blob([source], {type:'text/javascript'})));
          const Log = await load(logger);
          Log.initLogging('debug');
          for (const name of ['Debug','Info','Warn','Error']) Log[name]('private-canary-keys');
          window.clipboardTouches = 0;
          const {default: UI} = await load(ui);
          UI.clipboardReceive('private-canary-clipboard');
          UI.clipboardSend('private-canary-clipboard');
          return [Log.getLogging(), window.clipboardTouches];
        }""", [logging_response.text, ui_response.text])
        assert result == ["none", 0]
        assert logged == []
    finally:
        page.close()
