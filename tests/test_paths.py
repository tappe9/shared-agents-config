import os
import json
import stat
import subprocess
from pathlib import Path

import pytest

from harness.paths import assert_safe_target, resolve_layout, same_path, validate_relative_name


def test_codex_home_does_not_relocate_user_skills(tmp_path):
    home = tmp_path / 'User With Spaces \u30c6\u30b9\u30c8'
    layout = resolve_layout(tmp_path / 'repo', home=home, codex_home=None,
                            env={'CODEX_HOME': str(tmp_path / 'custom-codex')})
    assert layout.codex_home == tmp_path / 'custom-codex'
    assert layout.skills_home == home / '.agents' / 'skills'
    assert not home.exists()


def test_cli_path_overrides_environment(tmp_path):
    layout = resolve_layout(tmp_path, home=tmp_path / 'home',
                            codex_home=tmp_path / 'explicit', env={'CODEX_HOME': 'other'})
    assert layout.codex_home == tmp_path / 'explicit'


def test_default_paths(tmp_path):
    layout = resolve_layout(tmp_path, home=tmp_path / 'home', codex_home=None, env={})
    assert layout.state_dir == tmp_path / 'home/.codex/shared-agents-config'
    assert layout.repo == tmp_path


@pytest.mark.parametrize('name', ['', '.', '..', '../other', 'a/b', 'a\\b', 'x:y',
                                  'CON', 'NUL.txt', 'trailing.', 'a\n', 'a ', '/root'])
def test_skill_directory_name_rejects_escape(name):
    with pytest.raises(ValueError):
        validate_relative_name(name)


def test_normal_name():
    assert validate_relative_name('implementing-repository-changes') == 'implementing-repository-changes'


def test_safe_target_does_not_create_directories(tmp_path):
    root = tmp_path / 'new'
    assert_safe_target(root, root / 'agents/explorer.toml')
    assert not root.exists()


def test_escape_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        assert_safe_target(tmp_path / 'root', tmp_path / 'other/file')
    with pytest.raises(ValueError):
        assert_safe_target(tmp_path / 'root', tmp_path / 'root/../file')


def test_symlink_parent_is_rejected(tmp_path):
    root, outside = tmp_path / 'root', tmp_path / 'outside'
    root.mkdir(); outside.mkdir()
    try:
        (root / 'linked').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink creation is not permitted')
    with pytest.raises(ValueError):
        assert_safe_target(root, root / 'linked/file')
    with pytest.raises(ValueError):
        assert_safe_target(root / 'linked', root / 'linked/file')


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction creation requires Windows')
def test_windows_junction_is_rejected(tmp_path):
    root, outside = tmp_path / 'root', tmp_path / 'outside'
    root.mkdir(); outside.mkdir()
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(root / 'linked'), str(outside)],
                            capture_output=True)
    if result.returncode:
        pytest.skip('Junction creation is not permitted')
    with pytest.raises(ValueError):
        assert_safe_target(root, root / 'linked/file')
    assert not (outside / 'file').exists()


def test_same_directory_hardlink_names_are_distinct(tmp_path):
    first = tmp_path / 'first.md'
    second = tmp_path / 'second.md'
    first.write_text('skill')
    try:
        os.link(first, second)
    except OSError as error:
        pytest.skip(f'同一ディレクトリ内hardlinkを作成できない: {error.__class__.__name__}')

    assert first.samefile(second)
    assert same_path(first, second) is False


def test_case_distinct_hardlink_entries_are_distinct(tmp_path):
    upper = tmp_path / 'A.md'
    lower = tmp_path / 'a.md'
    upper.write_text('skill')
    if lower.exists():
        pytest.skip('このファイルシステムでは大小文字違いが同じdirentを指す')
    try:
        os.link(upper, lower)
    except OSError as error:
        pytest.skip(f'大小文字違いhardlinkを作成できない: {error.__class__.__name__}')

    assert upper.samefile(lower)
    assert same_path(upper, lower) is False


