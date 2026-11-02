"""Atomic local state and a dedicated Git branch with non-force conflict protection."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile


class StateError(RuntimeError):
    pass


def empty_state():
    return {'version': 1, 'initialized': False, 'products': {}, 'pending': [],
            'sent': [], 'history': [], 'last_success': None, 'failures': 0,
            'failure_notified': False, 'scan_sequence': 0}


def validate(state):
    template = empty_state()
    if not isinstance(state, dict) or state.get('version') != 1:
        raise StateError('Unsupported or corrupt state; restore a valid state commit.')
    for key, value in template.items():
        if key not in state or (value is not None and type(state[key]) is not type(value)):
            raise StateError(f'Invalid state field: {key}')
    for key, product in state['products'].items():
        if (not isinstance(product, dict) or product.get('id') != key
                or product.get('status') not in {'in_stock', 'out_of_stock', 'unknown'}
                or product.get('confirmed') not in {'in_stock', 'out_of_stock', None}
                or not all(k in product for k in ('name', 'url', 'first_seen', 'last_seen',
                                                 'transition', 'missing_scans'))):
            raise StateError('Corrupt product state; refusing to reset history.')
    for event in state['pending']:
        if not isinstance(event, dict) or not all(k in event for k in ('id', 'type', 'time')):
            raise StateError('Corrupt pending notification.')
    return state


class LocalState:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return empty_state()
        try:
            return validate(json.loads(self.path.read_text(encoding='utf-8')))
        except (ValueError, OSError) as exc:
            raise StateError('Cannot read state; restore from backup rather than reset.') from exc

    def save(self, state):
        validate(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.state-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


class GitState(LocalState):
    """Use checkout credentials without copying tokens into source or command arguments."""
    def __init__(self, source='.', branch='tracker-state'):
        self.source = Path(source).resolve()
        self.branch = branch
        self.temp = tempfile.TemporaryDirectory(prefix='hmt-state-')
        self.repo = Path(self.temp.name)
        origin = self._git('remote', 'get-url', 'origin', cwd=self.source).stdout.strip()
        self._git('init', '-b', branch)
        self._git('remote', 'add', 'origin', origin)
        # actions/checkout credentials are repository-local. Copy only that setting.
        headers = self._git('config', '--get-regexp', r'http\..*\.extraheader',
                            cwd=self.source, check=False)
        if headers.returncode not in (0, 1):
            raise StateError('Cannot read checkout authentication configuration.')
        for line in headers.stdout.splitlines():
            key, value = line.split(' ', 1)
            self._git('config', key, value)
        exists = self._git('ls-remote', '--exit-code', '--heads', 'origin',
                           f'refs/heads/{branch}', check=False)
        if exists.returncode == 0:
            self._git('fetch', '--depth=1', 'origin', f'refs/heads/{branch}')
            self._git('checkout', '-B', branch, 'FETCH_HEAD')
            if not (self.repo / 'state.json').exists():
                raise StateError('State branch exists but state.json is missing.')
        elif exists.returncode != 2:
            raise StateError('Cannot read remote state branch; refusing to initialize.')
        self._git('config', 'user.name', 'hmt-stock-tracker[bot]')
        self._git('config', 'user.email', 'hmt-stock-tracker@users.noreply.github.com')
        super().__init__(self.repo / 'state.json')

    def _git(self, *args, cwd=None, check=True):
        result = subprocess.run(['git', *args], cwd=cwd or self.repo,
                                capture_output=True, text=True, timeout=90)
        if check and result.returncode:
            # Git stderr can contain credential-bearing URLs: keep it out of logs.
            raise StateError(f'Git {args[0]} failed; remote access or state conflict. No force push attempted.')
        return result

    def save(self, state):
        super().save(state)
        self._git('add', 'state.json')
        diff = self._git('diff', '--cached', '--quiet', check=False)
        if diff.returncode == 0:
            return
        if diff.returncode != 1:
            raise StateError('Cannot inspect state changes.')
        self._git('commit', '-m', 'Persist HMT tracker state')
        # A rejected push aborts before further notifications; rerun reloads remote.
        self._git('push', 'origin', f'HEAD:refs/heads/{self.branch}')

    def close(self):
        self.temp.cleanup()
