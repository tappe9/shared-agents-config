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
        'version={unexpected="opaque", count=7}\n'
        '[client]\n'
        'kind=42\n'
        'version=["not", "a", "version"]\n',
        encoding='utf-8',
    )
    checks = diagnostics.inspect_runtime(sandbox.layout)
    names = {item.name for item in checks}
    assert 'superpowers-version' not in names
    assert 'client' not in names
    assert not any(item.name == 'local-config' and item.status == 'warn' for item in checks)


@pytest.mark.parametrize(('section', 'key'), [
    ('superpowers', 'skills_rooot'),
    ('git_commit', 'skill_flie'),
    ('client', 'vresion'),
])
def test_unknown_local_section_keys_are_warned(sandbox, section, key):
    sandbox.layout.state_dir.mkdir(parents=True)
    sandbox.layout.local_config.write_text(
        f'schema_version=1\n[{section}]\n{key}="ignored typo"\n', encoding='utf-8')

    checks = diagnostics.inspect_runtime(sandbox.layout)

    warning = next(item for item in checks if item.name == 'local-config')
    assert warning.status == 'warn'
    assert warning.evidence_kind == 'not_checked'
    assert section in warning.message


def test_unknown_local_subtable_is_warned(sandbox):
    sandbox.layout.state_dir.mkdir(parents=True)
    sandbox.layout.local_config.write_text(
        'schema_version=1\n[superpowers.extra]\nvalue="ignored"\n', encoding='utf-8')

    checks = diagnostics.inspect_runtime(sandbox.layout)

    warning = next(item for item in checks if item.name == 'local-config')
    assert warning.status == 'warn'
    assert warning.evidence_kind == 'not_checked'
    assert 'superpowers' in warning.message


def test_mixed_known_and_unknown_local_keys_are_rejected(sandbox, tmp_path):
    import tomlkit

    source = tmp_path / 'plugin-skills'
    source.mkdir()
    sandbox.layout.state_dir.mkdir(parents=True)
    sandbox.layout.local_config.write_text(tomlkit.dumps({
        'schema_version': 1,
        'superpowers': {'skills_root': str(source), 'skills_rooot': 'typo'},
    }), encoding='utf-8')

    with pytest.raises(ValueError):
        diagnostics._local(sandbox.layout)


@pytest.mark.parametrize(('section', 'required_skill'), [
    ('superpowers', 'superpowers:brainstorming'),
    ('git_commit', 'git-commit'),
])
def test_valid_local_skill_paths_are_checked(sandbox, tmp_path, section, required_skill):
    import tomlkit

    source = tmp_path / 'plugin-skills'
    source.mkdir()
    if section == 'superpowers':
        target = source / 'brainstorming' / 'SKILL.md'
        settings = {'skills_root': str(source)}
    else:
        target = source / 'SKILL.md'
        settings = {'skill_file': str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('---\nname: test\ndescription: fixture\n---\n', encoding='utf-8')
    sandbox.write(
        'config/dependencies.toml',
        f'schema_version=1\nrequired_skills=["{required_skill}"]\n',
    )
    sandbox.layout.state_dir.mkdir(parents=True)
    sandbox.layout.local_config.write_text(
        tomlkit.dumps({'schema_version': 1, section: settings}), encoding='utf-8')

    checks = diagnostics.inspect_runtime(sandbox.layout)

    dependency = next(item for item in checks if item.name == required_skill)
    assert dependency.status == 'ok'
    assert not any(item.name == 'local-config' and item.status == 'warn' for item in checks)


def test_unknown_local_key_is_sanitized_without_mutation(sandbox):
    sandbox.layout.state_dir.mkdir(parents=True)
    original = (
        b'schema_version=1\n[superpowers]\n'
        b'SECRET_UNKNOWN_KEY="SECRET_LOCAL_VALUE"\n'
    )
    sandbox.layout.local_config.write_bytes(original)

    checks = diagnostics.inspect_runtime(sandbox.layout)
    rendered = repr(checks)

    warning = next(item for item in checks if item.name == 'local-config')
    assert warning.status == 'warn'
    assert 'superpowers' in warning.message
    assert 'SECRET_UNKNOWN_KEY' not in rendered
    assert 'SECRET_LOCAL_VALUE' not in rendered
    assert sandbox.layout.local_config.read_bytes() == original


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
