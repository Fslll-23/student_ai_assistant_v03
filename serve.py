"""Production entry point: one worker owns the temporary attachment contexts."""
import os
from gunicorn.app.base import BaseApplication


class Server(BaseApplication):
    def load_config(self):
        # Explicit settings avoid Render's inherited --preload and worker defaults.
        for name, value in {
            'bind': '0.0.0.0:' + os.getenv('PORT', '10000'),
            'workers': 1, 'threads': 4, 'worker_class': 'gthread',
            'timeout': 120, 'preload_app': False,
            'accesslog': None, 'errorlog': '-',
            'forwarded_allow_ips': '*' if os.getenv('RENDER') == 'true' else '127.0.0.1,::1',
        }.items():
            self.cfg.set(name, value)

    def load(self):
        from app import app
        return app


if __name__ == '__main__':
    Server().run()
