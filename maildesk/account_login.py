"""Provider templates, isolated transport checks and native public-client OAuth.

Only the temporary loopback callback is HTTP. Provider endpoints are fixed HTTPS;
neither authentication probes nor cancellation send a message or change a mailbox.
"""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import webbrowser

PROVIDERS = {
    'gmail': {'name': 'Gmail', 'imap_host': 'imap.gmail.com', 'smtp_host': 'smtp.gmail.com',
              'imap_port': 993, 'smtp_port': 465, 'imap_security': 'ssl', 'smtp_security': 'ssl'},
    'outlook': {'name': 'Outlook / Hotmail', 'imap_host': 'outlook.office365.com', 'smtp_host': 'smtp-mail.outlook.com',
                'imap_port': 993, 'smtp_port': 587, 'imap_security': 'ssl', 'smtp_security': 'starttls'},
    'microsoft365': {'name': 'Microsoft 365', 'imap_host': 'outlook.office365.com', 'smtp_host': 'smtp.office365.com',
                     'imap_port': 993, 'smtp_port': 587, 'imap_security': 'ssl', 'smtp_security': 'starttls'},
    'other': {'name': '其他邮箱 · IMAP / SMTP', 'imap_host': '', 'smtp_host': '',
              'imap_port': 993, 'smtp_port': 465, 'imap_security': 'ssl', 'smtp_security': 'ssl'},
}
OAUTH = {
    'google': {'authorize': 'https://accounts.google.com/o/oauth2/v2/auth',
               'token': 'https://oauth2.googleapis.com/token', 'scope': 'https://mail.google.com/'},
    'microsoft': {'authorize': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
                  'token': 'https://login.microsoftonline.com/common/oauth2/v2.0/token',
                  'scope': 'https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access'},
}
TOKEN_PREFIX = 'telemail-oauth-v1:'

# ==========================================
# Function: Identify a provider without changing a custom server configuration.
# Method: Match only established public address domains or explicit Microsoft servers.
# ==========================================
def detect_provider(email='', account=None):
    domain=email.rsplit('@',1)[-1].lower()
    if domain in ('gmail.com','googlemail.com'):return 'gmail'
    if domain in ('outlook.com','hotmail.com','live.com','msn.com'):return 'outlook'
    if account and account.imap_host.lower()=='imap.gmail.com':return 'gmail'
    if account and account.imap_host.lower()=='outlook.office365.com':return 'microsoft365'
    return 'other'

# ==========================================
# Function: Translate a visible provider choice into its supported OAuth authority.
# Method: Keep Microsoft consumer and work templates on the same public authority.
# ==========================================
def oauth_provider(provider):
    return 'google' if provider=='gmail' else 'microsoft' if provider in ('outlook','microsoft365') else ''

# ==========================================
# Function: Report safe login failures without projecting provider-controlled text.
# Method: Use a small public error vocabulary and suppress raw exception details.
# ==========================================
class LoginError(ValueError):
    pass

# ==========================================
# Function: Check cooperative cancellation between bounded network stages.
# Method: Raise a non-secret public exception when the attempt event is set.
# ==========================================
def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise LoginError('登录已取消')

# ==========================================
# Function: Verify a candidate against both incoming and outgoing providers.
# Method: Supply an explicit isolated secret, use IMAP NOOP and SMTP AUTH only.
# ==========================================
def verify_login(account, secret, cancel=None, progress=None):
    from .transport import imap_connection, smtp_connection, checked
    from .credentials import identity
    if not secret:raise LoginError('请填写密码或完成浏览器授权')
    bundle=decode_oauth(secret) if account.auth=='oauth2' else None
    if bundle:
        allowed=[item for key,item in PROVIDERS.items() if oauth_provider(key)==bundle['provider']]
        if not any(account.imap_host==item['imap_host'] and account.smtp_host==item['smtp_host']
                   and account.imap_port==item['imap_port'] and account.smtp_port==item['smtp_port']
                   and account.imap_security==item['imap_security'] and account.smtp_security==item['smtp_security'] for item in allowed):
            raise LoginError('浏览器授权只能用于所选提供商的标准邮件服务器，请恢复邮箱模板。')
    transport_secret=bundle['access_token'] if bundle else secret
    for stage in ('imap','smtp'):
        check_cancel(cancel)
        if progress:progress(stage,'checking')
        try:
            if stage=='imap':
                with imap_connection(account, secret_override=transport_secret, notify=False) as client:
                    checked(client.noop(),'连接检查')
            else:
                with smtp_connection(account,secret_override=transport_secret):pass
        except Exception:
            check_cancel(cancel)
            message=('收件服务器验证失败。请检查服务器、用户名、授权码和 IMAP 权限。' if stage=='imap'
                     else '发件服务器验证失败。请检查 SMTP 地址、认证权限及组织的 SMTP AUTH 设置。')
            raise LoginError(message) from None
        check_cancel(cancel)
        if progress:progress(stage,'verified')
    return {'email':account.email,'username':account.login_name,'imap':account.imap_host,
            'smtp':account.smtp_host,'auth':account.auth,'verified_at':time.time(),
            'identity':identity(account),'credential_digest':hashlib.sha256(secret.encode()).hexdigest()}

