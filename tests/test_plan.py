import json
import pytest

from conftest import git
from harness.sync import build_plan


def test_plan_does_not_create_destination(sandbox):
    plan = build_plan(sandbox.layout)
    assert not plan.problems
    assert any(op.action == 'create' for op in plan.operations)
    assert not sandbox.layout.home.exists()


def test_missing_disable_candidate_does_not_create_config(sandbox):
    plan = build_plan(sandbox.layout)
    assert not any(op.target_id == 'codex:config.toml' for op in plan.operations)
    assert any(p.code == 'absent-disable-candidate' for p in plan.notes)


def test_existing_disable_candidate_gets_targeted(sandbox):
    candidate = sandbox.layout.skills_home / 'brainstorming/SKILL.md'
    candidate.parent.mkdir(parents=True)
    candidate.write_text('skill')
    plan = build_plan(sandbox.layout)
    assert not plan.problems
    config = next(op for op in plan.operations if op.target_id == 'codex:config.toml')
    assert b'enabled = false' in config.desired_bytes
    assert not sandbox.layout.codex_home.exists()


def test_unknown_existing_role_is_a_conflict(sandbox):
    dest = sandbox.layout.codex_home / 'agents/explorer.toml'
    dest.parent.mkdir(parents=True)
    dest.write_text('private local changes')
    plan = build_plan(sandbox.layout)
    assert any(op.action == 'conflict' for op in plan.operations)
    assert any(p.code == 'conflict' for p in plan.problems)
    assert 'private local changes' not in repr(plan)


def test_known_legacy_prefix_adoption(sandbox):
    old = git(sandbox.repo, 'rev-parse', 'HEAD')
    dest = sandbox.layout.codex_home / 'AGENTS.md'
    dest.parent.mkdir(parents=True)
    suffix = b'\r\n## Local\r\nkeep\r\n'
    dest.write_bytes((sandbox.repo / 'AGENTS.md').read_bytes() + suffix)
    sandbox.write('AGENTS.md', '# New\nAllowed `agent_type`: `explorer`\n')
    sandbox.commit()
    plan = build_plan(sandbox.layout, adopt_from=old)
    assert not plan.problems
    op = next(op for op in plan.operations if op.target_id == 'codex:AGENTS.md')
    assert op.action == 'adopt'
    assert op.desired_bytes.endswith(suffix)


def test_legacy_unknown_prefix_is_not_overwritten(sandbox):
    dest = sandbox.layout.codex_home / 'AGENTS.md'
    dest.parent.mkdir(parents=True)
    dest.write_text('private instructions')
    plan = build_plan(sandbox.layout, adopt_from='HEAD')
    assert plan.problems
    assert dest.read_text() == 'private instructions'


def test_dirty_source_is_visible_in_plan(sandbox):
    sandbox.write('untracked.txt', 'new')
    assert build_plan(sandbox.layout).source_dirty


def test_old_role_removed_from_source_is_reported(sandbox):
    old = git(sandbox.repo, 'rev-parse', 'HEAD')
    target = sandbox.layout.codex_home / 'agents/explorer.toml'
    target.parent.mkdir(parents=True)
    target.write_bytes((sandbox.repo / 'agents/explorer.toml').read_bytes())
    (sandbox.repo / 'agents/explorer.toml').rename(sandbox.repo / 'agents/reader.toml')
    sandbox.write('agents/reader.toml', 'name="reader"\ndescription="read"\ndeveloper_instructions="read"\n')
    sandbox.write('AGENTS.md', 'Allowed `agent_type`: `reader`\n')
    sandbox.commit()
    plan = build_plan(sandbox.layout, adopt_from=old)
    assert not plan.problems
    assert any(op.action == 'retired' and op.target == target for op in plan.operations)
    assert target.exists()


@pytest.mark.parametrize('raw', ['not json PRIVATE', '{}', '{"schema_version":2}',
                                 '{"schema_version":true}'])
def test_invalid_state_is_not_ignored(sandbox, raw):
    sandbox.layout.state_dir.mkdir(parents=True)
    (sandbox.layout.state_dir / 'state.json').write_text(raw)
    plan = build_plan(sandbox.layout)
    assert any(p.code == 'invalid-state' for p in plan.problems)
    assert 'PRIVATE' not in repr(plan)


def test_linked_parent_of_skills_root_is_rejected(sandbox, tmp_path):
    sandbox.layout.home.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (sandbox.layout.home / '.agents').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink creation is not permitted')
    assert build_plan(sandbox.layout).problems
    assert list(outside.iterdir()) == []


def test_source_inside_deployment_root_is_rejected(sandbox):
    from harness.paths import resolve_layout
    layout = resolve_layout(sandbox.repo, home=sandbox.layout.home,
                            codex_home=sandbox.repo / 'managed', env={})
    assert build_plan(layout).problems


def test_invalid_role_stops_plan_before_operations(sandbox):
    sandbox.write(
        'agents/explorer.toml',
        'name="explorer"\n'
        'description="test"\n'
        'developer_instructions="test"\n'
        'sandbox_mode="definitely-invalid"\n',
    )
    sandbox.commit()
    plan = build_plan(sandbox.layout)
    assert any(p.code == 'invalid-role' for p in plan.problems)
    assert plan.operations == []
    assert not sandbox.layout.home.exists()
