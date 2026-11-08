import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def invoke(sandbox, command, *options):
    return subprocess.run(
        [sys.executable, '-m', 'harness', command,
         '--repo', str(sandbox.repo), '--home', str(sandbox.layout.home),
         '--codex-home', str(sandbox.layout.codex_home), *options],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True, text=True, timeout=30,
    )


def test_cli_plan_apply_verify(sandbox):
    assert invoke(sandbox, 'validate').returncode == 0
    result = invoke(sandbox, 'plan', '--json')
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report['operations']
    assert 'desired_bytes' not in result.stdout and str(sandbox.layout.home) not in result.stdout
    assert not sandbox.layout.home.exists()
    assert invoke(sandbox, 'apply').returncode == 0
    assert invoke(sandbox, 'verify', '--json').returncode == 0
    assert invoke(sandbox, 'plan').returncode == 0


def test_cli_metadata_only_update_is_a_difference(sandbox):
    assert invoke(sandbox, 'apply').returncode == 0
    sandbox.commit()
    assert invoke(sandbox, 'plan').returncode == 1
    assert invoke(sandbox, 'apply').returncode == 0
    assert invoke(sandbox, 'plan').returncode == 0


def test_cli_config_secret_never_appears(sandbox):
    path = sandbox.layout.codex_home / 'config.toml'
    path.parent.mkdir(parents=True)
    path.write_text('SECRET_DO_NOT_OUTPUT = "unterminated', encoding='utf-8')
    for command in ('plan', 'apply', 'verify'):
        result = invoke(sandbox, command)
        assert result.returncode == 2
        assert 'SECRET_DO_NOT_OUTPUT' not in result.stdout + result.stderr
        assert 'Traceback' not in result.stderr


def test_cli_unknown_legacy_is_not_overwritten(sandbox):
    path = sandbox.layout.codex_home / 'AGENTS.md'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'private local instructions\n')
    result = invoke(sandbox, 'apply')
    assert result.returncode == 2
    assert path.read_bytes() == b'private local instructions\n'
    assert 'private local instructions' not in result.stdout + result.stderr


def test_cli_doctor_does_not_write_and_record_is_explicit(sandbox):
    first = invoke(sandbox, 'doctor')
    assert first.returncode == 0
    assert not sandbox.layout.home.exists()
    result = invoke(sandbox, 'doctor', '--record')
    assert result.returncode == 0
    report = json.loads((sandbox.layout.state_dir / 'diagnostics.json').read_text())
    assert report['applied_source_commit'] is None
    assert len(report['source_commit']) == 40
    assert all(check['status'] == 'ok' for check in report['checks'])
    assert 'recorded' in result.stdout


def test_cli_doctor_returns_warning_only_for_actual_warning(sandbox):
    path = sandbox.layout.codex_home / 'AGENTS.override.md'
    path.parent.mkdir(parents=True)
    path.write_text('local override', encoding='utf-8')
    result = invoke(sandbox, 'doctor')
    assert result.returncode == 1
    assert 'warn global-override' in result.stdout


@pytest.mark.parametrize(('section', 'key'), [
    ('superpowers', 'skills_rooot'),
    ('git_commit', 'skill_flie'),
    ('client', 'vresion'),
])
@pytest.mark.parametrize('explicit', [False, True], ids=['default-config', 'explicit-config'])
def test_cli_doctor_unknown_local_key_returns_warning(sandbox, tmp_path, section, key, explicit):
    config = tmp_path / 'local.toml' if explicit else sandbox.layout.local_config
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f'schema_version=1\n[{section}]\n{key}="ignored typo"\n', encoding='utf-8')
    options = ('--local-config', str(config)) if explicit else ()

    result = invoke(sandbox, 'doctor', *options)

    assert result.returncode == 1
    assert 'warn local-config' in result.stdout
    assert section in result.stdout
    assert key not in result.stdout + result.stderr


def test_cli_doctor_returns_error_for_explicit_missing_dependency(sandbox, tmp_path):
    root = tmp_path / 'plugin-skills'
    root.mkdir()
    sandbox.write(
        'config/dependencies.toml',
        'schema_version=1\nrequired_skills=["superpowers:brainstorming"]\n',
    )
    sandbox.layout.state_dir.mkdir(parents=True)
    sandbox.layout.local_config.write_text(
        'schema_version=1\n[superpowers]\nskills_root=' + repr(str(root)) + '\n',
        encoding='utf-8',
    )
    result = invoke(sandbox, 'doctor')
    assert result.returncode == 2
    assert 'missing superpowers:brainstorming' in result.stdout


