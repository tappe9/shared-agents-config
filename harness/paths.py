from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Problem:
    code: str
    target_id: str
    message: str


@dataclass(frozen=True)
class Layout:
    repo: Path
    home: Path
    codex_home: Path
    skills_home: Path
    state_dir: Path
    local_config: Path


def resolve_layout(repo: Path, *, home: Path, codex_home: Path | None,
                   env: Mapping[str, str]) -> Layout:
    repo, home = repo.expanduser().absolute(), home.expanduser().absolute()
    chosen = codex_home if codex_home is not None else env.get('CODEX_HOME')
    codex = Path(chosen).expanduser().absolute() if chosen else home / '.codex'
    state = codex / 'shared-agents-config'
    return Layout(repo, home, codex, home / '.agents/skills', state, state / 'local.toml')


def validate_relative_name(name: str) -> str:
    if (not isinstance(name, str) or not name or name in {'.', '..'}
            or any(c in name for c in '/\\:<>"|?*')
            or any(ord(c) < 32 for c in name) or name[-1:] in {' ', '.'}
            or re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name)):
        raise ValueError('invalid-relative-name')
    return name


def is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def assert_safe_target(root: Path, target: Path) -> None:
    if '..' in target.parts or '..' in root.parts:
        raise ValueError('unsafe-path')
    root, target = root.absolute(), target.absolute()
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise ValueError('outside-managed-root') from None
    path = root
    for part in ('', *relative.parts):
        if part:
            validate_relative_name(part)
            path = path / part
        if is_link(path):
            raise ValueError('linked-path')
        if path != target and path.exists() and not path.is_dir():
            raise ValueError('parent-not-directory')
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('outside-managed-root')


def same_path(left: Path, right: Path) -> bool:
    if os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right)):
        return True
    try:
        return left.samefile(right) and not is_link(left) and not is_link(right)
    except (OSError, ValueError):
        return False
