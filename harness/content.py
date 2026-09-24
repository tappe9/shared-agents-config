from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

import yaml

from .paths import Problem, assert_safe_target, validate_relative_name

BEGIN = b'<!-- shared-agents-config:begin -->\n'
END = b'<!-- shared-agents-config:end -->\n'
BOM = b'\xef\xbb\xbf'


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


def validate_sources(repo: Path) -> list[Problem]:
    problems: list[Problem] = []
    try:
        files = source_files(repo)
        read_policy(repo)
    except (OSError, ValueError):
        return [Problem('invalid-source', 'source', 'Source paths, policy or Git entries are invalid.')]
    roles = set()
    skills = set()
    for name, raw in files.items():
        parts = PurePosixPath(name).parts
        if parts[0] == 'agents':
            try:
                data = tomllib.loads(raw.decode('utf-8-sig'))
                for key in ('name', 'description', 'developer_instructions'):
                    if not isinstance(data.get(key), str) or not data[key].strip():
                        raise ValueError
                if data['name'] != Path(name).stem or data['name'] in roles:
                    raise ValueError
                roles.add(data['name'])
            except (ValueError, KeyError, TypeError):
                problems.append(Problem('invalid-role', name, 'Role definition is invalid.'))
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
