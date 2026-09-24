from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .config_merge import merge_skill_overrides, read_overrides
from .content import (canonical_text, commit_sha, extract_local_suffix, git_bytes,
                      managed_common, read_policy, render_agents, source_files, validate_sources)
from .paths import Layout, Problem, assert_safe_target, validate_relative_name


@dataclass(frozen=True)
class Operation:
    target_id: str
    action: str
    target: Path = field(repr=False)
    expected_before: bytes | None = field(repr=False)
    desired_bytes: bytes | None = field(repr=False)
    managed_hash: str | None = None


@dataclass
class SyncPlan:
    source_commit: str = ''
    source_dirty: bool = False
    operations: list[Operation] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    notes: list[Problem] = field(default_factory=list)
    state: dict = field(default_factory=dict, repr=False)
    state_before: bytes | None = field(default=None, repr=False)
    adopt_from: str | None = None
    retired: dict[str, str] = field(default_factory=dict)
    overrides: dict[str, bool] = field(default_factory=dict)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def roots_fingerprint(layout: Layout) -> str:
    roots = [os.path.normcase(str(p.resolve())) for p in (layout.codex_home, layout.skills_home)]
    return digest(json.dumps(roots).encode())


def _check_layout(layout: Layout) -> None:
    for root in (layout.codex_home, layout.skills_home):
        assert_safe_target(root, root)
        if root.is_relative_to(layout.home):
            assert_safe_target(layout.home, root)
        if root.resolve().is_relative_to(layout.repo.resolve()) or layout.repo.resolve().is_relative_to(root.resolve()):
            raise ValueError('overlapping-source-destination')
    if (layout.codex_home.resolve().is_relative_to(layout.skills_home.resolve()) or
            layout.skills_home.resolve().is_relative_to(layout.codex_home.resolve())):
        raise ValueError('overlapping-destinations')


def file_target(layout: Layout, target_id: str) -> tuple[Path, Path]:
    group, separator, name = target_id.partition(':')
    parts = name.split('/')
    if not separator:
        raise ValueError('invalid-target-id')
    for part in parts:
        validate_relative_name(part)
    if group == 'codex' and (name == 'AGENTS.md' or
                            (len(parts) == 2 and parts[0] == 'agents' and name.endswith('.toml'))):
        return layout.codex_home, layout.codex_home.joinpath(*parts)
    if group == 'skills' and len(parts) >= 2:
        if any(p.lower() in {'.env', 'auth.json', 'local.toml', 'state.json', 'diagnostics.json'}
               or p.lower().startswith('.env.') for p in parts):
            raise ValueError('sensitive-target-id')
        return layout.skills_home, layout.skills_home.joinpath(*parts)
    raise ValueError('invalid-target-id')


def _read(root: Path, path: Path) -> bytes | None:
    assert_safe_target(root, path)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def load_state(layout: Layout) -> tuple[dict, bytes | None]:
    raw = _read(layout.codex_home, layout.state_dir / 'state.json')
    if raw is None:
        return {}, None
    try:
        data = json.loads(raw)
        if (type(data['schema_version']) is not int or data['schema_version'] != 1 or
                data['roots_fingerprint'] != roots_fingerprint(layout) or
                not re.fullmatch('[0-9a-f]{40}', data['source_commit'])):
            raise ValueError
        for key in ('managed_files', 'retired_files', 'managed_skill_overrides'):
            if not isinstance(data[key], dict):
                raise ValueError
            for target_id, value in data[key].items():
                file_target(layout, target_id)
                if key == 'managed_skill_overrides':
                    if (not target_id.startswith('skills:') or
                            not target_id.endswith('/SKILL.md') or type(value) is not bool):
                        raise ValueError
                elif not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
                    raise ValueError
        return data, raw
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('invalid-state') from None


def _source_id(name: str) -> str:
    return 'skills:' + name[len('skills/'):] if name.startswith('skills/') else 'codex:' + name


