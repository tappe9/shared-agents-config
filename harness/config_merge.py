from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import tomllib
import tomlkit
from tomlkit.items import Array, InlineTable
from tomlkit.exceptions import TOMLKitError

from .content import BOM
from .paths import same_path


def _parse(original: bytes):
    try:
        document = tomlkit.parse(original.removeprefix(BOM).decode('utf-8'))
        skills = document.get('skills')
        if skills is not None and not isinstance(skills, Mapping):
            raise ValueError
        entries = skills.get('config') if skills is not None else None
        if entries is not None and (not isinstance(entries, list) or
                                    any(not isinstance(e, Mapping) for e in entries)):
            raise ValueError
        return document, entries
    except (ValueError, TypeError, TOMLKitError):
        raise ValueError('invalid-skills-config') from None


def _matches(entry: Mapping, target: Path) -> bool:
    value = entry.get('path')
    return isinstance(value, str) and Path(value).is_absolute() and same_path(Path(value), target)


def _enabled(entry: Mapping) -> bool:
    value = entry.get('enabled', True)
    if type(value) is not bool:
        raise ValueError('invalid-enabled-type')
    return value


def read_overrides(original: bytes, targets: Sequence[Path]) -> dict[Path, bool]:
    _, entries = _parse(original)
    result = {}
    for target in targets:
        matched = [e for e in (entries or []) if _matches(e, target)]
        if matched:
            values = {_enabled(e) for e in matched}
            if len(values) > 1:
                raise ValueError('conflicting-enabled-values')
            result[target] = values.pop()
    return result


def merge_skill_overrides(original: bytes, overrides: Mapping[Path, bool]) -> bytes:
    document, entries = _parse(original)
    if not overrides:
        return original
    for target, enabled in overrides.items():
        if not target.is_absolute() or type(enabled) is not bool:
            raise ValueError('invalid-override')
    if entries is None:
        if 'skills' not in document:
            document['skills'] = tomlkit.table()
        document['skills']['config'] = (tomlkit.array() if isinstance(document['skills'], InlineTable)
                                        else tomlkit.aot())
        entries = document['skills']['config']
    changed = False
    for target, enabled in overrides.items():
        indices = [i for i, entry in enumerate(entries) if _matches(entry, target)]
        if len(indices) > 1:
            if any(set(entries[i]) - {'path', 'enabled'} for i in indices):
                raise ValueError('ambiguous-duplicate-override')
            for i in indices:
                _enabled(entries[i])
            for i in reversed(indices[1:]):
                del entries[i]
            changed = True
        if indices:
            entry = entries[indices[0]]
            if _enabled(entry) != enabled or 'enabled' not in entry:
                entry['enabled'] = enabled
                changed = True
        else:
            entry = tomlkit.inline_table() if isinstance(entries, Array) else tomlkit.table()
            entry['path'] = str(target)
            entry['enabled'] = enabled
            entries.append(entry)
            changed = True
    if not changed:
        return original
    prefix = BOM if original.startswith(BOM) else b''
    serialized = tomlkit.dumps(document)
    try:
        tomllib.loads(serialized)
    except ValueError:
        raise ValueError('invalid-generated-config') from None
    return prefix + serialized.encode('utf-8')
