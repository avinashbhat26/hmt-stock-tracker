import json
import subprocess
from unittest.mock import Mock, patch
import pytest
from state_manager import GitState, LocalState, StateError, empty_state


def git(cwd, *args):
    result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def git_source(tmp_path):
    remote = tmp_path / 'remote.git'
    remote.mkdir()
    git(remote, 'init', '--bare')
    source = tmp_path / 'source'
    source.mkdir()
    git(source, 'init', '-b', 'main')
    git(source, 'config', 'user.name', 'Test')
    git(source, 'config', 'user.email', 'test@example.invalid')
    (source / 'README.md').write_text('test')
    git(source, 'add', 'README.md')
    git(source, 'commit', '-m', 'Initial')
    git(source, 'remote', 'add', 'origin', str(remote))
    git(source, 'push', 'origin', 'main')
    return source


def test_missing_and_corrupt_state(tmp_path):
    path = tmp_path / 'state.json'
    store = LocalState(path)
    assert not store.load()['initialized']
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(StateError):
        store.load()
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(StateError):
        store.load()


def test_atomic_write_failure_keeps_previous(tmp_path):
    store = LocalState(tmp_path / 'state.json')
    store.save(empty_state())
    changed = empty_state()
    changed['failures'] = 2
    with patch('state_manager.os.replace', side_effect=OSError('disk error')):
        with pytest.raises(OSError):
            store.save(changed)
    assert store.load()['failures'] == 0


def test_git_state_persists_across_processes(git_source):
    first = GitState(git_source)
    try:
        state = first.load()
        state['failures'] = 2
        first.save(state)
    finally:
        first.close()
    second = GitState(git_source)
    try:
        assert second.load()['failures'] == 2
        second.save(second.load())
    finally:
        second.close()


def test_conflicting_writer_cannot_overwrite(git_source):
    seed = GitState(git_source)
    seed.save(empty_state())
    seed.close()
    first = GitState(git_source)
    second = GitState(git_source)
    try:
        state = first.load()
        state['failures'] = 1
        first.save(state)
        stale = second.load()
        stale['failures'] = 9
        with pytest.raises(StateError, match='conflict'):
            second.save(stale)
        fresh = GitState(git_source)
        try:
            assert fresh.load()['failures'] == 1
        finally:
            fresh.close()
    finally:
        first.close()
        second.close()


def test_existing_branch_missing_state_is_error(git_source):
    git(git_source, 'push', 'origin', 'main:tracker-state')
    with pytest.raises(StateError, match='missing'):
        GitState(git_source)


def test_remote_failure_does_not_become_new_baseline(git_source):
    git(git_source, 'remote', 'set-url', 'origin', str(git_source / 'nonexistent.git'))
    with pytest.raises(StateError, match='refusing to initialize'):
        GitState(git_source)
