"""Company OIDC bearer authentication and contract-scoped authorization."""
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlsplit
import json
import os
import re
import httpx
import jwt
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

ISSUER = 'http://10.8.6.32:18080/realms/company-dev'
AUDIENCE = 'rixin-contract-review-api'
ROLES = {'agent_admin', 'agent_manager', 'agent_user'}
principal = ContextVar('principal', default=None)

@dataclass(frozen=True)
class Principal:
    sub: str
    roles: frozenset
    profile: dict
    expires_at: float

    @property
    def admin(self):
        return 'agent_admin' in self.roles


def owner_sub():
    user = principal.get()
    return user.sub if user else None


def review_author(field, reported):
    user = principal.get()
    if user is None:
        return {field: reported or '法务审阅员'}
    name = next((value.strip() for value in (user.profile.get('name'), user.profile.get('preferred_username'))
                 if isinstance(value, str) and value.strip()), user.sub)
    return {field: name, field + '_sub': user.sub}


def visible(payload):
    user = principal.get()
    return user is None or user.admin or payload.get('owner_sub') == user.sub


def require_owned(payload):
    if not visible(payload):
        raise HTTPException(404, '记录不存在或无权访问')


def validate_oidc_url(value, local_development=False):
    url = urlsplit(value)
    if url.hostname and not url.username and not url.password:
        if url.scheme == 'https' or (local_development and url.scheme == 'http' and url.netloc == urlsplit(ISSUER).netloc):
            return
    raise ValueError('OIDC 地址必须使用 HTTPS')


class TokenVerifier:
    def __init__(self):
        self.issuer = os.getenv('RIXIN_OIDC_ISSUER', ISSUER).rstrip('/')
        self.local_development = os.getenv('RIXIN_ENV', 'local') == 'local' and self.issuer == ISSUER
        validate_oidc_url(self.issuer, self.local_development)
        self.audience = os.getenv('RIXIN_OIDC_AUDIENCE', AUDIENCE)
        self.jwks = None

    def verify(self, token):
        try:
            if self.jwks is None:
                response = httpx.get(self.issuer + '/.well-known/openid-configuration', timeout=5)
                response.raise_for_status()
                metadata = response.json()
                if metadata['issuer'] != self.issuer:
                    raise ValueError('Issuer mismatch')
                for name, url in metadata.items():
                    if name.endswith('_endpoint') or name == 'jwks_uri':
                        validate_oidc_url(url, self.local_development)
                self.jwks = jwt.PyJWKClient(metadata['jwks_uri'], timeout=5, lifespan=300)
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=['RS256'], issuer=self.issuer,
                                audience=self.audience, options={'require': ['exp', 'iss', 'aud', 'sub']})
            if not isinstance(claims['sub'], str) or not claims['sub'].strip():
                raise ValueError('Missing subject')
            roles = claims.get('resource_access', {}).get(self.audience, {}).get('roles', [])
            if not isinstance(roles, list) or any(not isinstance(r, str) for r in roles):
                raise ValueError('Invalid roles')
            profile = {k: claims.get(k) for k in ('sub', 'preferred_username', 'name', 'email', 'department_code', 'department_name')}
            return Principal(claims['sub'], frozenset(roles) & ROLES, profile, float(claims['exp']))
        except (httpx.HTTPError, jwt.PyJWKClientConnectionError) as exc:
            raise HTTPException(503, '认证服务暂不可用，请稍后重试') from exc
        except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise HTTPException(401, '登录凭证无效或已过期', headers={'WWW-Authenticate': 'Bearer'}) from exc


def service_route(path, method):
    return (method == 'POST' and re.fullmatch(r'/api/v1/onlyoffice/callback/[^/]+', path)) or (
        method == 'GET' and re.fullmatch(r'/api/v1/editor-sessions/[^/]+/file', path))