def test_existing_case_distinct_files_are_distinct(tmp_path):
    upper = tmp_path / 'A.md'
    lower = tmp_path / 'a.md'
    upper.write_text('upper')
    try:
        lower.write_text('lower')
    except OSError as error:
        pytest.skip(f'大小文字違いファイルを作成できない: {error.__class__.__name__}')
    if upper.samefile(lower):
        pytest.skip('このファイルシステムでは大小文字違いが同じdirentを指す')

    assert same_path(upper, lower) is False


def test_case_alias_updates_one_override(tmp_path):
    import tomllib

    from harness.config_merge import merge_skill_overrides

    real_path = tmp_path / 'Foo' / 'SKILL.md'
    real_path.parent.mkdir()
    real_path.write_text('skill')
    alias_path = tmp_path / 'foo' / 'skill.md'
    if not alias_path.exists() or not real_path.samefile(alias_path):
        pytest.skip('このファイルシステムでは大小文字aliasが同じdirentを指さない')

    assert same_path(real_path, alias_path) is True
    original = (
        f'[[skills.config]]\npath = {json.dumps(str(real_path))}\n'
        'enabled = true\n'
    ).encode()
    updated = merge_skill_overrides(original, {alias_path: False})
    entries = tomllib.loads(updated.decode())['skills']['config']
    assert len(entries) == 1
    assert entries[0]['path'] == str(real_path)
    assert entries[0]['enabled'] is False


def test_case_alias_updates_one_override_with_same_inode_hardlink(tmp_path):
    import tomllib

    from harness.config_merge import merge_skill_overrides

    real_path = tmp_path / 'Foo' / 'SKILL.md'
    real_path.parent.mkdir()
    real_path.write_text('skill')
    alias_path = tmp_path / 'foo' / 'skill.md'
    if not alias_path.exists() or not real_path.samefile(alias_path):
        pytest.skip('このファイルシステムでは大小文字aliasが同じdirentを指さない')

    other_hardlink = real_path.parent / 'OTHER.md'
    try:
        os.link(real_path, other_hardlink)
    except OSError as error:
        pytest.skip(f'case aliasと同じ親内に別名hardlinkを作成できない: {error.__class__.__name__}')

    original = (
        f'[[skills.config]]\npath = {json.dumps(str(real_path))}\n'
        'enabled = true\n'
    ).encode()
    updated = merge_skill_overrides(original, {alias_path: False})
    entries = tomllib.loads(updated.decode())['skills']['config']
    assert len(entries) == 1
    assert entries[0]['path'] == str(real_path)
    assert entries[0]['enabled'] is False


def test_path_identity_handles_missing_and_unreadable_entries(tmp_path, monkeypatch):
    missing = tmp_path / 'absent' / 'SKILL.md'
    assert same_path(missing, missing) is True
    assert same_path(missing, tmp_path / 'other' / 'SKILL.md') is False

    left, right = tmp_path / 'left.md', tmp_path / 'right.md'
    left.write_text('left')
    right.write_text('right')

    original_scandir = os.scandir
    scandir_attempts = []

    def unreadable_scandir(path):
        if os.fspath(path) == os.fspath(tmp_path):
            scandir_attempts.append(os.fspath(path))
            raise OSError('private path details')
        return original_scandir(path)

    monkeypatch.setattr(os, 'scandir', unreadable_scandir)
    assert same_path(left, right) is False
    assert scandir_attempts


def test_same_path_rejects_symlink_alias(tmp_path):
    target = tmp_path / 'target.md'
    alias = tmp_path / 'alias.md'
    target.write_text('skill')
    try:
        alias.symlink_to(target)
    except OSError as error:
        pytest.skip(f'シンボリックリンクを作成できない: {error.__class__.__name__}')

    assert same_path(alias, target) is False


def test_same_existing_spelling_survives_parent_scan_failure(tmp_path, monkeypatch):
    target = tmp_path / 'skill' / 'SKILL.md'
    target.parent.mkdir()
    target.write_text('skill')

    original_scandir = os.scandir

    def denied_scandir(path):
        if os.fspath(path) == os.fspath(target.parent):
            raise PermissionError('injected parent scan denial')
        return original_scandir(path)

    monkeypatch.setattr(os, 'scandir', denied_scandir)
    assert same_path(target, target) is True
