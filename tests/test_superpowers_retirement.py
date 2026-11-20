import hashlib
import json

import pytest

from conftest import git
from harness import sync
from harness.diagnostics import inspect_runtime
from harness.sync import apply_plan, build_plan, verify_deployment


def legacy_hash(contents):
    normalized = contents.replace(b'\r\n', b'\n')
    return hashlib.sha256(normalized).hexdigest()


def set_legacy_superpowers_policy(sandbox, tracked_files):
    skill_names = sorted({path.split('/', 1)[0] for path in tracked_files})
    disabled = ', '.join(f'"{name}"' for name in skill_names)
    entries = '\n'.join(
        f'"{path}" = "{legacy_hash(contents)}"'
        for path, contents in tracked_files.items()
    )
    sandbox.write(
        'config/skills-policy.toml',
        'schema_version = 1\n\n'
        '[skills]\n'
        f'disabled_user_dirs = [{disabled}]\n\n'
        '[skills.superpowers_5_1_0_files]\n'
        f'{entries}\n',
    )
    sandbox.commit()


def put_skill_file(sandbox, relative_path, contents):
    target = sandbox.layout.skills_home / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(contents)
    return target


def test_matching_legacy_superpowers_file_is_planned_for_deletion(sandbox):
    legacy_content = b'# Systematic Debugging\n\nOfficial legacy file.\n'
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': legacy_content},
    )
    legacy_file = put_skill_file(
        sandbox, 'systematic-debugging/SKILL.md', legacy_content.replace(b'\n', b'\r\n'),
    )

    plan = build_plan(sandbox.layout)

    assert not plan.problems
    operation = next(
        op for op in plan.operations
        if op.target_id == 'skills:systematic-debugging/SKILL.md'
    )
    assert operation.action == 'delete'
    assert operation.desired_bytes is None
    assert legacy_file.exists()


def test_legacy_cleanup_preserves_modified_extra_and_other_version_files(sandbox):
    legacy_main = b'# Systematic Debugging\n'
    legacy_reference = b'# Local edits\n'
    legacy_writing = b'# Writing Skills\n'
    tracked_files = {
        'systematic-debugging/SKILL.md': legacy_main,
        'systematic-debugging/references/guide.md': legacy_reference,
        'writing-skills/SKILL.md': legacy_writing,
        'writing-skills/references/guide.md': legacy_reference,
    }
    set_legacy_superpowers_policy(sandbox, tracked_files)

    matching = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', legacy_main)
    modified = put_skill_file(
        sandbox, 'systematic-debugging/references/guide.md', b'# Local edits\r',
    )
    extra = put_skill_file(sandbox, 'systematic-debugging/private-notes.md', b'Keep me.\n')
    metadata = put_skill_file(
        sandbox, 'systematic-debugging/agents/openai.yaml', b'name: systematic-debugging\n',
    )
    other_version = put_skill_file(
        sandbox, 'writing-skills/SKILL.md', b'# Newer skill content\n',
    )
    other_version_reference = put_skill_file(
        sandbox, 'writing-skills/references/guide.md', legacy_reference,
    )
    plugin_copy = (
        sandbox.layout.codex_home / 'plugins/cache/openai-curated-remote/superpowers/7.0.1/'
        'skills/systematic-debugging/SKILL.md'
    )
    plugin_copy.parent.mkdir(parents=True)
    plugin_copy.write_bytes(legacy_main)

    plan = build_plan(sandbox.layout)

    deletions = {
        op.target_id for op in plan.operations if op.action == 'delete'
    }
    assert 'skills:systematic-debugging/SKILL.md' in deletions
    assert 'skills:systematic-debugging/references/guide.md' not in deletions
    assert 'skills:writing-skills/SKILL.md' not in deletions
    assert 'skills:writing-skills/references/guide.md' not in deletions
    assert 'skills:systematic-debugging/agents/openai.yaml' not in deletions

    result = apply_plan(sandbox.layout, plan)

    assert not result.problems
    assert not matching.exists()
    assert modified.read_bytes() == b'# Local edits\r'
    assert extra.read_bytes() == b'Keep me.\n'
    assert metadata.read_bytes() == b'name: systematic-debugging\n'
    assert other_version.read_bytes() == b'# Newer skill content\n'
    assert other_version_reference.read_bytes() == legacy_reference
    assert plugin_copy.read_bytes() == legacy_main
    assert verify_deployment(sandbox.layout) == []


