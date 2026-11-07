"""ケース定義の検証と合成repo・方針bundleの準備。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from jsonschema import Draft202012Validator
from harness.content import read_dependencies
from harness.paths import assert_safe_target, is_link, validate_relative_name


_PACKAGE_ROOT = Path(__file__).resolve().parent
_SCHEMA_PATH = _PACKAGE_ROOT / "cases.schema.json"
_ROLES = (
    "explorer.toml",
    "implementer.toml",
    "reviewer.toml",
    "reviewer_high_risk.toml",
    "tester.toml",
)
_POLICY_FILES = (
    "AGENTS.md",
    *(f"agents/{name}" for name in _ROLES),
    "config/dependencies.toml",
)
_SKILL_PREFIX = "skills/implementing-repository-changes/"
_KNOWN_RUN_DIRS = {"repo", "codex", "home"}
_FIXTURE_FILES = {
    ".gitignore",
    "README.md",
    "calc.py",
    "codex-settings.toml",
    "dependencies.txt",
    "permissions.py",
    "test_calc.py",
    "test_permissions.py",
    "test_calc.py.template",
    "test_permissions.py.template",
}
_REQUIRED_FIXTURE_FILES = {
    "README.md",
    "calc.py",
    "codex-settings.toml",
    "dependencies.txt",
    "permissions.py",
}
_BUGGY_ADD_CASES = {"P01", "P05", "N03", "S02", "S03", "S04", "S05"}
_BUGGY_LOCKED_PERMISSION_CASES = {"S01"}


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_case_list(value: object) -> list[dict]:
    errors = sorted(Draft202012Validator(_schema()).iter_errors(value), key=lambda e: list(map(str, e.path)))
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.path) or "root"
        raise ValueError(f"ケース定義 {location}: {error.message}")

    assert isinstance(value, list)
    ids: set[str] = set()
    for case in value:
        assert isinstance(case, dict)
        case_id = case["id"]
        if case_id in ids:
            raise ValueError(f"ケースIDが重複しています: {case_id}")
        ids.add(case_id)

        for field in ("allowed_changes",):
            for item in case[field]:
                _safe_relative_path(item, allow_glob=True)
        checks = case["checks"]
        for item in checks["changes"]["required"]:
            _safe_relative_path(item)
        for item in checks["changes"].get("contains", {}):
            _safe_relative_path(item)
        for item, replacement in checks["changes"].get("replacements", {}).items():
            _safe_relative_path(item)
            if replacement["old"] == replacement["new"]:
                raise ValueError("置換のoldとnewは異なる内容を指定してください")
        roles = checks.get("roles", {})
        if set(roles.get("required", ())) & set(roles.get("forbidden", ())):
            raise ValueError(f"ケース {case_id}: roles.required と roles.forbidden が重複しています")
    return value


def _safe_relative_path(value: object, *, allow_glob: bool = False) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError(f"安全でない相対POSIXパスです: {value!r}")
    if value.startswith(("/", "~")) or PureWindowsPath(value).drive:
        raise ValueError(f"安全でない相対POSIXパスです: {value!r}")

    path_value = value
    if value.endswith("/**"):
        if not allow_glob:
            raise ValueError(f"この項目ではglobを使えません: {value!r}")
        path_value = value[:-3]
    elif "*" in value or "?" in value or "[" in value or "]" in value:
        raise ValueError(f"サポートされないglobパスです: {value!r}")

    parts = path_value.split("/")
    if any(part in ("", ".", "..") for part in parts) or parts[0] == ".git":
        raise ValueError(f"安全でない相対POSIXパスです: {value!r}")
    pure_path = PurePosixPath(path_value)
    if pure_path.is_absolute() or pure_path.as_posix() != path_value:
        raise ValueError(f"正規化されていない相対POSIXパスです: {value!r}")
    return pure_path


def load_cases(path: Path) -> list[dict]:
    """JSON Schemaと追加の安全条件でケース配列を検証する。"""
    path = Path(path)
    _assert_no_symlink_components(path)
    if not path.is_file():
        raise ValueError(f"ケース定義が通常ファイルではありません: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"ケース定義を読み込めません: {error}") from error
    return _validate_case_list(raw)


def _assert_no_symlink_components(path: Path) -> Path:
    """既存のパス要素にsymlinkがあれば拒否して絶対パスを返す。"""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            current.lstat()
        except FileNotFoundError:
            continue
        if is_link(current):
            raise ValueError(f"symlink経由のパスは使えません: {current}")
    return absolute


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _prepare_run_root(run_root: Path, source_roots: tuple[Path, ...]) -> Path:
    root = _assert_no_symlink_components(Path(run_root))
    for source in source_roots:
        source = _assert_no_symlink_components(source)
        if _paths_overlap(root, source):
            raise ValueError("run_rootはsource repo/fixtureと重ならない一時領域である必要があります")

    if root.exists() and not root.is_dir():
        raise ValueError("run_rootは通常のディレクトリである必要があります")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in root.iterdir():
        if item.name not in _KNOWN_RUN_DIRS or item.is_symlink() or not item.is_dir():
            raise ValueError(f"run_rootに想定外の内容があります: {item.name}")
    return root


def _copy_regular_tree(source: Path, destination: Path, *, managed_root: Path) -> list[Path]:
    """symlinkを拒否し、通常ファイルとdirectoryだけをコピーする。"""
    _assert_no_symlink_components(source)
    if not source.is_dir():
        raise ValueError(f"fixture/policy directoryがありません: {source}")
    assert_safe_target(managed_root, destination)
    source_paths = sorted(source.rglob("*"))
    # 出力を作る前に全入力を検査し、symlinkや特殊ファイルの部分コピーを防ぐ。
    for source_path in source_paths:
        relative = source_path.relative_to(source)
        _safe_relative_path(relative.as_posix())
        mode = source_path.lstat().st_mode
        if is_link(source_path):
            raise ValueError(f"symlinkを含む入力は使えません: {relative.as_posix()}")
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(f"通常ファイル以外の入力は使えません: {relative.as_posix()}")
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    copied: list[Path] = []
    for source_path in source_paths:
        relative = source_path.relative_to(source)
        mode = source_path.lstat().st_mode
        destination_path = destination / relative
        assert_safe_target(managed_root, destination_path)
        if stat.S_ISDIR(mode):
            destination_path.mkdir(exist_ok=False, mode=0o700)
        elif stat.S_ISREG(mode):
            destination_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source_path, destination_path)
            copied.append(destination_path)
    return copied


def _validate_fixture_source(source: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"fixture directoryがありません: {source}")
    found: set[str] = set()
    for item in source.iterdir():
        mode = item.lstat().st_mode
        if is_link(item) or not stat.S_ISREG(mode):
            raise ValueError(f"fixtureはallowlist内の通常ファイルだけを含められます: {item.name}")
        found.add(item.name)
    missing = sorted(_REQUIRED_FIXTURE_FILES - found)
    unknown = sorted(found - _FIXTURE_FILES)
    ambiguous_tests = [
        source_name
        for source_name in ("test_calc.py", "test_permissions.py")
        if {source_name, source_name + ".template"} <= found
    ]
    if missing or unknown or ambiguous_tests:
        raise ValueError(
            "fixtureファイル集合が不正です "
            f"(不足: {missing}; 未知: {unknown}; 重複test: {ambiguous_tests})"
        )


def _git_environment() -> dict[str, str]:
    # git設定・identity・hooksなどのホスト由来値をfixture初期化に持ち込まない。
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        }
    )
    return environment


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env=_git_environment(),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(f"fixture git {arguments[0]} に失敗しました: {result.stderr.strip()}")
    return result.stdout.strip()


def _commit_fixture(repo: Path, message: str) -> None:
    _git(repo, "add", "--all")
    _git(repo, "commit", "--quiet", "--no-gpg-sign", "-m", message)


def prepare_case(case: dict, run_root: Path, *, fixture_root: Path | None = None) -> Path:
    """mini-repo fixtureをコピーし、remoteなしの独立Git repoにする。"""
    _validate_case_list([case])
    fixture_root = Path(fixture_root) if fixture_root is not None else _PACKAGE_ROOT / "fixtures"
    source = _assert_no_symlink_components(fixture_root) / case["fixture"]
    _assert_no_symlink_components(source)
    _validate_fixture_source(source)
    root = _prepare_run_root(Path(run_root), (source,))
    repo = root / "repo"
    if repo.exists() or repo.is_symlink():
        raise ValueError("run_root/repoは新規である必要があります")
    _copy_regular_tree(source, repo, managed_root=root)
    if not (repo / ".gitignore").exists():
        # テスト用fixtureでも標準フローの準備を範囲外変更にしない。
        (repo / ".gitignore").write_bytes(
            (_PACKAGE_ROOT / "fixtures/mini-repo/.gitignore").read_bytes()
        )
    for template_name in ("test_calc.py.template", "test_permissions.py.template"):
        template_path = repo / template_name
        if template_path.exists():
            template_path.rename(repo / template_name.removesuffix(".template"))
    if case["id"] in _BUGGY_ADD_CASES:
        calc = repo / "calc.py"
        calc.write_text(
            '"""Tiny synthetic arithmetic module for offline skill evaluation."""\n\n\n'
            'def add(a, b):\n'
            '    """Add two numbers. The fixture intentionally contains a small bug."""\n'
            '    return a + b + 1\n',
            encoding="utf-8",
        )
    if case["id"] in _BUGGY_LOCKED_PERMISSION_CASES:
        permissions = repo / "permissions.py"
        permissions.write_text(
            '"""Synthetic record permission check; no real service or identity is involved."""\n\n\n'
            'def may_edit(actor, owner_id, locked=False):\n'
            '    if actor.get("id") == owner_id:\n'
            '        return True\n'
            '    return bool(actor.get("is_admin", False))\n',
            encoding="utf-8",
        )

    _git(repo, "init", "--quiet", "--initial-branch=main")
    _git(repo, "config", "--local", "user.name", "Skill Eval Fixture")
    _git(repo, "config", "--local", "user.email", "skill-eval@example.invalid")
    _git(repo, "config", "--local", "commit.gpgsign", "false")
    (repo / ".eval-empty-hooks").mkdir()
    _git(repo, "config", "--local", "core.hooksPath", ".eval-empty-hooks")
    _commit_fixture(repo, "synthetic fixture baseline")

    if case["id"] == "N05":
        _git(repo, "checkout", "--quiet", "-b", "eval/local-feature")
        (repo / "merge-note.txt").write_text("Synthetic local merge fixture.\n", encoding="utf-8")
        _commit_fixture(repo, "synthetic feature branch")
        _git(repo, "checkout", "--quiet", "main")
    elif case["id"] == "N04":
        with (repo / "README.md").open("a", encoding="utf-8") as readme:
            readme.write("\n利用例: subtract(3, 2) は 1 を返します。\n")

    if _git(repo, "remote"):
        raise RuntimeError("fixture repoにremoteが作成されました")
    return repo


def _tracked_files(source_repo: Path, paths: tuple[str, ...]) -> list[Path]:
    result: list[Path] = []
    for relative in paths:
        _safe_relative_path(relative)
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=source_repo,
            env=_git_environment(),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        if tracked.returncode or tracked.stdout.strip() != relative:
            raise ValueError(f"原本がGit追跡されていません: {relative}")
        source = source_repo / relative
        _assert_no_symlink_components(source)
        mode = source.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError(f"原本が通常ファイルではありません: {relative}")
        result.append(source)
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_policy(
    source_repo: Path,
    run_root: Path,
    *,
    dependency_roots: Mapping[str, Path] | None = None,
    dependency_files: Mapping[str, list[str]] | None = None,
) -> dict[str, str]:
    """Git追跡された共通方針を隔離領域へ配置し、配置ファイルhashを返す。

    外部Skillは明示されたrootと相対file allowlistだけを使う。
    省略時にはホストを検索もコピーもしない。
    """
    source_repo = _assert_no_symlink_components(Path(source_repo))
    if not source_repo.is_dir():
        raise ValueError("source_repoはGit repo directoryである必要があります")
    skill_listing = subprocess.run(
        ["git", "ls-files", "-z", "--", _SKILL_PREFIX],
        cwd=source_repo,
        env=_git_environment(),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if skill_listing.returncode:
        raise ValueError("source_repoのGit追跡ファイルを確認できません")
    skill_relatives = sorted(
        item
        for item in skill_listing.stdout.split("\0")
        if item and item.startswith(_SKILL_PREFIX)
    )
    skill_entrypoint = _SKILL_PREFIX + "SKILL.md"
    if skill_entrypoint not in skill_relatives:
        raise ValueError("対象SkillのGit追跡されたSKILL.mdがありません")
    required = [*_POLICY_FILES, *skill_relatives]
    tracked_files = _tracked_files(source_repo, tuple(required))
    try:
        required_skills = read_dependencies(source_repo)["required_skills"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"config/dependencies.tomlを検証できません: {error}") from error

    explicit_roots: dict[str, Path] = {}
    selected_files: dict[str, list[tuple[str, Path]]] = {}
    if dependency_roots is None and dependency_files is not None:
        raise ValueError("dependency_filesには対応するdependency_rootsが必要です")
    if dependency_roots is not None:
        if not isinstance(dependency_files, Mapping) or set(dependency_files) != set(dependency_roots):
            raise ValueError("外部Skillには明示した必要file allowlistが必要です")
        unknown = set(dependency_roots) - set(required_skills)
        missing = set(required_skills) - set(dependency_roots)
        if unknown or missing:
            details = []
            if missing:
                details.append("未指定: " + ", ".join(sorted(missing)))
            if unknown:
                details.append("manifest外: " + ", ".join(sorted(unknown)))
            raise ValueError("外部Skill rootが不足または不正です (" + "; ".join(details) + ")")
        for name, path in dependency_roots.items():
            source = _assert_no_symlink_components(Path(path))
            if not source.is_dir():
                raise ValueError(f"外部Skill {name} の明示rootが通常directoryではありません")
            selected = dependency_files[name]
            if (not isinstance(selected, list) or not all(isinstance(item, str) for item in selected)
                    or len(set(selected)) != len(selected) or "SKILL.md" not in selected):
                raise ValueError("外部SkillのallowlistにはSKILL.mdと必要fileを指定してください")
            selected_files[name] = []
            for relative in selected:
                safe = _safe_relative_path(relative)
                if any(part.startswith(".env") or part in {".git", "auth.json", "config.toml"} for part in safe.parts):
                    raise ValueError("認証・個人config・envは外部Skill bundleに含められません")
                item = source.joinpath(*safe.parts)
                assert_safe_target(source, item)
                if not item.is_file():
                    raise ValueError("外部Skillの選択fileが通常ファイルではありません")
                selected_files[name].append((relative, item))
            explicit_roots[name] = source

    root = _prepare_run_root(Path(run_root), (source_repo, *explicit_roots.values()))
    codex_root = root / "codex"
    home_root = root / "home"
    if codex_root.exists() or codex_root.is_symlink() or home_root.exists() or home_root.is_symlink():
        raise ValueError("policy bundleの配置先は新規である必要があります")
    assert_safe_target(root, codex_root)
    assert_safe_target(root, home_root)
    codex_root.mkdir(mode=0o700)
    home_root.mkdir(mode=0o700)

    destinations: dict[str, Path] = {}
    for relative, source in zip(required, tracked_files, strict=True):
        if relative == "AGENTS.md":
            destination_relative = "codex/AGENTS.md"
        elif relative.startswith("agents/"):
            destination_relative = "codex/" + relative
        elif relative == "config/dependencies.toml":
            destination_relative = "codex/config/dependencies.toml"
        else:
            destination_relative = "home/.agents/skills/implementing-repository-changes/" + relative[len(_SKILL_PREFIX):]
        destination = root / destination_relative
        assert_safe_target(root, destination)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source, destination)
        destinations[destination_relative] = destination

    for name, source in explicit_roots.items():
        if name == "git-commit":
            safe_name = validate_relative_name(name)
        else:
            namespace, skill_name = name.split(":", 1)
            safe_name = validate_relative_name(namespace) + "--" + validate_relative_name(skill_name)
        destination_relative = f"home/.agents/skills/external/{safe_name}"
        destination = root / destination_relative
        assert_safe_target(root, destination)
        for relative, item in selected_files[name]:
            target = destination.joinpath(*PurePosixPath(relative).parts)
            assert_safe_target(root, target)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(item, target)
            destinations[target.relative_to(root).as_posix()] = target

    return {relative: _sha256(path) for relative, path in sorted(destinations.items())}
