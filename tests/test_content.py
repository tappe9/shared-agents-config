import os
from pathlib import Path
import pytest

from harness.content import (BEGIN, END, extract_local_suffix, managed_common,
                             render_agents, source_files, validate_sources)
from conftest import git


def test_local_suffix_survives_common_update():
    suffix = b'\n## Local\r\nkeep this text\r\n'
    old = render_agents(b'# Common v1\n', suffix)
    extracted = extract_local_suffix(old)
    updated = render_agents(b'# Common v2\n', extracted)
    assert extracted == suffix
    assert updated.endswith(suffix)
    assert updated.count(b'shared-agents-config:begin') == 1
    assert managed_common(updated) == b'# Common v2\n'


@pytest.mark.parametrize('bom', [b'', b'\xef\xbb\xbf'])
def test_legacy_prefix_migration_preserves_suffix(bom):
    old_common = b'# Common\nrule\n'
    suffix = b'\r\n## Local\r\nkeep\r\n'
    current = bom + b'# Common\r\nrule\r\n' + suffix
    assert extract_local_suffix(current, legacy_common=old_common) == suffix


def test_unknown_prefix_is_not_guessed():
    with pytest.raises(ValueError):
        extract_local_suffix(b'# User custom rules\n', legacy_common=b'# Common\n')


@pytest.mark.parametrize('current', [BEGIN + b'x\n', END + BEGIN, BEGIN + END + END,
    b'prefix\n' + BEGIN + END, BEGIN + BEGIN + END, BEGIN + END.rstrip(b'\n')])
def test_invalid_markers_are_rejected(current):
    with pytest.raises(ValueError):
        extract_local_suffix(current)


def test_bom_crlf_markers_without_suffix():
    original = b'\xef\xbb\xbf' + render_agents(b'# rules\n', b'').replace(b'\n', b'\r\n')
    assert extract_local_suffix(original) == b''
    assert managed_common(original) == b'# rules\n'


def test_valid_sources_and_no_untracked_copy(sandbox):
    sandbox.write('skills/sample/untracked.txt', 'do not copy')
    assert validate_sources(sandbox.repo) == []
    assert 'skills/sample/untracked.txt' not in source_files(sandbox.repo)


def test_binary_asset_is_preserved(sandbox):
    sandbox.write('skills/sample/assets/icon.bin', b'\x00\xff\x80')
    sandbox.commit()
    assert source_files(sandbox.repo)['skills/sample/assets/icon.bin'] == b'\x00\xff\x80'


@pytest.mark.parametrize('name', ['skills/sample/.env', 'skills/sample/auth.json',
                                 'skills/sample/local.toml'])
def test_tracked_secret_files_are_rejected(sandbox, name):
    sandbox.write(name, 'do not distribute')
    sandbox.commit()
    assert validate_sources(sandbox.repo)


def test_missing_reference_is_rejected(sandbox):
    sandbox.write('skills/sample/SKILL.md', '---\nname: sample\ndescription: Test\n---\nRead `references/missing.md`.\n')
    assert any(p.code == 'missing-reference' for p in validate_sources(sandbox.repo))


def test_duplicate_yaml_keys_are_rejected(sandbox):
    sandbox.write('skills/sample/SKILL.md', '---\nname: sample\nname: other\ndescription: Test\n---\n')
    assert any(p.code == 'invalid-skill' for p in validate_sources(sandbox.repo))


def test_role_allowlist_is_checked(sandbox):
    sandbox.write('AGENTS.md', 'Allowed `agent_type`: `different`\n')
    assert any(p.code == 'role-allowlist' for p in validate_sources(sandbox.repo))


def test_invalid_toml_and_skill_types(sandbox):
    sandbox.write('agents/explorer.toml', 'SECRET = "unterminated')
    sandbox.write('skills/sample/SKILL.md', '---\nname: sample\ndescription: 123\n---\n')
    problems = validate_sources(sandbox.repo)
    assert len(problems) >= 2
    assert 'SECRET' not in repr(problems)


def test_tracked_symlink_rejected(sandbox):
    target = sandbox.repo / 'skills/sample/link'
    try:
        target.symlink_to(sandbox.repo / 'AGENTS.md')
    except OSError:
        pytest.skip('Symlink creation is not permitted')
    sandbox.commit()
    assert validate_sources(sandbox.repo)


def test_git_reference_is_resolved_safely(sandbox):
    sha = git(sandbox.repo, 'rev-parse', 'HEAD')
    assert source_files(sandbox.repo, ref=sha)['AGENTS.md'].startswith(b'# Common')
    with pytest.raises(ValueError):
        source_files(sandbox.repo, ref='--help')


def _write_role(sandbox, extra=''):
    sandbox.write(
        'agents/explorer.toml',
        'name="explorer"\n'
        'description="test"\n'
        'developer_instructions="test"\n' + extra,
    )


@pytest.mark.parametrize('model_line', ['model=123\n', 'model=""\n', 'model="   "\n'])
def test_role_model_must_be_non_empty_string(sandbox, model_line):
    _write_role(sandbox, model_line)
    problems = validate_sources(sandbox.repo)
    problem = next(p for p in problems if p.code == 'invalid-role')
    assert problem.target_id == 'codex:agents/explorer.toml'
    assert 'model' in problem.message
    assert model_line.strip() not in repr(problems)


def test_role_reasoning_effort_rejects_undocumented_value(sandbox):
    _write_role(sandbox, 'model_reasoning_effort="definitely-invalid"\n')
    problems = validate_sources(sandbox.repo)
    problem = next(p for p in problems if p.code == 'invalid-role')
    assert problem.target_id == 'codex:agents/explorer.toml'
    assert 'model_reasoning_effort' in problem.message
    assert 'definitely-invalid' not in repr(problems)


def test_role_sandbox_mode_rejects_invalid_value(sandbox):
    _write_role(sandbox, 'sandbox_mode="definitely-invalid"\n')
    problems = validate_sources(sandbox.repo)
    problem = next(p for p in problems if p.code == 'invalid-role')
    assert problem.target_id == 'codex:agents/explorer.toml'
    assert 'sandbox_mode' in problem.message
    assert 'definitely-invalid' not in repr(problems)


def test_role_unknown_key_is_rejected_without_exposing_value(sandbox):
    _write_role(sandbox, 'modle="SECRET_ROLE_VALUE"\n')
    problems = validate_sources(sandbox.repo)
    problem = next(p for p in problems if p.code == 'invalid-role')
    assert problem.target_id == 'codex:agents/explorer.toml'
    assert 'modle' in problem.message
    assert 'SECRET_ROLE_VALUE' not in repr(problems)


def test_role_accepts_optional_codex_setting_from_pinned_schema(sandbox):
    _write_role(sandbox, 'model_reasoning_summary="concise"\n')
    assert validate_sources(sandbox.repo) == []


def test_role_optional_model_reasoning_and_sandbox_settings_may_be_omitted(sandbox):
    _write_role(sandbox)
    assert validate_sources(sandbox.repo) == []


def test_current_repository_role_definitions_validate():
    root = Path(__file__).resolve().parents[1]
    invalid_roles = [p for p in validate_sources(root) if p.code == 'invalid-role']
    assert invalid_roles == []
