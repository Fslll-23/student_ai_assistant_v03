import os
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask, g, jsonify
from public_access import install_public_access, Quotas


class PublicAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.password = 'test-only-long-beta-password'
        self.env = patch.dict(os.environ, {'BAOBAO_PUBLIC_TEST':'1', 'BAOBAO_TEST_PASSWORD':self.password, 'BAOBAO_QUOTA_PATH':self.tmp.name+'/quota.sqlite3'})
        self.env.start()
        self.app = Flask(__name__)
        @self.app.before_request
        def owner():
            g.chat_owner = 'browser-one'
        install_public_access(self.app)
        @self.app.route('/analyze', methods=['POST'])
        def analyze():
            return jsonify(ok=True)
        self.client = self.app.test_client()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def send(self, **kwargs):
        return self.client.post('/analyze', base_url='https://example.test', auth=('guest',self.password), **kwargs)

    def test_auth_tls_and_health(self):
        self.assertEqual(self.client.get('/healthz').status_code,200)
        self.assertEqual(self.client.post('/analyze').status_code,403)
        self.assertEqual(self.client.post('/analyze',base_url='https://example.test').status_code,401)
        self.assertEqual(self.send().status_code,200)
        self.assertIn('max-age',self.send().headers['Strict-Transport-Security'])

    def test_rate_and_concurrency_release(self):
        for _ in range(6): self.assertEqual(self.send().status_code,200)
        self.assertEqual(self.send().status_code,429)
        quotas=self.app.extensions['beta_quotas']
        self.assertTrue(quotas.slots.acquire(False));self.assertTrue(quotas.slots.acquire(False))
        self.assertEqual(self.send().status_code,429)
        quotas.slots.release();quotas.slots.release()

    def test_persistent_daily_and_global_caps(self):
        path=self.tmp.name+'/limits.sqlite3'
        quotas=Quotas(path)
        for n in range(30): self.assertTrue(quotas.reserve('one',n*61))
        self.assertFalse(Quotas(path).reserve('one',2000))
        for n in range(70): self.assertTrue(quotas.reserve('other'+str(n),2100))
        self.assertFalse(quotas.reserve('fresh-cookie',2100))
        self.assertTrue(quotas.reserve('one',86400))
        with open(path,'rb') as f: self.assertNotIn(b'fresh-cookie',f.read())

    def test_missing_password_fails_closed(self):
        with patch.dict(os.environ, {'BAOBAO_TEST_PASSWORD':''}):
            app=Flask('missing');install_public_access(app)
        self.assertEqual(app.test_client().get('/',base_url='https://example.test').status_code,503)

    def test_real_routes_gate_upload_limit_and_no_ai(self):
        from test_app import isolated_app
        app = isolated_app()
        client = app.test_client()
        with patch('requests.post') as upstream:
            self.assertEqual(client.post('/analyze',base_url='https://example.test',data={'text':'hello'}).status_code,401)
            response = client.post('/analyze',base_url='https://example.test',auth=('guest',self.password),data=b'x'*(18*1024*1024+1),content_type='application/x-www-form-urlencoded')
            self.assertEqual(response.status_code,413)
            response = client.post('/analyze',base_url='https://example.test',auth=('guest',self.password),data={'text':'hi','school':'x'*180001})
            self.assertEqual(response.status_code,413)
            upstream.assert_not_called()
