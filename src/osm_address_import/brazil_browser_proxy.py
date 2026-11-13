"""Disposable loopback TLS front end and jsDelivr-only browser proxy.

The TLS listener forwards only to the isolated HTTP port 39003. The external
proxy permits CONNECT to cdn.jsdelivr.net:443 only; all other remote hosts are
rejected, including public OpenStreetMap API hosts. Run only for browser checks.
"""

from __future__ import annotations

import argparse
import http.client
import select
import socket
import socketserver
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class RailsHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def _forward(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            self.send_error(413)
            return
        body = self.rfile.read(length) if length else None
        headers = {key: value for key, value in self.headers.items()
                   if key.lower() not in {"host", "connection", "content-length"}}
        headers["Host"] = "127.0.0.1:39004"
        headers["X-Forwarded-Proto"] = "https"
        headers["X-Forwarded-Host"] = "127.0.0.1:39004"
        if body is not None:
            headers["Content-Length"] = str(len(body))
        upstream = http.client.HTTPConnection("127.0.0.1", 39003, timeout=60)
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            data = response.read(20_000_001)
            if len(data) > 20_000_000:
                self.send_error(502)
                return
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {"connection", "content-length", "transfer-encoding"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            upstream.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _forward


class CdnProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(15)
        line = b""
        while not line.endswith(b"\r\n") and len(line) < 4096:
            line += self.request.recv(1)
        if line != b"CONNECT cdn.jsdelivr.net:443 HTTP/1.1\r\n":
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return
        while True:
            header = b""
            while not header.endswith(b"\r\n") and len(header) < 4096:
                header += self.request.recv(1)
            if header == b"\r\n" or not header:
                break
        remote = socket.create_connection(("cdn.jsdelivr.net", 443), timeout=15)
        try:
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.request.settimeout(None)
            remote.settimeout(None)
            sockets = (self.request, remote)
            while True:
                ready, _, _ = select.select(sockets, [], [], 60)
                if not ready:
                    break
                for source in ready:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    (remote if source is self.request else self.request).sendall(chunk)
        finally:
            remote.close()


class LocalProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    tls = ThreadingHTTPServer(("127.0.0.1", 39004), RailsHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.cert, args.key)
    tls.socket = context.wrap_socket(tls.socket, server_side=True)
    cdn = LocalProxy(("127.0.0.1", 39005), CdnProxyHandler)
    thread = threading.Thread(target=cdn.serve_forever, daemon=True)
    thread.start()
    try:
        tls.serve_forever()
    finally:
        cdn.shutdown()
        cdn.server_close()


if __name__ == "__main__":
    main()
