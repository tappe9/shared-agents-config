import tomllib
import pytest

from harness.config_merge import merge_skill_overrides, read_overrides


def test_merge_preserves_unmanaged_config_and_is_idempotent(tmp_path):
    original = (b'# user comment\nmodel = "keep-model"\n'
                b'[mcp_servers.keep]\nurl = "https://example.invalid/mcp"\n'
                b'[[skills.config]]\npath = "unmanaged/SKILL.md"\nenabled = true\n')
    target = tmp_path / 'user-skills/brainstorming/SKILL.md'
    updated = merge_skill_overrides(original, {target: False})
    parsed = tomllib.loads(updated.decode())
    assert parsed['model'] == 'keep-model'
    assert parsed['mcp_servers'] == tomllib.loads(original.decode())['mcp_servers']
    assert b'# user comment' in updated
    unmanaged = next(x for x in parsed['skills']['config'] if x['path'] == 'unmanaged/SKILL.md')
    assert unmanaged['enabled'] is True
    assert merge_skill_overrides(updated, {target: False}) == updated
    assert read_overrides(updated, [target]) == {target: False}


def test_only_user_scope_is_updated(tmp_path):
    target = tmp_path / '.agents/skills/skill-creator/SKILL.md'
    plugin = tmp_path / '.codex/plugins/skill-creator/SKILL.md'
    system = tmp_path / '.codex/skills/.system/skill-creator/SKILL.md'
    original = merge_skill_overrides(b'', {plugin: True, system: True, target: True})
    updated = merge_skill_overrides(original, {target: False})
    assert read_overrides(updated, [plugin, system, target]) == {plugin: True, system: True, target: False}


def test_duplicate_simple_entries_are_consolidated(tmp_path):
    target = tmp_path / 'skill/SKILL.md'
    entry = merge_skill_overrides(b'', {target: False})
    updated = merge_skill_overrides(entry + entry, {target: False})
    assert len(tomllib.loads(updated.decode())['skills']['config']) == 1


def test_duplicate_with_unknown_keys_is_rejected(tmp_path):
    target = tmp_path / 'skill/SKILL.md'
    entry = merge_skill_overrides(b'', {target: False})
    with pytest.raises(ValueError):
        merge_skill_overrides(entry + b'metadata="retain"\n' + entry, {target: False})


def test_extra_key_is_preserved_for_single_entry(tmp_path):
    target = tmp_path / 'skill/SKILL.md'
    entry = merge_skill_overrides(b'', {target: True}) + b'metadata="retain"\n'
    assert b'metadata="retain"' in merge_skill_overrides(entry, {target: False})


@pytest.mark.parametrize('original', [b'skills=2\n', b'[skills]\nconfig="x"\n',
    b'[skills]\nconfig=[2]\n', b'PRIVATE= "unterminated', b'\xff\xfe'])
def test_invalid_document_is_sanitized(original, tmp_path):
    with pytest.raises(ValueError) as error:
        merge_skill_overrides(original, {tmp_path / 'SKILL.md': False})
    assert 'PRIVATE' not in str(error.value)


def test_bom_crlf_noop_and_trailing_comment(tmp_path):
    target = tmp_path / 'skill/SKILL.md'
    original = b'\xef\xbb\xbf' + merge_skill_overrides(b'', {target: False}).replace(b'\n', b'\r\n') + b'# keep\r\n'
    assert merge_skill_overrides(original, {target: False}) == original
    changed = merge_skill_overrides(original, {target: True})
    assert changed.startswith(b'\xef\xbb\xbf')
    assert b'# keep\r\n' in changed


def test_enabled_wrong_type_is_rejected(tmp_path):
    target = tmp_path / 'skill/SKILL.md'
    original = merge_skill_overrides(b'', {target: False}).replace(b'false', b'"false"')
    with pytest.raises(ValueError):
        merge_skill_overrides(original, {target: False})


def test_relative_entry_is_not_adopted(tmp_path):
    target = tmp_path / 'skill/SKILL.md'
    original = b'[[skills.config]]\npath="skill/SKILL.md"\nenabled=true\n'
    result = merge_skill_overrides(original, {target: False})
    assert b'path="skill/SKILL.md"\nenabled=true' in result


def test_no_targets_does_not_create_empty_tables():
    assert merge_skill_overrides(b'# only a comment\n', {}) == b'# only a comment\n'


@pytest.mark.parametrize('original', [
    b'[skills]\nconfig = []\n',
    b'skills = {config = []}\n',
    b'skills = {other = "keep"}\n',
    b'[skills]\nconfig = [{path = "/other/SKILL.md", enabled = true}]\n',
])
def test_inline_config_stays_valid_when_adding_override(tmp_path, original):
    target = tmp_path / 'skill/SKILL.md'
    updated = merge_skill_overrides(original, {target: False})
    parsed = tomllib.loads(updated.decode())
    assert any(e['path'] == str(target) and e['enabled'] is False for e in parsed['skills']['config'])
    assert merge_skill_overrides(updated, {target: False}) == updated