def install(app, store):
    enabled = os.getenv('RIXIN_AUTH_ENABLED', '1') != '0'
    app.state.auth_enabled = enabled
    app.state.token_verifier = TokenVerifier()

    @app.middleware('http')
    async def authenticate(request, call_next):
        user = None
        path = request.url.path
        try:
            if enabled and (path.startswith('/api/') or path in ('/docs', '/redoc', '/openapi.json')) and not service_route(path, request.method):
                scheme, _, token = request.headers.get('authorization', '').partition(' ')
                if scheme.lower() != 'bearer' or not token.strip():
                    raise HTTPException(401, '请先登录公司统一身份认证', headers={'WWW-Authenticate': 'Bearer'})
                user = await run_in_threadpool(app.state.token_verifier.verify, token)
                if path != '/api/v1/auth/me' and not user.roles:
                    raise HTTPException(403, '当前账号尚未分配本系统角色，请联系管理员')
                if (path.startswith('/api/v1/legal-cases') or path in ('/docs', '/redoc', '/openapi.json')) and not user.admin:
                    raise HTTPException(403, '此功能需要系统管理员角色')
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers=exc.headers)
        marker = principal.set(user)
        request.state.principal = user
        try:
            response = await call_next(request)
            if path.startswith('/api/'):
                response.headers['Cache-Control'] = 'no-store'
            return response
        finally:
            principal.reset(marker)

    @app.get('/api/v1/auth/me')
    def me():
        user = principal.get()
        if user is None:
            return {'enabled': False, 'sub': None, 'roles': []}
        with store.connect() as db:
            db.execute('INSERT INTO auth_users(sub,profile) VALUES(?,?) ON CONFLICT(sub) DO UPDATE SET profile=excluded.profile',
                       (user.sub, json.dumps(user.profile, ensure_ascii=False)))
        return {'enabled': True, **user.profile, 'roles': sorted(user.roles)}


# All resource URL families resolve to a contract before any handler runs.
RESOURCE_SQL = {
    'contracts': 'SELECT id FROM contracts WHERE id=?',
    'versions': 'SELECT contract_id FROM versions WHERE id=?',
    'runs': 'SELECT contract_id FROM runs WHERE id=?',
    'review-records': 'SELECT contract_id FROM runs WHERE id=?',
    'results': 'SELECT r.contract_id FROM results x JOIN runs r ON r.id=x.run_id WHERE x.id=?',
    'extractions': 'SELECT v.contract_id FROM extractions x JOIN versions v ON v.id=x.version_id WHERE x.id=?',
    'editor-sessions': 'SELECT contract_id FROM editor_sessions WHERE id=?',
    'exports': 'SELECT contract_id FROM document_exports WHERE id=?',
    'proposal-operations': 'SELECT contract_id FROM proposal_operations WHERE id=?',
    'subject-checks': 'SELECT contract_id FROM subject_checks WHERE id=?',
}
BODY_RESOURCES = {
    'contract_id': 'contracts', 'document_version_id': 'versions', 'source_version_id': 'versions',
    'expected_version_id': 'versions', 'expected_head_version_id': 'versions',
    'run_id': 'runs', 'parent_run_id': 'runs', 'extraction_id': 'extractions',
    'session_id': 'editor-sessions',
}

async def authorize_resources(request: Request):
    user = principal.get()
    if user is None or user.admin:
        return
    path = request.url.path.split('/')
    resources = []
    if len(path) > 4 and path[3] in RESOURCE_SQL and not (path[3] == 'contracts' and path[4] == 'import'):
        resources.append((path[3], path[4]))
    if request.headers.get('content-type', '').split(';')[0] == 'application/json':
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            body = None
        def collect(value):
            if isinstance(value, dict):
                for key, val in value.items():
                    if key in BODY_RESOURCES and isinstance(val, str) and val:
                        resources.append((BODY_RESOURCES[key], val))
                    elif isinstance(val, (dict, list)):
                        collect(val)
            elif isinstance(value, list):
                for val in value: collect(val)
        collect(body)
    with request.app.state.store.connect() as db:
        for family, ident in resources:
            row = db.execute(RESOURCE_SQL[family], (ident,)).fetchone()
            if row is None:
                raise HTTPException(404, '记录不存在或无权访问')
            contract = db.execute('SELECT payload FROM contracts WHERE id=?', (row[0],)).fetchone()
            require_owned(json.loads(contract[0]))
