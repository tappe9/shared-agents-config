from __future__ import annotations

import os
import re
import stat
import unicodedata
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
    left, right = Path(os.path.abspath(left)), Path(os.path.abspath(right))
    try:
        left.lstat()
    except FileNotFoundError:
        left_missing = True
    except (OSError, ValueError):
        return False
    else:
        left_missing = False
    try:
        right.lstat()
    except FileNotFoundError:
        right_missing = True
    except (OSError, ValueError):
        return False
    else:
        right_missing = False

    if left_missing or right_missing:
        # 存在しないパスでは従来の字句比較を保ち、既存パスへの表記差は実体を調べる。
        return left_missing and right_missing and (
            os.path.normcase(str(left)) == os.path.normcase(str(right)))

    # 同じ綴りの既存パスは一覧権限に依存させず、symlinkや確認不能な経路は拒否する。
    if str(left) == str(right):
        return not _has_link_component(left)

    left_entry = _directory_entry_identity(left)
    right_entry = _directory_entry_identity(right)
    return left_entry is not None and left_entry == right_entry


def _has_link_component(path: Path) -> bool:
    try:
        return any(is_link(component) for component in (path, *path.parents))
    except (OSError, ValueError):
        return True


def _directory_entry_identity(path: Path) -> tuple[int, int, str] | None:
    try:
        # 親ディレクトリのsymlink経由を受け入れると、別scopeのaliasまで統合し得る。
        if _has_link_component(path):
            return None
        parent_info = path.parent.stat()
        if not stat.S_ISDIR(parent_info.st_mode):
            return None
        with os.scandir(path.parent) as scanned:
            entries = list(scanned)
    except (OSError, ValueError):
        return None

    exact = [entry for entry in entries if entry.name == path.name]
    if len(exact) == 1:
        return parent_info.st_dev, parent_info.st_ino, exact[0].name
    if exact:
        return None

    # 大文字小文字とUnicode表記を正規化してbasenameを絞り、別名hardlinkは候補に含めない。
    requested_name = unicodedata.normalize('NFC', path.name).casefold()
    aliases = []
    try:
        for entry in entries:
            if unicodedata.normalize('NFC', entry.name).casefold() != requested_name:
                continue
            if entry.is_symlink():
                continue
            if os.path.samefile(path, entry.path):
                aliases.append(entry.name)
    except (OSError, ValueError):
        return None
    if len(aliases) != 1:
        return None
    return parent_info.st_dev, parent_info.st_ino, aliases[0]