def _add_file(plan: SyncPlan, layout: Layout, name: str, desired: bytes,
              legacy: dict[str, bytes]) -> None:
    target_id = _source_id(name)
    root, target = file_target(layout, target_id)
    before = _read(root, target)
    common = canonical_text(desired)
    if name == 'AGENTS.md' and not common.endswith(b'\n'):
        common += b'\n'
    desired_hash = digest(common if name == 'AGENTS.md' else desired)
    previous = plan.state.get('managed_files', {}).get(target_id)
    if before is None:
        action = 'create'
        if name == 'AGENTS.md':
            desired = render_agents(common, b'')
    elif name == 'AGENTS.md':
        try:
            current_common = managed_common(before)
            suffix = extract_local_suffix(before)
            current_hash = digest(current_common)
            if current_hash == desired_hash:
                action = 'unchanged' if previous == desired_hash else 'adopt'
                desired = before
            elif current_hash == previous:
                action = 'update'
                desired = render_agents(common, suffix)
            elif name in legacy and current_common == canonical_text(legacy[name]):
                action = 'adopt'
                desired = render_agents(common, suffix)
            else:
                action = 'conflict'
        except ValueError:
            try:
                known = legacy.get(name)
                if known is None and canonical_text(before) == common:
                    known = common
                suffix = extract_local_suffix(before, legacy_common=known)
                action, desired = 'adopt', render_agents(common, suffix)
            except ValueError:
                action = 'conflict'
    elif before == desired:
        action = 'unchanged' if previous == desired_hash else 'adopt'
    elif digest(before) == previous:
        action = 'update'
    elif legacy.get(name) == before:
        action = 'adopt'
    elif (name.startswith('agents/') and name in legacy and
          before.replace(b'\r\n', b'\n') == legacy[name].replace(b'\r\n', b'\n')):
        action = 'adopt'
    else:
        action = 'conflict'
    if action == 'conflict':
        plan.problems.append(Problem('conflict', target_id, 'Local changes require reconciliation.'))
    plan.operations.append(Operation(target_id, action, target, before, desired, desired_hash))


def _add_config(plan: SyncPlan, layout: Layout) -> None:
    target = layout.codex_home / 'config.toml'
    original = _read(layout.codex_home, target)
    desired: dict[Path, bool] = {}
    for name in read_policy(layout.repo):
        candidate = layout.skills_home / name / 'SKILL.md'
        assert_safe_target(layout.skills_home, candidate)
        if candidate.is_file():
            desired[candidate] = False
        else:
            plan.notes.append(Problem('absent-disable-candidate', f'skills:{name}/SKILL.md',
                                      'No override is generated for an absent skill.'))
    previous = plan.state.get('managed_skill_overrides', {})
    previous_paths = {key: file_target(layout, key)[1] for key in previous}
    current = read_overrides(original or b'', list(previous_paths.values()))
    for key, path in previous_paths.items():
        if path in desired and current.get(path) != previous[key]:
            plan.problems.append(Problem('conflict', key, 'The managed enabled value changed locally.'))
        if path not in desired and path in current:
            plan.overrides[key] = current[path]
            plan.notes.append(Problem('orphaned-override', key, 'Previously managed override remains untouched.'))
    for path, value in desired.items():
        plan.overrides['skills:' + path.relative_to(layout.skills_home).as_posix()] = value
    updated = merge_skill_overrides(original or b'', desired)
    if original is None and not updated:
        return
    action = 'create' if original is None else 'update' if updated != original else 'unchanged'
    plan.operations.append(Operation('codex:config.toml', action, target, original, updated))


def build_plan(layout: Layout, *, adopt_from: str | None = None) -> SyncPlan:
    plan = SyncPlan()
    try:
        _check_layout(layout)
        plan.source_commit = commit_sha(layout.repo)
        plan.source_dirty = bool(git_bytes(layout.repo, 'status', '--porcelain', '-z', '--untracked-files=all'))
        plan.problems.extend(validate_sources(layout.repo))
        if plan.problems:
            return plan
        try:
            plan.state, plan.state_before = load_state(layout)
        except ValueError:
            plan.problems.append(Problem('invalid-state', 'state', 'State is invalid or belongs to different roots.'))
            return plan
        plan.adopt_from = commit_sha(layout.repo, adopt_from) if adopt_from else None
        legacy = source_files(layout.repo, ref=plan.adopt_from) if plan.adopt_from else {}
        files = source_files(layout.repo)
        for name, data in sorted(files.items()):
            _add_file(plan, layout, name, data, legacy)
        _add_config(plan, layout)
        current_ids = {_source_id(name) for name in files}
        old = dict(plan.state.get('retired_files', {}))
        old.update(plan.state.get('managed_files', {}))
        for name, data in legacy.items():
            key = _source_id(name)
            if key not in current_ids and key not in old:
                root, target = file_target(layout, key)
                if _read(root, target) == data:
                    old[key] = digest(data)
        for key, last_hash in sorted(old.items()):
            if key in current_ids:
                continue
            root, target = file_target(layout, key)
            before = _read(root, target)
            if before is not None:
                plan.retired[key] = last_hash
                plan.operations.append(Operation(key, 'retired', target, before, None, last_hash))
    except (OSError, ValueError):
        plan.problems.append(Problem('invalid-input', 'deployment', 'Paths, source or configuration cannot be safely read.'))
    return plan


@dataclass
class ApplyResult:
    changed_ids: list[str] = field(default_factory=list)
    adopted_ids: list[str] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    notes: list[Problem] = field(default_factory=list)


