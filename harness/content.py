from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError

from .paths import Problem, assert_safe_target, validate_relative_name

BEGIN = b'<!-- shared-agents-config:begin -->\n'
END = b'<!-- shared-agents-config:end -->\n'
BOM = b'\xef\xbb\xbf'

ROLE_METADATA_KEYS = frozenset({'name', 'description'})
ROLE_REQUIRED_STRING_KEYS = ('name', 'description', 'developer_instructions')
# Pinned to the Codex documentation/schema snapshot recorded in docs/role-validation.md.
MODEL_REASONING_EFFORTS = frozenset({
    'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra',
})


def canonical_text(data: bytes) -> bytes:
    return data.removeprefix(BOM).replace(b'\r\n', b'\n')


def render_agents(common: bytes, suffix: bytes) -> bytes:
    common = canonical_text(common)
    common.decode('utf-8')
    if BEGIN.rstrip() in common or END.rstrip() in common:
        raise ValueError('markers-in-source')
    if not common.endswith(b'\n'):
        common += b'\n'
    return BEGIN + common + END + suffix


def _managed_parts(current: bytes) -> tuple[bytes, bytes]:
    data = current.removeprefix(BOM)
    lines = data.splitlines(keepends=True)
    if (data.count(BEGIN.rstrip()) != 1 or data.count(END.rstrip()) != 1
            or not lines or canonical_text(lines[0]) != BEGIN):
        raise ValueError('invalid-agents-markers')
    for i, line in enumerate(lines[1:], 1):
        if canonical_text(line) == END:
            return canonical_text(b''.join(lines[1:i])), b''.join(lines[i + 1:])
    raise ValueError('invalid-agents-markers')


def managed_common(current: bytes) -> bytes:
    return _managed_parts(current)[0]


def extract_local_suffix(current: bytes, *, legacy_common: bytes | None = None) -> bytes:
    if BEGIN.rstrip() in current or END.rstrip() in current:
        return _managed_parts(current)[1]
    if legacy_common is None:
        raise ValueError('unknown-agents-boundary')
    lines = current.removeprefix(BOM).splitlines(keepends=True)
    legacy = canonical_text(legacy_common).splitlines(keepends=True)
    if not legacy or len(lines) < len(legacy):
        raise ValueError('unknown-agents-boundary')
    if [canonical_text(line) for line in lines[:len(legacy)]] != legacy:
        raise ValueError('unknown-agents-boundary')
    return b''.join(lines[len(legacy):])


