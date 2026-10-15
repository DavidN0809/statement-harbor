"""Paperless API v9 upload and acknowledgement; response bodies stay private."""
from __future__ import annotations

import hashlib
import re
import uuid
from urllib.parse import urlencode

from .services import Service


class Paperless:
    def __init__(self, config):
        self.http = Service(config)
        self.config = config

    def existing(self, data, sha256):
        # Paperless checksum is the original file's MD5, not SHA-256. Verify
        # candidate original bytes with SHA-256 before acknowledging anything.
        query = urlencode({"checksum__iexact": hashlib.md5(data, usedforsecurity=False).hexdigest()})
        response = self.http.request("/api/documents/?" + query)
        for item in response.get("results", []):
            identity = item.get("id")
            if type(identity) is int and identity > 0:
                original = self.http.request(f"/api/documents/{identity}/download/?original=true", binary=True)
                if hashlib.sha256(original).hexdigest() == sha256:
                    return identity
        return None

    def named(self, resource, name):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z '&._-]{0,79}", name):
            raise ValueError("metadata names must not contain account numbers")
        value = self.http.request(f"/api/{resource}/?" + urlencode({"name__iexact": name}))
        for row in value.get("results", []):
            if row.get("name", "").casefold() == name.casefold():
                return int(row["id"])
        return int(self.http.json(f"/api/{resource}/", {"name": name})["id"])

    def metadata(self, provider, category, kind):
        fields = {}
        if self.config.get("create_metadata", False):
            fields["correspondent"] = str(self.named("correspondents", provider))
            fields["document_type"] = str(self.named("document_types", kind))
            fields["tags"] = [str(self.named("tags", provider)), str(self.named("tags", category))]
        return fields

    def submit(self, data, filename, fields):
        boundary = "harbor-" + uuid.uuid4().hex
        parts = []
        for key, values in fields.items():
            for value in values if isinstance(values, list) else [values]:
                parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                              f'{value}\r\n').encode())
        parts.extend([(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
                       f'filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n').encode(),
                      data, f"\r\n--{boundary}--\r\n".encode()])
        result = self.http.request("/api/documents/post_document/", "POST", b"".join(parts),
                                   "multipart/form-data; boundary=" + boundary)
        return str(uuid.UUID(result))

    def task(self, identity):
        identity = str(uuid.UUID(identity))
        value = self.http.request("/api/tasks/?" + urlencode({"task_id": identity}))
        rows = value.get("results", []) if isinstance(value, dict) else value
        for row in rows:
            if row.get("task_id") == identity:
                return str(row.get("status", "")).upper()
        return "UNKNOWN"
