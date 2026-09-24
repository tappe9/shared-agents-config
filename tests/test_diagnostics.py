import subprocess

import pytest

from harness import diagnostics
from harness.content import validate_sources


@pytest.fixture(autouse=True)
def no_installed_cli(monkeypatch):
    monkeypatch.setattr(diagnostics.shutil, 'which', lambda name: None)


def test_missing_cli_is_unknown_not_verified(sandbox):
    checks = diagnostics.inspect_runtime(sandbox.layout)
    cli = next(item for item in checks if item.name == 'codex-cli')
    assert cli.status == 'unknown'
    assert cli.evidence_kind == 'not_checked'
    assert not sandbox.layout.home.exists()


def test_version_is_observed_but_session_is_not(sandbox, monkeypatch):
    monkeypatch.setattr(diagnostics.shutil, 'which', lambda name: '/fake/codex')
    monkeypatch.setattr(diagnostics.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, b'codex-cli 0.155.0-alpha.16\n', b''))
    checks = diagnostics.inspect_runtime(sandbox.layout)
    assert next(d for d in checks if d.name == 'codex-cli').status == 'ok'
    assert next(d for d in checks if d.name == 'session-inventory').status == 'unknown'


@pytest.mark.parametrize('output', [b'0.155.0\nPRIVATE', b'PRIVATE value', b'\xff'])
def test_unexpected_cli_output_is_not_disclosed(sandbox, monkeypatch, output):
    monkeypatch.setattr(diagnostics.shutil, 'which', lambda name: '/fake/codex')
    monkeypatch.setattr(diagnostics.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, output, b'SECRET'))
    checks = diagnostics.inspect_runtime(sandbox.layout)
    assert next(d for d in checks if d.name == 'codex-cli').status == 'warn'
    assert 'PRIVATE' not in repr(checks) and 'SECRET' not in repr(checks)


def test_timeout_is_not_success(sandbox, monkeypatch):
    monkeypatch.setattr(diagnostics.shutil, 'which', lambda name: '/fake/codex')
    def timeout(*a, **k):
        raise subprocess.TimeoutExpired('PRIVATE', 5)
    monkeypatch.setattr(diagnostics.subprocess, 'run', timeout)
    checks = diagnostics.inspect_runtime(sandbox.layout)
    assert next(d for d in checks if d.name == 'codex-cli').status == 'warn'
    assert 'PRIVATE' not in repr(checks)


@pytest.mark.parametrize('content,expected', [(b'', 'ok'), (b' \n', 'ok'), (b'override', 'warn')])
def test_override_is_checked_without_editing(sandbox, content, expected):
    sandbox.layout.codex_home.mkdir(parents=True)
    path = sandbox.layout.codex_home / 'AGENTS.override.md'
    path.write_bytes(content)
    checks = diagnostics.inspect_runtime(sandbox.layout)
    assert next(d for d in checks if d.name == 'global-override').status == expected
    assert path.read_bytes() == content


def test_explicit_missing_skill_is_reported(sandbox, tmp_path):
    import tomlkit
    root = tmp_path / 'plugin-skills'
    root.mkdir()
    sandbox.write('config/dependencies.toml', 'schema_version=1\nrequired_skills=["superpowers:brainstorming"]\n')
    sandbox.layout.state_dir.mkdir(parents=True)
    config = tomlkit.dumps({'schema_version': 1, 'superpowers': {'skills_root': str(root)}})
    sandbox.layout.local_config.write_text(config, encoding='utf-8')
    checks = diagnostics.inspect_runtime(sandbox.layout)
    assert next(d for d in checks if d.name == 'superpowers:brainstorming').status == 'missing'


def test_provider_metadata_is_rejected_by_dependency_manifest(sandbox):
    sandbox.write(
        'config/dependencies.toml',
        'schema_version=1\nrequired_skills=[]\n'
        '[providers.superpowers]\nlast_documented_version="6.4.1"\n',
    )
    check = next(
        d for d in diagnostics.inspect_runtime(sandbox.layout)
        if d.name == 'dependencies'
    )
    assert check.status == 'missing'


def test_malformed_local_config_is_sanitized(sandbox):
    sandbox.layout.state_dir.mkdir(parents=True)
    sandbox.layout.local_config.write_text('SECRET = "unterminated')
    checks = diagnostics.inspect_runtime(sandbox.layout)
    assert any(d.name == 'local-config' and d.status == 'warn' for d in checks)
    assert 'SECRET' not in repr(checks)


def test_external_references_must_be_in_manifest(sandbox):
    sandbox.write('skills/sample/SKILL.md', '---\nname: sample\ndescription: test\n---\nUse `superpowers:brainstorming`.\n')
    assert any(p.code == 'missing-dependency' for p in validate_sources(sandbox.repo))


def test_relative_config_target_is_flagged(sandbox):
    sandbox.layout.codex_home.mkdir(parents=True)
    (sandbox.layout.codex_home / 'config.toml').write_text('[[skills.config]]\npath="relative/SKILL.md"\nenabled=false\n')
    checks = diagnostics.inspect_runtime(sandbox.layout)
    assert any(d.name == 'skill-overrides' and d.status == 'warn' for d in checks)
