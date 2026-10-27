"""Bounded public HTTP fetching with DNS pinning, TLS verification and redirect checks."""
from __future__ import annotations

import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

SENSITIVE = re.compile(r"(?:password|passwd|secret|token|api.?key|authorization|cookie|credential)", re.I)
MAX_BYTES = 50 * 1024 * 1024


def validate_url(url):
    if len(url) > 2048 or any(ord(c) < 32 for c in url) or "\\" in url:
        raise ValueError("Enter a valid public HTTP or HTTPS URL.")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("Use a public HTTP(S) URL without embedded credentials or a fragment.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise ValueError("URL port is invalid.") from None
    if port not in {80, 443}:
        raise ValueError("Only public HTTP and HTTPS ports are supported.")
    if any(SENSITIVE.search(key) or key.lower() == "key" for key, _ in parse_qsl(parts.query)):
        raise ValueError("Put external credentials in the credentials settings, not in the URL.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        raise ValueError("The public hostname could not be resolved.") from None
    def public(address):
        parsed = ipaddress.ip_address(address)
        if not parsed.is_global or parsed.is_multicast or parsed.is_reserved:
            return False
        if isinstance(parsed, ipaddress.IPv6Address):
            if parsed.is_site_local or parsed in ipaddress.ip_network("64:ff9b::/96") or parsed in ipaddress.ip_network("64:ff9b:1::/48"):
                return False
            if parsed.sixtofour and not parsed.sixtofour.is_global:
                return False
            if parsed.teredo and any(not item.is_global for item in parsed.teredo):
                return False
        return True
    if not addresses or any(not public(address) for address in addresses):
        raise ValueError("Private, local, reserved and metadata addresses cannot be fetched.")
    return parts, port, sorted(addresses)[0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, address, port):
        super().__init__(hostname, port=port, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # The TCP destination is exactly the previously validated public address.
        # Certificate verification and SNI still use the original hostname.
        raw = socket.create_connection((self.address, self.port), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class DeadlineReader(io.RawIOBase):
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Fetch deadline exceeded")
        self.sock.settimeout(min(10, remaining))
        return self.sock.recv_into(buffer)


class DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode, *args, **kwargs):
        return io.BufferedReader(DeadlineReader(self.sock, self.deadline))

    def __getattr__(self, name):
        return getattr(self.sock, name)


def get(url, credentials=None, max_bytes=MAX_BYTES):
    initial_host = urlsplit(url).hostname
    deadline = time.monotonic() + 60
    for hop in range(4):
        parts, port, address = validate_url(url)
        headers = {"Host": parts.netloc, "Accept-Encoding": "identity", "User-Agent": "NigeriaOpenData/1.0"}
        if credentials:
            if parts.scheme != "https" or parts.hostname != initial_host:
                raise ValueError("Authenticated APIs must use HTTPS and cannot redirect to another host.")
            if credentials["kind"] == "bearer":
                headers["Authorization"] = f"Bearer {credentials['secret']}"
            else:
                headers[credentials["header_name"]] = credentials["secret"]
        connection = (PinnedHTTPS(parts.hostname, address, port) if parts.scheme == "https"
                      else http.client.HTTPConnection(address, port=port, timeout=10))
        try:
            connection.connect()
            connection.sock = DeadlineSocket(connection.sock, deadline)
            path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or hop == 3:
                    raise ValueError("The remote redirect chain is unsupported.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError("The source did not return HTTP 200. Check its endpoint and credentials.")
            if response.getheader("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise ValueError("Compressed HTTP responses are not supported. Use an uncompressed endpoint.")
            size = response.getheader("Content-Length")
            if size and (not size.isdigit() or int(size) > max_bytes):
                raise ValueError("The response exceeds the size limit.")
            data = bytearray()
            while chunk := response.read(min(65536, max_bytes + 1 - len(data))):
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ValueError("The response exceeds the size limit.")
            result = bytes(data)
            if credentials and credentials["secret"].encode() in result:
                raise ValueError("The response echoed external credentials and cannot be imported.")
            if credentials:
                try:
                    decoded = json.dumps(json.loads(result), ensure_ascii=False)
                except (ValueError, UnicodeError):
                    decoded = ""
                if credentials["secret"] in decoded:
                    raise ValueError("The response echoed external credentials and cannot be imported.")
            return result, response.getheader("Content-Type", "").split(";")[0].lower()
        except (OSError, http.client.HTTPException):
            raise ValueError("The source could not be fetched securely. Check its availability and TLS configuration.") from None
        finally:
            connection.close()
    raise ValueError("The remote redirect chain is unsupported.")


def with_params(url, params):
    if any(SENSITIVE.search(key) or key.lower() == "key" for key in params):
        raise ValueError("Credential query parameters are not supported. Use a credential header.")
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({str(k): str(v) for k, v in params.items()})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def redact(value):
    if isinstance(value, dict):
        return {str(key): "[redacted]" if SENSITIVE.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value[:5]]
    return value[:400] if isinstance(value, str) else value