def git_bytes(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ['git', '--literal-pathspecs', '-C', str(repo), *args],
            env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'), shell=False,
            check=True, capture_output=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError('git-read-failed') from None


def commit_sha(repo: Path, ref: str = 'HEAD') -> str:
    value = git_bytes(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').strip()
    if not re.fullmatch(rb'[0-9a-f]{40}', value):
        raise ValueError('invalid-commit')
    return value.decode('ascii')


def source_files(repo: Path, *, ref: str | None = None) -> dict[str, bytes]:
    if ref is None:
        entries = git_bytes(repo, 'ls-files', '--stage', '-z', '--', 'AGENTS.md', 'agents', 'skills')
    else:
        ref = commit_sha(repo, ref)
        entries = git_bytes(repo, 'ls-tree', '-r', '-z', ref, '--', 'AGENTS.md', 'agents', 'skills')
    result: dict[str, bytes] = {}
    seen: set[str] = set()
    for entry in entries.split(b'\0'):
        if not entry:
            continue
        meta, raw = entry.split(b'\t', 1)
        fields = meta.split()
        mode = fields[0]
        name = raw.decode('utf-8')
        parts = PurePosixPath(name).parts
        for part in parts:
            validate_relative_name(part)
        if name.casefold() in seen or mode not in {b'100644', b'100755'}:
            raise ValueError('unsafe-source-entry')
        seen.add(name.casefold())
        if ref is None and fields[2] != b'0':
            raise ValueError('unmerged-source')
        if not (name == 'AGENTS.md' or
                (parts[0] == 'agents' and len(parts) == 2 and name.endswith('.toml')) or
                (parts[0] == 'skills' and len(parts) >= 3)):
            raise ValueError('unsupported-source-entry')
        if any(p.lower() in {'.env', 'auth.json', 'local.toml', 'state.json', 'diagnostics.json'}
               or p.lower().startswith('.env.') for p in parts):
            raise ValueError('sensitive-source-entry')
        if ref is not None:
            result[name] = git_bytes(repo, 'show', f'{ref}:{name}')
        else:
            path = repo / name
            assert_safe_target(repo, path)
            result[name] = path.read_bytes()
    if 'AGENTS.md' not in result:
        raise ValueError('missing-common-agents')
    return result


def read_policy(repo: Path) -> tuple[str, ...]:
    path = repo / 'config/skills-policy.toml'
    assert_safe_target(repo, path)
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8-sig'))
        if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
            raise ValueError
        names = data['skills']['disabled_user_dirs']
        if not isinstance(names, list):
            raise ValueError
        for name in names:
            validate_relative_name(name)
        if len({n.casefold() for n in names}) != len(names):
            raise ValueError
        return tuple(names)
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('invalid-skills-policy') from None


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key, value in loader.construct_pairs(node, deep=deep):
        if key in result:
            raise ValueError('duplicate-yaml-key')
        result[key] = value
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def read_role_schema(repo: Path) -> dict:
    path = repo / 'config/codex-config.schema.json'
    assert_safe_target(repo, path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('type') != 'object' or
                data.get('additionalProperties') is not False or
                not isinstance(data.get('properties'), dict)):
            raise ValueError
        Draft7Validator.check_schema(data)
        return data
    except (OSError, UnicodeError, json.JSONDecodeError, SchemaError, TypeError, ValueError):
        raise ValueError('invalid-role-schema') from None


def _role_problem(name: str, key: str, reason: str) -> Problem:
    return Problem('invalid-role', 'codex:' + name, f'Role setting "{key}" {reason}.')


def _schema_problem(name: str, error) -> Problem:
    path = [str(part) for part in error.absolute_path]
    if error.validator == 'additionalProperties':
        match = re.search(r"'([^']+)' (?:was|were) unexpected", error.message)
        if match:
            path.append(match.group(1))
    elif error.validator == 'required':
        match = re.search(r"'([^']+)' is a required property", error.message)
        if match:
            path.append(match.group(1))
    key = '.'.join(path) or '<root>'
    reason = {
        'additionalProperties': 'is not supported by the pinned Codex schema',
        'enum': 'has an invalid value',
        'oneOf': 'has an invalid value',
        'type': 'has an invalid type',
        'minLength': 'does not meet the minimum length',
        'minimum': 'is below the allowed minimum',
        'maximum': 'is above the allowed maximum',
        'required': 'is required by the pinned Codex schema',
    }.get(error.validator, 'does not satisfy the pinned Codex schema')
    return _role_problem(name, key, reason)


def _validate_role_definition(name: str, data: dict, roles: set[str],
                              schema: dict, validator: Draft7Validator) -> list[Problem]:
    if not isinstance(data, dict):
        return [_role_problem(name, '<root>', 'must be a TOML table')]

    for key in ROLE_REQUIRED_STRING_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            return [_role_problem(name, key, 'must be a non-empty string')]

    role_name = data['name']
    if role_name != Path(name).stem:
        return [_role_problem(name, 'name', 'must match the role filename')]
    if role_name in roles:
        return [_role_problem(name, 'name', 'duplicates another role name')]

    allowed_keys = set(schema['properties']) | ROLE_METADATA_KEYS
    unknown = sorted(set(data) - allowed_keys)
    if unknown:
        return [_role_problem(name, unknown[0], 'is not supported by the pinned Codex schema')]

    if 'model' in data:
        model = data['model']
        if not isinstance(model, str) or not model.strip():
            return [_role_problem(name, 'model', 'must be a non-empty string')]

    if 'model_reasoning_effort' in data:
        effort = data['model_reasoning_effort']
        if not isinstance(effort, str) or effort not in MODEL_REASONING_EFFORTS:
            return [_role_problem(
                name, 'model_reasoning_effort',
                'is not a documented value for the pinned Codex specification',
            )]

    config_data = {key: value for key, value in data.items() if key not in ROLE_METADATA_KEYS}
    errors = sorted(
        validator.iter_errors(config_data),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), str(error.validator)),
    )
    return [_schema_problem(name, errors[0])] if errors else []


