import io
import socket
import zipfile

import pytest
from pipeline.portal import content, remote


@pytest.mark.parametrize("url,address", [
    ("http://localhost", "127.0.0.1"), ("http://metadata", "169.254.169.254"),
    ("http://private", "10.0.0.1"), ("http://private", "172.16.0.1"), ("http://private", "192.168.1.1"),
    ("http://private", "::1"), ("http://private", "fc00::1"), ("http://private", "::ffff:127.0.0.1"),
    ("http://private", "64:ff9b::a00:1"), ("http://private", "224.0.0.1"),
    ("file:///etc/passwd", "93.184.216.34"), ("https://user:pass@public.example", "93.184.216.34"),
    ("http://public.example:8080", "93.184.216.34"), ("http://public.example?api_key=secret", "93.184.216.34"),
])
def test_unsafe_addresses_rejected(monkeypatch, url, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (address, 80))])
    with pytest.raises(ValueError): remote.validate_url(url)


def transport(monkeypatch, replies):
    calls = []
    class Connection:
        def __init__(self, host, *a, **kw): calls.append(host); self.sock = object()
        def connect(self): pass
        def request(self, method, path, headers): calls.append((path, headers))
        def getresponse(self): return replies.pop(0)
        def close(self): pass
    monkeypatch.setattr(remote.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(remote, "PinnedHTTPS", Connection)
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **kw: [(2, 1, 6, "", ("127.0.0.1" if host == "internal.example" else "93.184.216.34", 80))])
    return calls


class Reply:
    def __init__(self, data=b"[]", status=200, headers=None): self.body = io.BytesIO(data); self.status = status; self.headers = headers or {}
    def getheader(self, name, default=None): return self.headers.get(name, default)
    def read(self, size): return self.body.read(size)


def test_pinned_http_redirect_and_actual_size_limit(monkeypatch):
    calls = transport(monkeypatch, [Reply()])
    assert remote.get("http://public.example/records")[0] == b"[]"
    assert calls[0] == "93.184.216.34" and calls[1][1]["Host"] == "public.example"
    transport(monkeypatch, [Reply(status=302, headers={"Location": "http://internal.example/secret"})])
    with pytest.raises(ValueError, match="Private"): remote.get("http://public.example")
    transport(monkeypatch, [Reply(b"a" * 11)])
    with pytest.raises(ValueError, match="size"): remote.get("http://public.example", max_bytes=10)


def test_credentials_never_follow_other_host_or_echo(monkeypatch):
    credential = {"kind": "bearer", "secret": "fixture-secret"}
    transport(monkeypatch, [Reply(status=302, headers={"Location": "https://other.example/data"})])
    with pytest.raises(ValueError, match="another host"): remote.get("https://public.example", credential)
    transport(monkeypatch, [Reply(b'{"value":"fixture-secret"}')])
    with pytest.raises(ValueError, match="echoed"): remote.get("https://public.example", credential)
    assert remote.redact({"api_key": "secret", "data": 4}) == {"api_key": "[redacted]", "data": 4}


def test_tls_uses_pinned_destination_and_original_sni(monkeypatch):
    calls = []
    class Raw:
        def close(self): pass
    class Context:
        def wrap_socket(self, raw, server_hostname): calls.append(server_hostname); return raw
    monkeypatch.setattr(socket, "create_connection", lambda target, timeout: calls.append(target) or Raw())
    connection = remote.PinnedHTTPS("public.example", "93.184.216.34", 443)
    connection._context = Context(); connection.connect()
    assert calls == [("93.184.216.34", 443), "public.example"]


def test_flat_records_limits_formula_escape_and_zip_bomb():
    with pytest.raises(ValueError): content.json_records(b'[{"cell":{"nested":true}}]')
    with pytest.raises(ValueError): content.normalise([{"value": float("inf")}])
    assert b"'=SUM" in content.csv_export([{"value": "=SUM(1,2)"}])
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "a" * 10_000_000)
        archive.writestr("[Content_Types].xml", "a")
    with pytest.raises(ValueError, match="unsafe"): content.validate(stream.getvalue(), "xlsx")
