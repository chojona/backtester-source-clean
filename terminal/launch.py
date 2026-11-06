"""Launch both loopback-only servers; Ctrl-C stops both processes."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production', action='store_true', help='Use the existing Next.js production build')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    config = repo / 'terminal' / '.env'
    if config.is_file():
        for line in config.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env.setdefault(key.strip(), value.strip().strip('\"').strip("'"))
    if not env.get('NQ_DATA_ROOT'):
        parser.error('Set NQ_DATA_ROOT or copy terminal/.env.example to terminal/.env and edit the data path.')
    if not (repo / 'terminal/web/node_modules').is_dir():
        parser.error('Install frontend dependencies: cd terminal/web && npm ci')
    if args.production and not (repo / 'terminal/web/.next/BUILD_ID').is_file():
        parser.error('Build first: cd terminal/web && npm run build')
    env['NQ_API_URL'] = 'http://127.0.0.1:8000'
    children = []
    def stop(*_):
        for p in children:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        for port in (8000, 3000):
            import socket
            with socket.socket() as sock:
                if sock.connect_ex(('127.0.0.1', port)) == 0:
                    parser.error(f'Port {port} is already occupied. Stop that server before launching.')
        children.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'terminal.api:app', '--host', '127.0.0.1', '--port', '8000'],cwd=repo, env=env, start_new_session=True))
        for _ in range(60):
            if children[0].poll() is not None:
                raise RuntimeError('API exited before readiness')
            try:
                with urlopen('http://127.0.0.1:8000/api/health', timeout=2) as response:
                    if response.status == 200:
                        break
            except HTTPError as exc:
                raise RuntimeError(f"Dataset verification failed: {exc.read().decode()}") from exc
            except URLError:
                time.sleep(.25)
        else:
            raise RuntimeError('Dataset verification failed; inspect the API error above and NQ_DATA_ROOT')
        children.append(subprocess.Popen(['npm', 'run', 'start' if args.production else 'dev'],cwd=repo/'terminal/web',env=env,start_new_session=True))
        print('\nNQ terminal: http://127.0.0.1:3000\nAPI docs: http://127.0.0.1:8000/docs\nCtrl-C stops both servers.\n',flush=True)
        while all(p.poll() is None for p in children):
            time.sleep(.5)
        raise RuntimeError('A terminal server exited unexpectedly')
    except KeyboardInterrupt:
        pass
    finally:
        stop()
        for p in children:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid,signal.SIGKILL)
                p.wait()


if __name__ == '__main__':
    main()
