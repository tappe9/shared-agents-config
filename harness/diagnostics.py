from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .content import canonical_text, read_dependencies
from .paths import Layout, assert_safe_target, is_link


@dataclass(frozen=True)
class Diagnostic:
    name: str
    status: str
    evidence_kind: str
    message: str


def _local(layout: Layout) -> dict:
    path = layout.local_config
    root = layout.codex_home if path.is_relative_to(layout.codex_home) else path.parent
    assert_safe_target(root, path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    data = tomllib.loads(raw.decode('utf-8-sig'))
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('invalid-local-config')
    if set(data) - {'schema_version', 'superpowers', 'git_commit', 'client'}:
        raise ValueError('invalid-local-config')
    for section in ('superpowers', 'git_commit', 'client'):
        if not isinstance(data.get(section, {}), dict):
            raise ValueError('invalid-local-config')
    for section, key in (('superpowers', 'skills_root'), ('git_commit', 'skill_file')):
        value = data.get(section, {}).get(key)
        if value is not None and (not isinstance(value, str) or not Path(value).is_absolute()):
            raise ValueError('invalid-local-path')
    return data


def inspect_runtime(layout: Layout) -> list[Diagnostic]:
    checks: list[Diagnostic] = []
    try:
        local = _local(layout)
    except (OSError, ValueError, TypeError):
        local = {}
        checks.append(Diagnostic('local-config', 'warn', 'not_checked', 'Local diagnostic configuration is invalid.'))
    try:
        manifest = read_dependencies(layout.repo)
    except (OSError, ValueError):
        manifest = {'required_skills': []}
        checks.append(Diagnostic('dependencies', 'missing', 'observed', 'Dependency manifest cannot be read.'))
    for name in manifest['required_skills']:
        source = local.get('superpowers', {}).get('skills_root') if name.startswith('superpowers:') else local.get('git_commit', {}).get('skill_file')
        if source is None:
            continue
        path = Path(source) / name.split(':', 1)[1] / 'SKILL.md' if name.startswith('superpowers:') else Path(source)
        root = Path(source) if name.startswith('superpowers:') else path.parent
        try:
            assert_safe_target(root, path)
            exists = path.is_file()
            checks.append(Diagnostic(
                name,
                'ok' if exists else 'missing',
                'observed',
                'File exists; session loading is not verified.' if exists else 'Required skill file is missing.',
            ))
        except (OSError, ValueError):
            checks.append(Diagnostic(name, 'warn', 'not_checked', 'Declared skill path cannot be safely inspected.'))
    override = layout.codex_home / 'AGENTS.override.md'
    try:
        assert_safe_target(layout.codex_home, override)
        active = override.is_file() and bool(canonical_text(override.read_bytes()).strip())
        checks.append(Diagnostic('global-override', 'warn' if active else 'ok', 'observed',
                                 'Nonempty override may hide shared instructions.' if active else 'No nonempty global override found.'))
    except (OSError, ValueError):
        checks.append(Diagnostic('global-override', 'warn', 'not_checked', 'Override could not be inspected.'))
    for relative in ('.codex/config.toml', '.codex/agents', '.agents/skills'):
        path = layout.repo / relative
        if path.exists() or is_link(path):
            checks.append(Diagnostic('project-scope:' + relative, 'warn', 'observed', 'Project scope may change effective configuration.'))
    if is_link(layout.skills_home / 'superpowers'):
        checks.append(Diagnostic('legacy-superpowers', 'warn', 'observed', 'Legacy skill link exists; review for configuration conflicts.'))
    config = layout.codex_home / 'config.toml'
    try:
        assert_safe_target(layout.codex_home, config)
        if config.is_file():
            data = tomllib.loads(config.read_bytes().decode('utf-8-sig'))
            entries = data.get('skills', {}).get('config', [])
            uncertain = any(not isinstance(e.get('path'), str) or
                            not Path(e['path']).is_absolute() or not Path(e['path']).is_file() for e in entries)
            if uncertain:
                checks.append(Diagnostic('skill-overrides', 'warn', 'observed', 'Named, relative or absent skill targets need configuration review.'))
    except (OSError, ValueError, TypeError, AttributeError):
        checks.append(Diagnostic('skill-overrides', 'warn', 'not_checked', 'Skill override configuration cannot be inspected.'))
    return checks