# ==========================================
# Function: Validate an installed-app OAuth registration before browser navigation.
# Method: Require the caller's public client ID and a fixed supported authority.
# ==========================================
def validate_client(provider, client_id, client_secret=''):
    if provider not in OAUTH:raise LoginError('此邮箱模板不支持浏览器授权')
    if not isinstance(client_id,str) or not client_id.strip() or len(client_id)>512 or any(c.isspace() for c in client_id):
        raise LoginError('请先配置此应用自己的 OAuth Client ID')
    if len(client_secret)>4096:raise LoginError('OAuth 应用配置无效')
    return client_id.strip()

# ==========================================
# Function: Import a Google desktop registration through a user-selected local file.
# Method: Accept only installed-client JSON and never retain arbitrary endpoint values.
# ==========================================
def import_google_client(path):
    from pathlib import Path
    path=Path(path)
    if path.stat().st_size>65536:raise LoginError('OAuth 配置文件过大')
    try:
        data=json.loads(path.read_text(encoding='utf-8'))['installed']
        client_id=validate_client('google',data['client_id'],data.get('client_secret',''))
        return {'provider':'google','client_id':client_id,'client_secret':str(data.get('client_secret',''))}
    except (KeyError,TypeError,ValueError):raise LoginError('请选择 Google 桌面应用的客户端 JSON') from None