def test_invalid_legacy_file_path_stops_plan(sandbox):
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': b'# Systematic Debugging\n'},
    )
    policy = sandbox.repo / 'config/skills-policy.toml'
    policy.write_text(
        policy.read_text().replace(
            'systematic-debugging/SKILL.md',
            'systematic-debugging/../outside/SKILL.md',
        ),
    )
    sandbox.commit()
    legacy_file = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', b'Keep me.\n')

    plan = build_plan(sandbox.layout)

    assert any(problem.code == 'invalid-source' for problem in plan.problems)
    assert plan.operations == []
    assert legacy_file.read_bytes() == b'Keep me.\n'


def test_symlinked_legacy_skill_path_stops_plan(sandbox, tmp_path):
    legacy_content = b'# Systematic Debugging\n'
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': legacy_content},
    )
    outside = tmp_path / 'outside'
    outside.mkdir()
    protected = outside / 'SKILL.md'
    protected.write_bytes(legacy_content)
    sandbox.layout.skills_home.mkdir(parents=True)
    try:
        (sandbox.layout.skills_home / 'systematic-debugging').symlink_to(
            outside, target_is_directory=True,
        )
    except OSError:
        pytest.skip('Symlink creation is not permitted')

    plan = build_plan(sandbox.layout)

    assert any(problem.code == 'invalid-input' for problem in plan.problems)
    assert not any(op.action == 'delete' for op in plan.operations)
    before = {path: path.read_bytes() for path in sandbox.layout.home.rglob('*') if path.is_file()}
    result = apply_plan(sandbox.layout, plan)
    assert result.problems
    assert result.changed_ids == []
    assert {path: path.read_bytes() for path in sandbox.layout.home.rglob('*') if path.is_file()} == before
    assert protected.read_bytes() == legacy_content


def test_change_after_plan_prevents_legacy_deletion(sandbox):
    legacy_content = b'# Systematic Debugging\n'
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': legacy_content},
    )
    legacy_file = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', legacy_content)
    plan = build_plan(sandbox.layout)
    legacy_file.write_bytes(b'# Local update\n')
    before = {path: path.read_bytes() for path in sandbox.layout.home.rglob('*') if path.is_file()}

    result = apply_plan(sandbox.layout, plan)

    assert any(problem.code == 'stale-plan' for problem in result.problems)
    assert result.changed_ids == []
    assert {path: path.read_bytes() for path in sandbox.layout.home.rglob('*') if path.is_file()} == before
    assert legacy_file.read_bytes() == b'# Local update\n'
    assert not (sandbox.layout.state_dir / 'state.json').exists()


def test_legacy_cleanup_can_be_applied_retried_and_verified(sandbox):
    legacy_content = b'# Systematic Debugging\n'
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': legacy_content},
    )
    legacy_file = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', legacy_content)

    first = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert not first.problems
    assert 'skills:systematic-debugging/SKILL.md' in first.changed_ids
    assert 'codex:config.toml' in first.changed_ids
    assert not legacy_file.exists()
    assert verify_deployment(sandbox.layout) == []

    before = {path: path.read_bytes() for path in sandbox.layout.home.rglob('*') if path.is_file()}
    second = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert not second.problems
    assert second.changed_ids == []
    assert {path: path.read_bytes() for path in sandbox.layout.home.rglob('*') if path.is_file()} == before
    assert verify_deployment(sandbox.layout) == []


def test_deleted_legacy_skill_overrides_do_not_warn_after_apply(sandbox):
    legacy_content = b'# Systematic Debugging\n'
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': legacy_content},
    )
    legacy_file = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', legacy_content)

    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert not result.problems
    assert not legacy_file.exists()
    assert verify_deployment(sandbox.layout) == []
    assert not any(
        check.name == 'skill-overrides' and check.status == 'warn'
        for check in inspect_runtime(sandbox.layout)
    )


def test_unrelated_missing_skill_override_still_warns(sandbox):
    legacy_content = b'# Systematic Debugging\n'
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': legacy_content},
    )
    legacy_file = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', legacy_content)
    missing_skill = sandbox.layout.skills_home / 'local-custom/SKILL.md'
    config = sandbox.layout.codex_home / 'config.toml'
    config.parent.mkdir(parents=True)
    config.write_text(
        '[[skills.config]]\n'
        f'path = "{missing_skill.as_posix()}"\n'
        'enabled = false\n',
    )

    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert not result.problems
    assert not legacy_file.exists()
    assert verify_deployment(sandbox.layout) == []
    assert any(
        check.name == 'skill-overrides' and check.status == 'warn'
        for check in inspect_runtime(sandbox.layout)
    )