def validate_sources(repo: Path) -> list[Problem]:
    problems: list[Problem] = []
    try:
        files = source_files(repo)
        read_policy(repo)
    except (OSError, ValueError):
        return [Problem('invalid-source', 'source', 'Source paths, policy or Git entries are invalid.')]
    try:
        role_schema = read_role_schema(repo)
        role_validator = Draft7Validator(role_schema)
    except ValueError:
        return [Problem('invalid-role-schema', 'config:codex-config.schema.json',
                        'Pinned Codex role schema is invalid or unreadable.')]
    roles = set()
    skills = set()
    for name, raw in files.items():
        parts = PurePosixPath(name).parts
        if parts[0] == 'agents':
            try:
                data = tomllib.loads(raw.decode('utf-8-sig'))
                role_problems = _validate_role_definition(
                    name, data, roles, role_schema, role_validator,
                )
                if role_problems:
                    problems.extend(role_problems)
                else:
                    roles.add(data['name'])
            except (UnicodeError, ValueError, KeyError, TypeError):
                problems.append(Problem(
                    'invalid-role', 'codex:' + name,
                    'Role TOML cannot be parsed safely.',
                ))
        if parts[0] == 'skills' and parts[-1] == 'SKILL.md' and len(parts) == 3:
            try:
                text = raw.decode('utf-8-sig')
                lines = text.splitlines()
                if lines[0] != '---':
                    raise ValueError
                end = lines.index('---', 1)
                data = yaml.load('\n'.join(lines[1:end]), Loader=UniqueSafeLoader)
                if not isinstance(data, dict):
                    raise ValueError
                for key in ('name', 'description'):
                    if not isinstance(data.get(key), str) or not data[key].strip():
                        raise ValueError
                if data['name'] != parts[1] or data['name'] in skills:
                    raise ValueError
                skills.add(data['name'])
            except (ValueError, yaml.YAMLError, TypeError, IndexError):
                problems.append(Problem('invalid-skill', name, 'Skill frontmatter is invalid.'))
        if parts[0] == 'skills' and name.endswith('.md'):
            try:
                text = raw.decode('utf-8-sig')
                for ref in re.findall(r'references/[\w./-]+\.md', text):
                    resolved = '/'.join(parts[:2]) + '/' + ref
                    if '..' in PurePosixPath(ref).parts or resolved not in files:
                        problems.append(Problem('missing-reference', name, 'Referenced file is not tracked.'))
            except UnicodeError:
                problems.append(Problem('invalid-text', name, 'Markdown must be UTF-8.'))
    try:
        common = files['AGENTS.md'].decode('utf-8-sig')
        render_agents(files['AGENTS.md'], b'')
        lines = [line for line in common.splitlines() if '`agent_type`' in line]
        allowed = set(re.findall(r'`([^`]+)`', '\n'.join(lines))) - {'agent_type'}
        if not allowed or allowed != roles:
            problems.append(Problem('role-allowlist', 'AGENTS.md', 'Role allowlist differs from definitions.'))
    except ValueError:
        problems.append(Problem('invalid-text', 'AGENTS.md', 'Common instructions are invalid.'))
    for name in files:
        parts = PurePosixPath(name).parts
        if parts[0] == 'skills' and parts[1] not in skills:
            problems.append(Problem('missing-skill-root', name, 'A valid top-level SKILL.md is required.'))
    try:
        dependencies = set(read_dependencies(repo)['required_skills'])
        references = set()
        for name, raw in files.items():
            if name.endswith('.md'):
                references.update(re.findall(r'`(superpowers:[a-z0-9-]+|git-commit)`', raw.decode('utf-8-sig')))
        if references - dependencies:
            problems.append(Problem('missing-dependency', 'dependencies', 'An external skill reference is not declared.'))
    except (ValueError, OSError):
        problems.append(Problem('invalid-dependencies', 'dependencies', 'Dependency manifest is invalid.'))
    return problems


def read_dependencies(repo: Path) -> dict:
    path = repo / 'config/dependencies.toml'
    assert_safe_target(repo, path)
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8-sig'))
        if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
            raise ValueError
        names = data['required_skills']
        if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
            raise ValueError
        if len(set(names)) != len(names):
            raise ValueError
        for name in names:
            if name != 'git-commit':
                if not name.startswith('superpowers:'):
                    raise ValueError
                validate_relative_name(name.split(':', 1)[1])
        if set(data) != {'schema_version', 'required_skills'}:
            raise ValueError
        return data
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('invalid-dependency-manifest') from None
