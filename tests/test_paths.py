import os
import stat
import subprocess
from pathlib import Path

import pytest

from harness.paths import assert_safe_target, resolve_layout, validate_relative_name


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
