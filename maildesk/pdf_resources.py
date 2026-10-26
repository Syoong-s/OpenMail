"""Capability-scoped, loopback-only resources for the bundled offline PDF viewer."""
from functools import lru_cache
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

ASSETS = Path(__file__).resolve().parent / 'desktop_assets/pdfjs'
MAX_PDF_BYTES = 64 * 1024 * 1024
CSP = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; "
       "connect-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' blob: data:; "
       "img-src 'self' blob: data:; object-src 'none'; frame-src 'none'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")
MIME = {'.html': 'text/html; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
        '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.gif': 'image/gif',
        '.png': 'image/png', '.wasm': 'application/wasm', '.bcmap': 'application/octet-stream',
        '.pfb': 'application/octet-stream', '.ttf': 'font/ttf', '.icc': 'application/octet-stream'}

# ==========================================
# Function: Resolve the exact vendored resource allowlist without accepting paths from PDF content.
# Method: Cache the pinned distribution manifest plus the three application-owned viewer files.
# ==========================================
@lru_cache(maxsize=1)
def resource_names():
    manifest = json.loads((ASSETS / 'vendor/SOURCE.json').read_text(encoding='utf-8'))
    return frozenset({'viewer.html', 'viewer.mjs', 'bootstrap.mjs', 'viewer.css'} |
                     {'vendor/' + name for name in manifest['files'] if Path(name).suffix in MIME})

# ==========================================
# Function: Keep immutable engine assets in memory after their first bounded local read.
# Method: Cache only known distribution files, never PDF documents, passwords or arbitrary paths.
# ==========================================
@lru_cache(maxsize=320)
def resource_bytes(name):
    if name not in resource_names():
        raise ValueError('Unknown PDF viewer resource')
    return (ASSETS / name).read_bytes()

# ==========================================
# Function: Serve one document and trusted viewer resources without exposing the filesystem.
# Method: Require the exact loopback Host and random capability path; reject cross-origin requests.
# ==========================================
class PDFHandler(BaseHTTPRequestHandler):
    # ==========================================
    # Function: Return an allowlisted local resource or the document owned by this server.
    # Method: Reject alternate hosts, traversal, queries and cross-site requests before reading bytes.
    # ==========================================
    def do_GET(self):
        server = self.server
        try:
            parsed = urlsplit(self.path)
            if (self.headers.get('Host') != server.expected_host or parsed.scheme or parsed.netloc or
                    parsed.query or parsed.fragment or not parsed.path.startswith(server.prefix) or
                    self.headers.get('Sec-Fetch-Site') == 'cross-site' or
                    self.headers.get('Origin') not in (None, server.origin)):
                self.send_error(403)
                return
            name = parsed.path[len(server.prefix):]
            if name == 'document.pdf':
                data, mime = server.pdf_data, 'application/pdf'
            elif name in resource_names():
                data, mime = resource_bytes(name), MIME[Path(name).suffix]
            else:
                self.send_error(404)
                return
            if server.retired:
                self.send_error(410)
                return
            server.served[name] += 1
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            if name == 'viewer.html':
                self.send_header('Content-Security-Policy', CSP)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    # ==========================================
    # Function: Answer metadata requests using the same strict resource policy as GET.
    # Method: Reuse the handler while omitting the response body.
    # ==========================================
    def do_HEAD(self):
        self.do_GET()

    # ==========================================
    # Function: Keep capability URLs and document details out of logs.
    # Method: Disable the standard request logger entirely.
    # ==========================================
    def log_message(self, *unused):
        pass

# ==========================================
# Function: Bound accepted socket reads and allow immediate cleanup of retired viewer sessions.
# Method: Use daemon request threads and time out incomplete HTTP requests.
# ==========================================
class PDFServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    # ==========================================
    # Function: Prevent a stalled local client from retaining a request thread indefinitely.
    # Method: Apply a finite timeout before HTTP headers are parsed.
    # ==========================================
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address

# ==========================================
# Function: Own one offline PDF capability and its bounded server lifetime.
# Method: Bind only 127.0.0.1 on an ephemeral port and discard document bytes on close.
# ==========================================
class PDFSession:
    # ==========================================
    # Function: Admit a bounded PDF and start its private local resource endpoint.
    # Method: Validate bytes and installed assets before creating any background threads.
    # ==========================================
    def __init__(self, data):
        if not data or len(data) > MAX_PDF_BYTES or b'%PDF-' not in data[:1024]:
            raise ValueError('PDF 无效或超过 64 MiB 预览上限')
        resource_names()
        self.closed = False
        self.server = PDFServer(('127.0.0.1', 0), PDFHandler)
        self.server.pdf_data = bytes(data)
        self.server.retired = False
        self.server.served = Counter()
        self.token = secrets.token_hex(24)
        self.server.prefix = '/' + self.token + '/'
        self.server.expected_host = '127.0.0.1:' + str(self.server.server_port)
        self.server.origin = 'http://' + self.server.expected_host
        self.url = self.server.origin + self.server.prefix + 'viewer.html'
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .05},
                                       name='maildesk-pdf', daemon=True)
        self.thread.start()

    # ==========================================
    # Function: Revoke the capability and release document bytes exactly once.
    # Method: Stop the listener before returning, without retaining PDF data in shared asset caches.
    # ==========================================
    def close(self):
        if self.closed:
            return
        self.closed = True
        self.server.retired = True
        self.server.pdf_data = b''
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