def test_partial_legacy_cleanup_can_be_retried(sandbox, monkeypatch):
    legacy_main = b'# Systematic Debugging\n'
    legacy_alpha = b'# Alpha reference\n'
    legacy_zeta = b'# Zeta reference\n'
    set_legacy_superpowers_policy(
        sandbox,
        {
            'systematic-debugging/SKILL.md': legacy_main,
            'systematic-debugging/references/alpha.md': legacy_alpha,
            'systematic-debugging/references/zeta.md': legacy_zeta,
        },
    )
    root = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', legacy_main)
    alpha = put_skill_file(sandbox, 'systematic-debugging/references/alpha.md', legacy_alpha)
    zeta = put_skill_file(sandbox, 'systematic-debugging/references/zeta.md', legacy_zeta)
    original_rename = sync.os.rename

    def fail_on_zeta(source, destination, *args, **kwargs):
        if source == zeta:
            raise PermissionError('simulated deletion failure')
        original_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(sync.os, 'rename', fail_on_zeta)
    first = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert first.problems
    assert not alpha.exists()
    assert zeta.read_bytes() == legacy_zeta
    assert root.read_bytes() == legacy_main
    assert not (sandbox.layout.state_dir / 'state.json').exists()

    monkeypatch.setattr(sync.os, 'rename', original_rename)
    second = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert not second.problems
    assert not alpha.exists()
    assert not zeta.exists()
    assert not root.exists()
    assert verify_deployment(sandbox.layout) == []


def test_changed_legacy_file_is_restored_when_delete_detects_race(sandbox, monkeypatch):
    legacy_content = b'# Systematic Debugging\n'
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': legacy_content},
    )
    legacy_file = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', legacy_content)
    custom_content = b'# User change during cleanup\n'
    original_rename = sync.os.rename

    def change_before_rename(source, destination, *args, **kwargs):
        if source == legacy_file:
            source.write_bytes(custom_content)
        original_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(sync.os, 'rename', change_before_rename)
    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert result.problems
    assert legacy_file.read_bytes() == custom_content
    assert not list(legacy_file.parent.glob('.harness-retained-*'))
    assert not (sandbox.layout.state_dir / 'state.json').exists()


def test_new_same_name_file_and_legacy_payload_are_retained(sandbox, monkeypatch):
    legacy_content = b'# Systematic Debugging\n'
    new_content = b'# Recreated by another process\n'
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': legacy_content},
    )
    legacy_file = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', legacy_content)
    original_rename = sync.os.rename

    def recreate_original_after_move(source, destination, *args, **kwargs):
        original_rename(source, destination, *args, **kwargs)
        if source == legacy_file:
            legacy_file.write_bytes(new_content)

    monkeypatch.setattr(sync.os, 'rename', recreate_original_after_move)
    result = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    retained_payloads = list(legacy_file.parent.glob('.harness-retained-*/payload'))
    assert any(problem.code == 'retained-file' for problem in result.problems)
    assert legacy_file.read_bytes() == new_content
    assert len(retained_payloads) == 1
    assert retained_payloads[0].read_bytes() == legacy_content
    assert any(problem.code == 'retained-file' for problem in build_plan(sandbox.layout).problems)


def test_state_write_failure_after_cleanup_preserves_override_on_retry(sandbox, monkeypatch):
    legacy_content = b'# Systematic Debugging\n'
    set_legacy_superpowers_policy(
        sandbox,
        {'systematic-debugging/SKILL.md': legacy_content},
    )
    legacy_file = put_skill_file(sandbox, 'systematic-debugging/SKILL.md', legacy_content)
    original_atomic_write = sync.atomic_write

    def fail_on_state(root, target, contents, expected):
        if target.name == 'state.json':
            raise PermissionError('simulated state write failure')
        original_atomic_write(root, target, contents, expected)

    monkeypatch.setattr(sync, 'atomic_write', fail_on_state)
    failed = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert failed.problems
    assert not legacy_file.exists()
    assert not (sandbox.layout.state_dir / 'state.json').exists()

    monkeypatch.setattr(sync, 'atomic_write', original_atomic_write)
    retried = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert not retried.problems
    assert verify_deployment(sandbox.layout) == []
    managed_overrides = json.loads(
        (sandbox.layout.state_dir / 'state.json').read_bytes(),
    )['managed_skill_overrides']
    assert managed_overrides['skills:systematic-debugging/SKILL.md'] is False

    before = {path: path.read_bytes() for path in sandbox.layout.home.rglob('*') if path.is_file()}
    second = apply_plan(sandbox.layout, build_plan(sandbox.layout))

    assert not second.problems
    assert second.changed_ids == []
    assert {path: path.read_bytes() for path in sandbox.layout.home.rglob('*') if path.is_file()} == before
    assert verify_deployment(sandbox.layout) == []
