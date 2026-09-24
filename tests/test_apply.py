import json
import os
import shutil
import stat
from dataclasses import replace

import pytest

from conftest import git
from harness import sync
from harness.content import render_agents
from harness.paths import resolve_layout
from harness.sync import apply_plan, build_plan, verify_deployment


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def apply(sandbox):
    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))
    assert not result.problems
    return result


def test_second_apply_is_noop(sandbox):
    apply(sandbox)
    assert verify_deployment(sandbox.layout) == []
    before = snapshot(sandbox.layout.home)
    second = apply(sandbox)
    assert second.changed_ids == []
    assert snapshot(sandbox.layout.home) == before


def test_crlf_legacy_role_is_adopted_and_verified(sandbox):
    old = git(sandbox.repo, 'rev-parse', 'HEAD')
    target = sandbox.layout.codex_home / 'agents/explorer.toml'
    target.parent.mkdir(parents=True)
    legacy = (sandbox.repo / 'agents/explorer.toml').read_bytes()
    target.write_bytes(legacy.replace(b'\n', b'\r\n'))
    sandbox.write('agents/explorer.toml',
                  'name="explorer"\ndescription="updated"\ndeveloper_instructions="test"\n')
    sandbox.commit()

    result = apply_plan(sandbox.layout, build_plan(sandbox.layout, adopt_from=old))
    assert not result.problems
    assert target.read_bytes() == (sandbox.repo / 'agents/explorer.toml').read_bytes()
    assert verify_deployment(sandbox.layout) == []


def test_source_update_preserves_suffix_and_unmanaged_config(sandbox):
    apply(sandbox)
    target = sandbox.layout.codex_home / 'AGENTS.md'
    suffix = b'\r\n## Local\r\nprivate local text\r\n'
    target.write_bytes(target.read_bytes() + suffix)
    config = sandbox.layout.codex_home / 'config.toml'
    config.write_bytes(b'# comment\nmodel="user-model"\n')
    sandbox.write('AGENTS.md', '# Updated\nAllowed `agent_type`: `explorer`\n')
    sandbox.commit()
    apply(sandbox)
    assert target.read_bytes().endswith(suffix)
    assert config.read_bytes() == b'# comment\nmodel="user-model"\n'
    assert verify_deployment(sandbox.layout) == []


def test_local_managed_edit_is_not_overwritten(sandbox):
    apply(sandbox)
    role = sandbox.layout.codex_home / 'agents/explorer.toml'
    role.write_bytes(role.read_bytes() + b'# local modification\n')
    before = snapshot(sandbox.layout.home)
    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))
    assert any(p.code == 'conflict' for p in result.problems)
    assert snapshot(sandbox.layout.home) == before


def test_common_edit_is_a_conflict_but_suffix_edit_is_not(sandbox):
    apply(sandbox)
    dest = sandbox.layout.codex_home / 'AGENTS.md'
    dest.write_bytes(dest.read_bytes().replace(b'# Common', b'# Local'))
    assert build_plan(sandbox.layout).problems


def test_manual_enabled_change_is_a_conflict(sandbox):
    target = sandbox.layout.skills_home / 'brainstorming/SKILL.md'
    target.parent.mkdir(parents=True); target.write_text('skill')
    apply(sandbox)
    config = sandbox.layout.codex_home / 'config.toml'
    config.write_bytes(config.read_bytes().replace(b'false', b'true'))
    before = snapshot(sandbox.layout.home)
    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))
    assert result.problems
    assert snapshot(sandbox.layout.home) == before


def test_conflict_prevents_all_writes(sandbox):
    target = sandbox.layout.codex_home / 'agents/explorer.toml'
    target.parent.mkdir(parents=True); target.write_text('conflict')
    before = snapshot(sandbox.layout.home)
    assert apply_plan(sandbox.layout, build_plan(sandbox.layout)).problems
    assert snapshot(sandbox.layout.home) == before
    assert not (sandbox.layout.codex_home / 'AGENTS.md').exists()


def test_dirty_source_cannot_be_applied(sandbox):
    sandbox.write('untracked.txt', 'uncommitted')
    assert any(p.code == 'dirty-source' for p in apply_plan(sandbox.layout, build_plan(sandbox.layout)).problems)
    assert not sandbox.layout.home.exists()


def test_plan_is_rechecked_before_apply(sandbox):
    plan = build_plan(sandbox.layout)
    sandbox.write('AGENTS.md', '# Changed\nAllowed `agent_type`: `explorer`\n')
    sandbox.commit()
    result = apply_plan(sandbox.layout, plan)
    assert result.problems
    assert not (sandbox.layout.codex_home / 'AGENTS.md').exists()


def test_failure_does_not_record_success_and_retry_continues(sandbox, monkeypatch):
    original = sync.atomic_write
    def fail_on_role(root, target, data, expected):
        if target.name == 'explorer.toml':
            raise PermissionError('PRIVATE_PATH')
        original(root, target, data, expected)
    monkeypatch.setattr(sync, 'atomic_write', fail_on_role)
    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))
    assert result.problems
    assert result.changed_ids == ['codex:AGENTS.md']
    assert not (sandbox.layout.state_dir / 'state.json').exists()
    assert 'PRIVATE_PATH' not in repr(result)
    monkeypatch.setattr(sync, 'atomic_write', original)
    apply(sandbox)
    assert verify_deployment(sandbox.layout) == []