# ==========================================
# Function: Exchange a code or refresh token without logging secrets or response bodies.
# Method: POST a bounded form to the fixed HTTPS endpoint with normal certificate checks.
# ==========================================
def token_request(provider, values):
    if provider not in OAUTH:raise LoginError('OAuth 提供商无效')
    request=Request(OAUTH[provider]['token'],data=urlencode(values).encode(),
                    headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
    try:
        with urlopen(request,timeout=20) as response:
            if response.geturl()!=OAUTH[provider]['token']:raise LoginError('OAuth 令牌地址发生异常跳转')
            raw=response.read(65537)
        if len(raw)>65536:raise LoginError('OAuth 响应过大')
        result=json.loads(raw)
        if not isinstance(result,dict) or not isinstance(result.get('access_token'),str) or not result['access_token']:
            raise LoginError('授权未返回可用的访问令牌，请重新登录')
        expires=float(result.get('expires_in',3600))
        if not 0<expires<=31536000:raise LoginError('OAuth 令牌有效期无效')
        return {**result,'expires_at':time.time()+expires}
    except Exception:
        raise LoginError('浏览器授权或令牌更新失败，请重新登录；请检查应用配置及提供商权限。') from None

# ==========================================
# Function: Encode a refreshable credential for the existing encrypted credential vault.
# Method: Use an explicit version prefix and retain only required token metadata.
# ==========================================
def encode_oauth(provider, client_id, token, client_secret=''):
    validate_client(provider,client_id,client_secret)
    value={'provider':provider,'client_id':client_id,'client_secret':client_secret,
           'access_token':token['access_token'],'refresh_token':token.get('refresh_token',''),
           'expires_at':float(token.get('expires_at',0))}
    return TOKEN_PREFIX+json.dumps(value,separators=(',',':'))

# ==========================================
# Function: Recognize and validate a persisted OAuth credential envelope.
# Method: Keep legacy raw access tokens and passwords distinct from refreshable bundles.
# ==========================================
def decode_oauth(value):
    if not isinstance(value,str) or not value.startswith(TOKEN_PREFIX):return None
    try:
        data=json.loads(value[len(TOKEN_PREFIX):]);validate_client(data['provider'],data['client_id'],data.get('client_secret',''))
        if not isinstance(data['access_token'],str) or not data['access_token']:raise ValueError()
        if not isinstance(data.get('refresh_token',''),str):raise ValueError()
        float(data['expires_at'])
        return data
    except Exception:raise LoginError('已保存的授权无效，请重新登录') from None

# ==========================================
# Function: Obtain explicit provider consent using a one-use native loopback callback.
# Method: Generate S256 PKCE/state, bind only 127.0.0.1 and close on every outcome.
# ==========================================
def browser_authorize(provider, client_id, email='', client_secret='', cancel=None,
                      opener=None, timeout=180, progress=None):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    client_id=validate_client(provider,client_id,client_secret)
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    result={};path='/oauth/callback'
    # ==========================================
    # Function: Accept only the exact callback path and state once.
    # Method: Reject malformed and cross-site requests without releasing code data.
    # ==========================================
    class Callback(BaseHTTPRequestHandler):
        # ==========================================
        # Function: Handle a single provider callback without rendering untrusted data.
        # Method: Verify path/state and send a fixed local completion page.
        # ==========================================
        def do_GET(self):
            query=urlsplit(self.path);params=parse_qs(query.query,keep_blank_values=True)
            valid=(query.path==path and params.get('state')==[state] and not result
                   and ((len(params.get('code',[]))==1 and 0<len(params['code'][0])<=8192) or len(params.get('error',[]))==1))
            if not valid:
                self.send_error(400,'Invalid callback');return
            if 'error' in params:result['error']=True
            else:result['code']=params['code'][0]
            body=b'<!doctype html><meta charset="utf-8"><title>TeleMail</title><p>Authorization received. Return to TeleMail to finish signing in.</p>'
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'")
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        # ==========================================
        # Function: Prevent callback codes and state from reaching terminal logs.
        # Method: Disable BaseHTTPRequestHandler's URL-bearing access log.
        # ==========================================
        def log_message(self,*unused):pass
    # ==========================================
    # Function: Bound incomplete requests sent to the temporary loopback listener.
    # Method: Set a short accepted-socket timeout so cancellation cannot hang in parsing.
    # ==========================================
    class LoopbackServer(HTTPServer):
        # ==========================================
        # Function: Return an accepted local socket with finite reads.
        # Method: Apply the timeout before BaseHTTPRequestHandler consumes headers.
        # ==========================================
        def get_request(self):
            connection,address=super().get_request();connection.settimeout(1);return connection,address
        # ==========================================
        # Function: Keep malformed callbacks from emitting provider codes to stderr.
        # Method: Suppress server tracebacks; the outer attempt retains its safe timeout.
        # ==========================================
        def handle_error(self,*unused):pass
    server=LoopbackServer(('127.0.0.1',0),Callback);server.timeout=.15
    redirect='http://'+('127.0.0.1' if provider=='google' else 'localhost')+':'+str(server.server_port)+path
    values={'client_id':client_id,'redirect_uri':redirect,'response_type':'code',
            'scope':OAUTH[provider]['scope'],'state':state,'code_challenge':challenge,
            'code_challenge_method':'S256','login_hint':email,'prompt':'select_account'}
    if provider=='google':values.update(access_type='offline',prompt='consent select_account')
    try:
        check_cancel(cancel)
        if progress:progress('browser','waiting')
        if not (opener or webbrowser.open)(OAUTH[provider]['authorize']+'?'+urlencode(values)):
            raise LoginError('无法打开系统浏览器，请检查默认浏览器后重试')
        deadline=time.monotonic()+timeout
        while not result:
            check_cancel(cancel)
            if time.monotonic()>=deadline:raise LoginError('浏览器授权已超时，请重试')
            server.handle_request()
        check_cancel(cancel)
        if result.get('error'):raise LoginError('授权未完成，未添加账户')
    finally:server.server_close()
    values={'client_id':client_id,'code':result['code'],'redirect_uri':redirect,
            'code_verifier':verifier,'grant_type':'authorization_code'}
    if client_secret:values['client_secret']=client_secret
    token=token_request(provider,values);check_cancel(cancel)
    return encode_oauth(provider,client_id,token,client_secret)

# ==========================================
# Function: Expose a descriptive transport-verification entry point for integrations.
# Method: Delegate to the same isolated two-stage implementation used by the wizard.
# ==========================================
def verify_account(account, secret, progress=None, cancel=None):
    return verify_login(account,secret,cancel=cancel,progress=progress)