def test_doctor_record_failure_is_reported(sandbox, monkeypatch, capsys):
    from harness import __main__ as cli
    def denied(*args, **kwargs):
        raise PermissionError('SECRET_PERMISSION')
    monkeypatch.setattr(cli, 'atomic_write', denied)
    code = cli.main(['doctor', '--record', '--repo', str(sandbox.repo),
                     '--home', str(sandbox.layout.home), '--codex-home', str(sandbox.layout.codex_home)])
    output = capsys.readouterr()
    assert code == 2
    assert 'recorded' not in output.out
    assert 'SECRET_PERMISSION' not in output.out + output.err


@pytest.mark.parametrize('options', [('--unexpected-SECRET',), ('--adopt-from', '--bad-SECRET')])
def test_cli_invalid_arguments_are_sanitized(sandbox, options):
    result = invoke(sandbox, 'plan', *options)
    assert result.returncode == 2
    assert 'SECRET' not in result.stdout + result.stderr
    assert 'Traceback' not in result.stderr


def test_cli_missing_deployment_is_mismatch(sandbox):
    result = invoke(sandbox, 'verify', '--json')
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert any(p['code'] == 'not-recorded' for p in report['problems'])
    assert not sandbox.layout.home.exists()


def test_cli_explicit_local_config(sandbox):
    local = sandbox.repo.parent / 'local.toml'
    local.write_text('schema_version=1\n[client]\nkind="desktop"\nversion="1.2.3"\n', encoding='utf-8')
    result = invoke(sandbox, 'doctor', '--local-config', str(local))
    assert result.returncode == 0
    assert '1.2.3' not in result.stdout


def test_cli_doctor_unknown_key_record_is_sanitized(sandbox):
    key_sentinel = 'SECRET_UNKNOWN_KEY'
    value_sentinel = 'SECRET_LOCAL_VALUE'
    sandbox.layout.state_dir.mkdir(parents=True)
    sandbox.layout.local_config.write_text(
        'schema_version=1\n[client]\n'
        f'{key_sentinel}="{value_sentinel}"\n', encoding='utf-8')

    result = invoke(sandbox, 'doctor')

    assert result.returncode == 1
    assert not (sandbox.layout.state_dir / 'diagnostics.json').exists()
    assert key_sentinel not in result.stdout + result.stderr
    assert value_sentinel not in result.stdout + result.stderr

    recorded = invoke(sandbox, 'doctor', '--record')

    assert recorded.returncode == 1
    assert key_sentinel not in recorded.stdout + recorded.stderr
    assert value_sentinel not in recorded.stdout + recorded.stderr
    report = json.loads((sandbox.layout.state_dir / 'diagnostics.json').read_text(encoding='utf-8'))
    warning = next(check for check in report['checks'] if check['name'] == 'local-config')
    assert warning['status'] == 'warn'
    assert 'client' in warning['message']
    serialized = json.dumps(report)
    assert key_sentinel not in serialized
    assert value_sentinel not in serialized


def test_cli_invalid_role_stops_validate_plan_and_apply_before_writes(sandbox):
    sandbox.write(
        'agents/explorer.toml',
        'name="explorer"\n'
        'description="test"\n'
        'developer_instructions="test"\n'
        'modle="SECRET_ROLE_VALUE"\n',
    )
    sandbox.commit()
    for command in ('validate', 'plan', 'apply'):
        result = invoke(sandbox, command)
        assert result.returncode == 2
        assert 'modle' in result.stdout
        assert 'SECRET_ROLE_VALUE' not in result.stdout + result.stderr
    assert not sandbox.layout.home.exists()


def test_cli_index_flags_are_errors_with_preview(sandbox):
    from conftest import git

    secret_text = 'PRIVATE_SOURCE_BODY_DO_NOT_PRINT'
    sandbox.write('agents/explorer.toml',
                  'name="explorer"\ndescription="' + secret_text +
                  '"\ndeveloper_instructions="test"\n')
    sandbox.commit()
    git(sandbox.repo, 'update-index', '--skip-worktree', 'agents/explorer.toml')

    plan_result = invoke(sandbox, 'plan', '--json')
    apply_result = invoke(sandbox, 'apply')
    verify_result = invoke(sandbox, 'verify', '--json')
    plan_report = json.loads(plan_result.stdout)
    verify_report = json.loads(verify_result.stdout)

    for result in (plan_result, apply_result, verify_result):
        output = result.stdout + result.stderr
        assert secret_text not in output
        assert str(sandbox.repo) not in output
        assert 'Traceback' not in result.stderr
    assert (plan_result.returncode, apply_result.returncode, verify_result.returncode) == (2, 2, 2)
    assert any(problem['code'] == 'source-index-flags' for problem in plan_report['problems'])
    assert plan_report['operations']
    assert 'source-index-flags' in apply_result.stdout
    assert any(problem['code'] == 'source-index-flags' for problem in verify_report['problems'])
    assert not sandbox.layout.home.exists()