def test_state_write_failure_is_not_success(sandbox, monkeypatch):
    original = sync.atomic_write
    def fail_on_state(root, target, data, expected):
        if target.name == 'state.json':
            raise PermissionError('STATE_SECRET')
        original(root, target, data, expected)
    monkeypatch.setattr(sync, 'atomic_write', fail_on_state)
    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))
    assert result.problems
    assert not (sandbox.layout.state_dir / 'state.json').exists()
    assert verify_deployment(sandbox.layout)


def test_preexisting_lock_is_not_removed(sandbox):
    sandbox.layout.state_dir.mkdir(parents=True)
    lock = sandbox.layout.state_dir / 'apply.lock'
    lock.write_text('another process')
    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))
    assert any(p.code == 'locked' for p in result.problems)
    assert lock.read_text() == 'another process'
    assert not (sandbox.layout.codex_home / 'AGENTS.md').exists()


def test_external_edit_before_write_is_not_overwritten(sandbox, monkeypatch):
    original = sync.atomic_write
    def concurrent(root, target, data, expected):
        if target.name == 'AGENTS.md':
            target.write_bytes(b'external edit')
        original(root, target, data, expected)
    monkeypatch.setattr(sync, 'atomic_write', concurrent)
    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))
    assert result.problems
    assert (sandbox.layout.codex_home / 'AGENTS.md').read_bytes() == b'external edit'
    assert not (sandbox.layout.state_dir / 'state.json').exists()


def test_retired_files_remain_tracked_across_applies(sandbox):
    apply(sandbox)
    (sandbox.repo / 'skills/sample/SKILL.md').unlink()
    sandbox.commit()
    apply(sandbox)
    state_path = sandbox.layout.state_dir / 'state.json'
    assert 'skills:sample/SKILL.md' in json.loads(state_path.read_bytes())['retired_files']
    apply(sandbox)
    assert any(p.code == 'retired' for p in verify_deployment(sandbox.layout))
    (sandbox.layout.skills_home / 'sample/SKILL.md').unlink()
    apply(sandbox)
    assert not json.loads(state_path.read_bytes())['retired_files']


def test_state_from_other_home_is_rejected(sandbox, tmp_path):
    apply(sandbox)
    other = resolve_layout(sandbox.repo, home=tmp_path / 'other', codex_home=None, env={})
    other.state_dir.mkdir(parents=True)
    shutil.copy(sandbox.layout.state_dir / 'state.json', other.state_dir / 'state.json')
    assert any(p.code == 'invalid-state' for p in build_plan(other).problems)


def test_commit_only_update_does_not_rewrite_managed_files(sandbox):
    apply(sandbox)
    target = sandbox.layout.codex_home / 'AGENTS.md'
    before = target.stat().st_mtime_ns
    sha = sandbox.commit()
    apply(sandbox)
    assert target.stat().st_mtime_ns == before
    assert json.loads((sandbox.layout.state_dir / 'state.json').read_bytes())['source_commit'] == sha


@pytest.mark.skipif(os.name == 'nt', reason='POSIX modes are not Windows ACLs')
def test_existing_permissions_are_preserved(sandbox):
    apply(sandbox)
    target = sandbox.layout.codex_home / 'agents/explorer.toml'
    target.chmod(0o640)
    sandbox.write('agents/explorer.toml', (sandbox.repo / 'agents/explorer.toml').read_bytes() + b'# new\n')
    sandbox.commit(); apply(sandbox)
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert stat.S_IMODE((sandbox.layout.state_dir / 'state.json').stat().st_mode) == 0o600


def test_atomic_replace_failure_removes_temporary_file(sandbox, monkeypatch):
    sandbox.layout.codex_home.mkdir(parents=True)
    target = sandbox.layout.codex_home / 'AGENTS.md'
    target.write_bytes(b'keep')
    def fail(*args):
        raise PermissionError('file in use')
    monkeypatch.setattr(sync.os, 'replace', fail)
    with pytest.raises(PermissionError):
        sync.atomic_write(sandbox.layout.codex_home, target, b'new', b'keep')
    assert target.read_bytes() == b'keep'
    assert sorted(p.name for p in target.parent.iterdir()) == ['AGENTS.md']


@pytest.mark.skipif(os.name != 'nt', reason='Windows sharing-mode verification')
def test_windows_file_in_use_does_not_record_success(sandbox):
    import ctypes
    from ctypes import wintypes
    assert not apply_plan(sandbox.layout, build_plan(sandbox.layout)).problems
    target = sandbox.layout.codex_home / 'agents/explorer.toml'
    before = target.read_bytes()
    state = (sandbox.layout.state_dir / 'state.json').read_bytes()
    sandbox.write('agents/explorer.toml', before + b'\n# update\n')
    sandbox.commit()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(target), 0x80000000, 1, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value
    try:
        result = apply_plan(sandbox.layout, build_plan(sandbox.layout))
        assert result.problems
        assert target.read_bytes() == before
        assert (sandbox.layout.state_dir / 'state.json').read_bytes() == state
    finally:
        kernel.CloseHandle(handle)
