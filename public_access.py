"""Small private-beta gate. Stores only hashed quota identities and counters."""
from contextlib import closing
import hashlib
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from flask import g, jsonify, request


class Quotas:
    def __init__(self, path):
        self.path = path
        self.slots = threading.BoundedSemaphore(2)

    def reserve(self, owner, now=None):
        now = int(time.time() if now is None else now)
        day, minute = now // 86400, now // 60
        identity = hashlib.sha256(owner.encode()).hexdigest()
        limits = [('global', day, 100), (identity, day, 30), ('minute:'+identity, minute, 6)]
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS counts (identity TEXT, window INTEGER, n INTEGER, expires INTEGER, PRIMARY KEY(identity,window))')
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM counts WHERE expires <= ?', (now,))
            for key, window, limit in limits:
                row = db.execute('SELECT n FROM counts WHERE identity=? AND window=?', (key, window)).fetchone()
                if row and row[0] >= limit:
                    return False
            for key, window, _ in limits:
                expires = (minute+1)*60 if key.startswith('minute:') else (day+1)*86400
                db.execute('INSERT INTO counts VALUES (?,?,1,?) ON CONFLICT(identity,window) DO UPDATE SET n=n+1', (key,window,expires))
        return True


def install_public_access(app):
    enabled = os.getenv('RENDER') == 'true' or os.getenv('BAOBAO_PUBLIC_TEST') == '1'
    app.config['PUBLIC_TEST'] = enabled
    # This is a separate beta access password, never the AI credential.
    password = os.getenv('BAOBAO_TEST_PASSWORD', '') if enabled else ''
    quota_path = os.getenv('BAOBAO_QUOTA_PATH', '/tmp/baobao-beta/quotas.sqlite3')
    if enabled:
        Path(quota_path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    quotas = Quotas(quota_path)
    app.extensions['beta_quotas'] = quotas
    attempts = []
    attempt_lock = threading.Lock()

    @app.before_request
    def beta_guard():
        if request.path == '/healthz':
            return jsonify(ok=True)
        if not app.config['PUBLIC_TEST']:
            return None
        if len(password) < 16:
            return jsonify(error='公开测试尚未开放。Private beta is not configured.'), 503
        if not request.is_secure:
            return jsonify(error='请使用 HTTPS 访问。HTTPS is required.'), 403
        auth = request.authorization
        valid = auth and auth.type == 'basic' and secrets.compare_digest((auth.username or '').encode(), b'guest') and secrets.compare_digest((auth.password or '').encode(), password.encode())
        if not valid:
            now = time.monotonic()
            with attempt_lock:
                attempts[:] = [t for t in attempts if now-t < 60]
                if len(attempts) >= 30:
                    return jsonify(error='尝试过于频繁，请稍后重试。Too many attempts.'), 429, {'Retry-After':'60'}
                attempts.append(now)
            return jsonify(error='请输入朋友测试访问口令。Private beta access required.'), 401, {'WWW-Authenticate':'Basic realm="BaoBao private beta", charset="UTF-8"'}
        if request.path != '/analyze':
            return None
        if not quotas.slots.acquire(blocking=False):
            return jsonify(error='当前体验人数较多，请稍后重试。Service busy.'), 429, {'Retry-After':'30'}
        g.beta_slot = True
        try:
            allowed = quotas.reserve(g.chat_owner)
        except (OSError, sqlite3.Error):
            return jsonify(error='额度保护暂不可用，请稍后重试。Quota protection unavailable.'), 503
        if not allowed:
            return jsonify(error='已达到测试频率或今日额度，请稍后或明天再试。Beta rate or daily limit reached.'), 429, {'Retry-After':'60'}

    @app.teardown_request
    def release_slot(_error):
        if getattr(g, 'beta_slot', False):
            g.beta_slot = False
            quotas.slots.release()

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        if app.config['PUBLIC_TEST']:
            response.headers['Cache-Control'] = 'no-store'
            if request.is_secure:
                response.headers['Strict-Transport-Security'] = 'max-age=86400'
        return response
