import pytest

from harness import diagnostics
from harness.content import validate_sources


def test_missing_inventory_is_not_reported_as_runtime_problem(sandbox):
    checks = diagnostics.inspect_runtime(sandbox.layout)
    names = {item.name for item in checks}
    assert 'codex-cli' not in names
    assert 'superpowers-version' not in names
    assert 'client' not in names
    assert 'session-inventory' not in names
    assert not sandbox.layout.home.exists()


def test_unobserved_skill_source_is_skipped(sandbox):
    sandbox.write(
        'config/dependencies.toml',
        'schema_version=1\nrequired_skills=["superpowers:brainstorming","git-commit"]\n',
    )
    checks = diagnostics.inspect_runtime(sandbox.layout)
    names = {item.name for item in checks}
    assert 'superpowers:brainstorming' not in names
    assert 'git-commit' not in names


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


def test_legacy_inventory_values_are_accepted_but_ignored(sandbox):
    sandbox.layout.state_dir.mkdir(parents=True)
    sandbox.layout.local_config.write_text(
        'schema_version=1\n'
        '[superpowers]\n'
        'version="6.5.0"\n'
        '[client]\n'
        'kind="desktop"\n'
        'version="1.2.3"\n',
        encoding='utf-8',
    )
    checks = diagnostics.inspect_runtime(sandbox.layout)
    names = {item.name for item in checks}
    assert 'superpowers-version' not in names
    assert 'client' not in names


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