def atomic_write(root: Path, target: Path, data: bytes, expected: bytes | None) -> None:
    import stat
    import tempfile

    assert_safe_target(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _read(root, target) != expected:
        raise ValueError('concurrent-change')
    mode = stat.S_IMODE(target.stat().st_mode) if expected is not None else 0o600
    fd, temporary = tempfile.mkstemp(prefix='.harness-', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != 'nt':
            os.chmod(temporary, mode)
        if _read(root, target) != expected:
            raise ValueError('concurrent-change')
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _verify_operations(layout: Layout, plan: SyncPlan) -> list[Problem]:
    problems = []
    _check_layout(layout)
    for op in plan.operations:
        if op.action == 'retired':
            continue
        root = layout.skills_home if op.target_id.startswith('skills:') else layout.codex_home
        if _read(root, op.target) != op.desired_bytes:
            problems.append(Problem('mismatch', op.target_id, 'Written content did not match the plan.'))
    return problems


def apply_plan(layout: Layout, plan: SyncPlan) -> ApplyResult:
    from datetime import datetime, timezone

    result = ApplyResult(problems=list(plan.problems), notes=list(plan.notes))
    if plan.source_dirty:
        result.problems.append(Problem('dirty-source', 'source', 'Commit or reconcile source changes before apply.'))
    if result.problems:
        return result
    lock = layout.state_dir / 'apply.lock'
    locked = False
    current_id = 'state'
    try:
        _check_layout(layout)
        assert_safe_target(layout.codex_home, lock)
        layout.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            result.problems.append(Problem('locked', 'state', 'Another apply lock exists; no files were applied.'))
            return result
        os.close(fd)
        locked = True
        fresh = build_plan(layout, adopt_from=plan.adopt_from)
        if fresh != plan:
            result.problems.append(Problem('stale-plan', 'deployment', 'Inputs changed; create a new plan.'))
            return result
        for op in fresh.operations:
            current_id = op.target_id
            if op.action == 'retired':
                result.notes.append(Problem('retired', op.target_id, 'Old managed file remains; not deleted.'))
                continue
            if op.action == 'adopt':
                result.adopted_ids.append(op.target_id)
            if op.desired_bytes != op.expected_before:
                _check_layout(layout)
                root = layout.skills_home if op.target_id.startswith('skills:') else layout.codex_home
                atomic_write(root, op.target, op.desired_bytes, op.expected_before)
                result.changed_ids.append(op.target_id)
        current_id = 'deployment'
        result.problems.extend(_verify_operations(layout, fresh))
        if (commit_sha(layout.repo) != fresh.source_commit or
                git_bytes(layout.repo, 'status', '--porcelain', '-z', '--untracked-files=all')):
            result.problems.append(Problem('source-changed', 'source', 'Source changed while applying.'))
        if result.problems:
            return result
        payload = {
            'schema_version': 1, 'source_commit': fresh.source_commit,
            'roots_fingerprint': roots_fingerprint(layout),
            'managed_files': {op.target_id: op.managed_hash for op in fresh.operations
                              if op.action != 'retired' and op.managed_hash is not None},
            'managed_skill_overrides': fresh.overrides,
            'retired_files': fresh.retired,
            'validation': {'sources': 'passed', 'deployment': 'passed'},
        }
        old_payload = {k: v for k, v in fresh.state.items() if k != 'applied_at'}
        if payload != old_payload:
            current_id = 'state'
            payload['applied_at'] = datetime.now(timezone.utc).isoformat()
            raw = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + '\n').encode()
            _check_layout(layout)
            atomic_write(layout.codex_home, layout.state_dir / 'state.json', raw, fresh.state_before)
    except (OSError, ValueError):
        result.problems.append(Problem('apply-failed', current_id,
                                      'Apply stopped. Inspect changed IDs; success was not recorded.'))
    finally:
        if locked:
            try:
                lock.unlink()
            except OSError:
                result.problems.append(Problem('lock-cleanup-failed', 'state', 'Apply lock could not be removed.'))
    return result


def verify_deployment(layout: Layout) -> list[Problem]:
    plan = build_plan(layout)
    problems = list(plan.problems)
    if problems:
        return problems
    if not plan.state:
        problems.append(Problem('not-recorded', 'state', 'No verified deployment is recorded.'))
    elif plan.state['source_commit'] != plan.source_commit:
        problems.append(Problem('commit-mismatch', 'state', 'Recorded and source commits differ.'))
    if plan.source_dirty:
        problems.append(Problem('dirty-source', 'source', 'Source contains uncommitted changes.'))
    for op in plan.operations:
        if op.action == 'retired':
            problems.append(Problem('retired', op.target_id, 'Previously managed file remains.'))
        elif op.expected_before != op.desired_bytes or op.action == 'adopt':
            problems.append(Problem('mismatch', op.target_id, 'Content or ownership differs from the recorded source.'))
    problems.extend(p for p in plan.notes if p.code == 'orphaned-override')
    return problems
