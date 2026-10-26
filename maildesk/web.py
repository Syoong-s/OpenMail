"""Loopback-only HTTP UI with same-origin mutations and inert message rendering."""
from email import policy
from email.parser import BytesParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, quote, urlsplit

from .mime import attachment_content

MAX_REQUEST = 44 * 1024 * 1024
STATIC = Path(__file__).parent / 'static'

# ==========================================
# Function: Own the loopback server and session boundary.
# Method: Generate a process-local session/CSRF token; bind only IPv4 localhost.
# ==========================================
class MailServer(ThreadingHTTPServer):
    daemon_threads = True

    # ==========================================
    # Function: Bind a mailbox service to one HTTP listener.
    # Method: Restrict addressing and preserve the selected ephemeral port.
    # ==========================================
    def __init__(self, port, service):
        self.service = service
        self.token = secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), Handler)
        self.allowed_hosts = {f'127.0.0.1:{self.server_port}', f'localhost:{self.server_port}'}

# ==========================================
# Function: Serve application assets and explicit mail use cases.
# Method: Validate Host, session and CSRF, then dispatch a small fixed route set.
# ==========================================
class Handler(BaseHTTPRequestHandler):
    server_version = 'TeleMail/0.1'

    # ==========================================
    # Function: Avoid logging mail addresses, searches or content.
    # Method: Suppress default HTTP access logging.
    # ==========================================
    def log_message(self, format, *args):
        pass

    # ==========================================
    # Function: Return bytes with restrictive security headers.
    # Method: Set content type/length, disable caching, and disallow active foreign content.
    # ==========================================
    def respond(self, data, content_type='application/json; charset=utf-8', status=200, headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    # ==========================================
    # Function: Return UTF-8 JSON.
    # Method: Serialize domain results without ASCII escaping Chinese strings.
    # ==========================================
    def json(self, value, status=200):
        self.respond(json.dumps(value, ensure_ascii=False).encode(), status=status)

    # ==========================================
    # Function: Enforce loopback Host and authenticated same-origin mutations.
    # Method: Reject DNS rebinding, missing sessions and forged browser requests.
    # ==========================================
    def authorized(self, mutation=False, public=False):
        if self.headers.get('Host') not in self.server.allowed_hosts:
            self.json({'error': 'Host 不被允许'}, 403)
            return False
        if public:
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except Exception:
            cookie = SimpleCookie()
        session = cookie.get('telemail_session')
        if session is None or not secrets.compare_digest(session.value, self.server.token):
            self.json({'error': '请从 TeleMail 首页打开应用'}, 401)
            return False
        if mutation:
            origin = self.headers.get('Origin')
            if origin not in {'http://' + h for h in self.server.allowed_hosts} or not secrets.compare_digest(self.headers.get('X-TeleMail-CSRF', ''), self.server.token):
                self.json({'error': '请求校验失败，请刷新页面'}, 403)
                return False
        return True

    # ==========================================
    # Function: Route read-only UI and mailbox requests.
    # Method: Serve fixed static assets or authenticated API resources.
    # ==========================================
    def do_GET(self):
        parsed_url = urlsplit(self.path)
        path = parsed_url.path
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if not self.authorized(public=path in assets):
            return
        if path in assets:
            file, content_type = assets[path]
            headers = {'Set-Cookie': f'telemail_session={self.server.token}; HttpOnly; SameSite=Strict; Path=/'} if path == '/' else {}
            self.respond((STATIC / file).read_bytes(), content_type, headers=headers)
            return
        query = parse_qs(parsed_url.query)
        service = self.server.service
        try:
            if path == '/api/session':
                accounts = [{'id': a.id, 'email': a.email} for a in service.accounts.values()]
                if service.demo:
                    accounts = [{'id': 'demo', 'email': 'demo@example.com'}]
                self.json({'csrf': self.server.token, 'accounts': accounts, 'demo': service.demo})
            elif path == '/api/status':
                self.json(service.status)
            elif path == '/api/messages':
                options = {key: query.get(key, [''])[0] for key in ('category', 'account', 'search')}
                self.json(service.store.list_messages(view=query.get('view', ['inbox'])[0], offset=int(query.get('offset', ['0'])[0]), **options))
            elif path == '/api/message':
                identity = query.get('id', [''])[0]
                self.json({'message': service.store.get(identity), 'thread': service.store.thread(identity)})
            elif path == '/api/job':
                self.json(service.store.job(query.get('id', [''])[0]))
            elif path == '/api/jobs':
                self.json(service.store.jobs())
            elif path == '/api/attachment':
                message = service.store.get(query.get('id', [''])[0], raw=True)
                index = int(query.get('index', ['-1'])[0])
                descriptor = next((a for a in message['parsed']['attachments'] if a['index'] == index), None)
                if descriptor is None:
                    raise KeyError('附件不存在')
                msg = BytesParser(policy=policy.default).parsebytes(message['raw'])
                part = list(msg.walk())[index]
                self.respond(attachment_content(part), 'application/octet-stream', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(descriptor['name'], safe='')})
            elif path == '/api/export':
                message = service.store.get(query.get('id', [''])[0], raw=True)
                self.respond(message['raw'], 'message/rfc822', headers={'Content-Disposition': 'attachment; filename="message.eml"'})
            else:
                self.json({'error': '路径不存在'}, 404)
        except (ValueError, KeyError) as error:
            self.json({'error': str(error)}, 400)
        except Exception:
            self.json({'error': '读取失败，请检查本地数据或服务状态'}, 500)

    # ==========================================
    # Function: Route explicit user mutations.
    # Method: Bound JSON input size, require session/CSRF, then call domain services.
    # ==========================================
    def do_POST(self):
        if not self.authorized(mutation=True):
            return
        service = self.server.service
        try:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('请求格式必须是 JSON')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_REQUEST:
                raise ValueError('请求大小无效或超过限制')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('请求内容必须是对象')
            if self.path == '/api/sync':
                service.request_sync()
                self.json({'ok': True})
            elif self.path == '/api/update':
                self.json(service.update(data['id'], data['changes']))
            elif self.path in ('/api/draft', '/api/send'):
                self.json(service.compose(data, send=self.path == '/api/send'))
            elif self.path == '/api/cancel':
                service.store.cancel(data['id'])
                self.json({'ok': True})
            elif self.path == '/api/reclassify':
                self.json({'updated': service.store.reclassify()})
            elif self.path == '/api/import':
                account = 'demo' if service.demo else data.get('account')
                if account != 'demo' and account not in service.accounts:
                    raise ValueError('请选择导入账户')
                import hashlib
                raw = base64.b64decode(data['base64'], validate=True)
                identity = service.store.ingest(account, '@import', 'local', hashlib.sha256(raw).hexdigest(), raw)
                self.json({'id': identity})
            else:
                self.json({'error': '路径不存在'}, 404)
        except (ValueError, KeyError, TypeError) as error:
            self.json({'error': str(error)}, 400)
        except Exception:
            self.json({'error': '操作未成功，请检查连接及服务状态'}, 500)
