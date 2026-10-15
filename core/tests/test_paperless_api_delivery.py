import hashlib
import json
import uuid

import pytest
from pypdf import PdfWriter

from paperpull_core.outbox import Outbox, safe_metadata
from paperpull_core.paperless_api import Paperless
from paperpull_core.services import Service


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    config = tmp_path / "integrations.json"
    config.write_text(json.dumps({"paperless": {"mode": "api"}}))
    monkeypatch.setenv("HARBOR_INTEGRATIONS", str(config))
    source = tmp_path / "private-123456789.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(source)
    fake = Fake()
    monkeypatch.setattr("paperpull_core.paperless_api.Paperless", lambda config: fake)
    return Outbox(tmp_path / "delivery.sqlite3"), source, fake


class Fake:
    def __init__(self):
        self.found = None
        self.posts = 0
        self.status = "STARTED"
        self.crash = False

    def existing(self, data, digest):
        assert hashlib.sha256(data).hexdigest() == digest
        return self.found

    def metadata(self, *args):
        return {}

    def submit(self, data, filename, fields):
        self.posts += 1
        assert "123456789" not in filename
        if self.crash:
            raise OSError("private token banking 123456789")
        return str(uuid.uuid4())

    def task(self, identity):
        return self.status


def test_processing_ack_and_restart_do_not_resubmit(delivery):
    box, source, fake = delivery
    box.enqueue(source, source.parent, "Bank", identity="statement-one")
    assert box.flush() == {"PROCESSING": 1}
    fake.status = "SUCCESS"
    assert Outbox(box.path).flush() == {"PROCESSING": 1}
    fake.found = 17
    assert Outbox(box.path).flush() == {"DELIVERED": 1}
    box.flush()
    assert fake.posts == 1
    assert source.exists()


def test_ambiguous_submission_reconciles_without_resend(delivery):
    box, source, fake = delivery
    box.enqueue(source, source.parent, "Bank")
    fake.crash = True
    assert box.flush() == {"SUBMITTING": 1}
    box.retry(box.overview()[0]["id"])
    assert Outbox(box.path).flush() == {"SUBMITTING": 1}
    assert fake.posts == 1
    fake.found = 3
    assert box.flush() == {"DELIVERED": 1}
    assert b"private token" not in box.path.read_bytes()


def test_failed_task_only_retries_ingestion_when_requested(delivery):
    box, source, fake = delivery
    key = box.enqueue(source, source.parent, "Bank")
    box.flush()
    fake.status = "FAILURE"
    assert box.flush() == {"API_FAILED": 1}
    box.flush()
    assert fake.posts == 1
    box.retry(key)
    assert box.flush() == {"PROCESSING": 1}
    assert fake.posts == 2


def test_existing_original_skips_upload_and_corrupt_is_rejected(delivery):
    box, source, fake = delivery
    fake.found = 4
    box.enqueue(source, source.parent, "Bank")
    assert box.flush() == {"DELIVERED": 1}
    assert fake.posts == 0
    source.write_text("<html>login</html>")
    box.enqueue(source, source.parent, "Bank")
    assert box.flush() == {"DELIVERED": 1, "CORRUPT": 1}


def test_metadata_excludes_provider_text_and_account_number():
    assert safe_metadata({"title": "secret account 123456789", "category": "Statement", "date": "2026-10-12", "account_category": "123456789"}) == {
        "kind": "Statement", "category": "Financial", "date": "2026-10-12", "period": "2026-10"}


@pytest.mark.parametrize("url", ["https://user:secret@example.org", "https://example.org/path", "file:///etc/passwd", "https://example.org?secret=yes"])
def test_service_origin_rejects_credential_and_path_urls(url):
    with pytest.raises(ValueError):
        Service({"url": url})


def test_paperless_verifies_candidate_original_sha256():
    api = Paperless.__new__(Paperless)
    calls = []
    class HTTP:
        def request(self, path, **kwargs):
            calls.append(path)
            return b"correct" if kwargs else {"results": [{"id": 9}]}
    api.http = HTTP()
    assert api.existing(b"correct", hashlib.sha256(b"correct").hexdigest()) == 9
    assert api.existing(b"wrong", hashlib.sha256(b"wrong").hexdigest()) is None
    assert "original=true" in calls[1]


def test_multipart_metadata_tags_and_task_uuid():
    api = Paperless.__new__(Paperless)
    identity = str(uuid.uuid4())
    class HTTP:
        def request(self, path, method, data, content_type):
            assert method == "POST"
            assert data.count(b'name="tags"') == 2
            assert b'%PDF-synthetic' in data
            return identity
    api.http = HTTP()
    assert api.submit(b"%PDF-synthetic", "safe.pdf", {"tags": ["1", "2"]}) == identity


def test_explicit_rejection_can_retry_after_repair(delivery):
    from urllib.error import HTTPError
    box, source, fake = delivery
    key = box.enqueue(source, source.parent, "Bank")
    real_submit = fake.submit
    def rejected(*args):
        raise HTTPError("https://private.invalid", 403, "secret", {}, None)
    fake.submit = rejected
    assert box.flush() == {"API_FAILED": 1}
    box.retry(key)
    fake.submit = real_submit
    assert box.flush() == {"PROCESSING": 1}


def test_remote_redirect_never_forwards_token(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.error import HTTPError
    hits = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/stolen")
            self.end_headers()
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = tmp_path / "token"
    token.write_text("synthetic-private-token")
    try:
        service = Service({"url": f"http://127.0.0.1:{server.server_port}", "token_file": str(token), "allow_private_http": True})
        with pytest.raises(HTTPError):
            service.request("/api/test/")
        assert hits == ["/api/test/"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
