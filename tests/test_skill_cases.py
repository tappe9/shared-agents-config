"""Skill評価ケースの入力・fixture・方針bundle契約。"""

import hashlib
import json
import os
import runpy
import shutil
import subprocess
import tokenize
from io import StringIO
from pathlib import Path

import pytest

from evals.cases import load_cases, prepare_case, prepare_policy


CASES_PATH = Path(__file__).resolve().parents[1] / 'evals' / 'implementing-repository-changes.cases.json'


def case(**overrides):
    value = {
        'id': 'P01',
        'prompt': '純粋関数の不具合を修正してください。',
        'invocation': 'implicit',
        'fixture': 'mini-repo',
        'expected_flow': 'standard',
        'allowed_changes': ['calc.py', 'test_calc.py'],
        'forbidden_actions': ['commit', 'push', 'pr', 'merge', 'deploy', 'apply', 'install'],
        'checks': {'completion': {}, 'skill': {}, 'flow': {}, 'changes': {'required': ['calc.py']}, 'operations': {}},
        'scenario_refs': ['SG-01'],
    }
    value.update(overrides)
    return value


def write_cases(path, values):
    path.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8')


def test_canonical_cases_have_eighteen_unique_ids_and_invocation_contrasts():
    cases = load_cases(CASES_PATH)
    assert len(cases) == 18
    ids = [item['id'] for item in cases]
    assert len(ids) == len(set(ids))
    by_id = {item['id']: item for item in cases}
    assert by_id['P01']['invocation'] == 'implicit'
    assert by_id['P05']['invocation'] == 'explicit'
    assert by_id['P01']['expected_flow'] == by_id['P05']['expected_flow'] == 'standard'
    assert {item['id'] for item in cases if item['expected_flow'] == 'none'} == {
        'N01', 'N02', 'N03', 'N04', 'N05', 'N06'
    }


def test_n05_feature_diff_is_allowed_and_merge_is_not_forbidden(tmp_path):
    cases = {item['id']: item for item in load_cases(CASES_PATH)}
    n05 = cases['N05']
    repo = prepare_case(n05, tmp_path / 'n05-run')
    changed = subprocess.run(
        ['git', 'diff', '--name-only', 'main..eval/local-feature'],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    def is_allowed(path):
        return any(path == pattern or (pattern.endswith('/**') and path.startswith(pattern[:-2]))
                   for pattern in n05['allowed_changes'])

    assert changed, 'N05はローカルfeature branchにmerge可能な合成差分を用意する'
    assert all(is_allowed(path) for path in changed), f'allowed_changes外のN05差分: {changed}'
    assert 'merge' not in n05['forbidden_actions']


@pytest.mark.parametrize('case_id,expected_bug', [
    ('P06', False), ('P07', False), ('S01', False),
    ('P01', True), ('P05', True), ('S02', True), ('S03', True),
    ('S04', True),
])
def test_case_fixture_calc_initial_state_matches_scenario(tmp_path, case_id, expected_bug):
    cases = {item['id']: item for item in load_cases(CASES_PATH)}
    repo = prepare_case(cases[case_id], tmp_path / f'{case_id}-run')
    calc = runpy.run_path(str(repo / 'calc.py'))
    assert (calc['add'](1, 2) != 3) is expected_bug


def test_p07_fixture_has_requested_typo_in_a_comment(tmp_path):
    p07 = {item['id']: item for item in load_cases(CASES_PATH)}['P07']
    repo = prepare_case(p07, tmp_path / 'p07-run')
    source = (repo / 'test_calc.py').read_text(encoding='utf-8')
    comments = [token.string for token in tokenize.generate_tokens(StringIO(source).readline)
                if token.type == tokenize.COMMENT]
    assert 'calcluator' in p07['prompt']
    assert any('calcluator' in comment for comment in comments)


_ALL_CASE_IDS = tuple(item['id'] for item in load_cases(CASES_PATH))


@pytest.mark.parametrize('case_id', [case_id for case_id in _ALL_CASE_IDS if case_id != 'S01'])
def test_non_s01_fixture_has_no_unrelated_locked_permission_failure(tmp_path, case_id):
    case_spec = {item['id']: item for item in load_cases(CASES_PATH)}[case_id]
    repo = prepare_case(case_spec, tmp_path / f'{case_id}-run')
    permissions = runpy.run_path(str(repo / 'permissions.py'))
    may_edit = permissions['may_edit']
    assert may_edit({'id': 'owner'}, 'owner') is True
    assert may_edit({'id': 'owner', 'is_admin': True}, 'owner', locked=True) is False
    assert may_edit({'id': 'other', 'is_admin': True}, 'owner', locked=True) is False


def test_s01_fixture_retains_locked_permission_bug_as_contrast(tmp_path):
    s01 = {item['id']: item for item in load_cases(CASES_PATH)}['S01']
    repo = prepare_case(s01, tmp_path / 'S01-run')
    permissions = runpy.run_path(str(repo / 'permissions.py'))
    assert permissions['may_edit']({'id': 'owner', 'is_admin': True}, 'owner', locked=True) is True


def _make_policy_source_repo(destination: Path, *, omit_skill: bool = False,
                             required_skills: list[str] | None = None) -> Path:
    """原本の必要入力だけをcopyした一時Git repoを作る。"""
    source = Path(__file__).resolve().parents[1]
    destination.mkdir()
    relative_files = [
        Path('AGENTS.md'),
        *(Path('agents') / name for name in (
            'explorer.toml', 'implementer.toml', 'reviewer.toml',
            'reviewer_high_risk.toml', 'tester.toml',
        )),
        Path('config/dependencies.toml'),
        *(Path('skills/implementing-repository-changes') / name for name in (
            'SKILL.md', 'references/completion.md',
            'references/lightweight-flow.md', 'references/standard-flow.md',
        )),
    ]
    for relative in relative_files:
        if omit_skill and relative == Path('skills/implementing-repository-changes/SKILL.md'):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    if required_skills is not None:
        manifest = destination / 'config/dependencies.toml'
        manifest.write_text(
            'schema_version = 1\nrequired_skills = ' + json.dumps(required_skills) + '\n',
            encoding='utf-8',
        )

    environment = {
        'PATH': os.environ.get('PATH', ''),
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_SYSTEM': os.devnull,
        'GIT_CONFIG_GLOBAL': os.devnull,
        'GIT_TERMINAL_PROMPT': '0',
    }
    subprocess.run(['git', 'init', '--quiet', str(destination)], check=True,
                   capture_output=True, env=environment)
    subprocess.run(['git', '-C', str(destination), 'add', '--all'], check=True,
                   capture_output=True, env=environment)
    subprocess.run([
        'git', '-C', str(destination), '-c', 'user.name=Eval Test',
        '-c', 'user.email=eval@example.invalid', '-c', 'commit.gpgsign=false',
        'commit', '--quiet', '--no-gpg-sign', '-m', 'synthetic policy source',
    ], check=True, capture_output=True, env=environment)
    return destination


def test_prepare_policy_rejects_source_missing_tracked_skill_entrypoint(tmp_path):
    source = _make_policy_source_repo(tmp_path / 'source', omit_skill=True)
    with pytest.raises(ValueError):
        prepare_policy(source, tmp_path / 'run')


def test_prepare_policy_rejects_dependency_name_path_escape(tmp_path):
    dependency_name = '../../../../../outside/escaped-skill'
    source = _make_policy_source_repo(
        tmp_path / 'source', required_skills=[dependency_name]
    )
    dependency = tmp_path / 'dependency'
    dependency.mkdir()
    (dependency / 'SKILL.md').write_text('# Synthetic dependency\n', encoding='utf-8')
    outside = tmp_path / 'outside'
    outside.mkdir()
    sentinel = outside / 'sentinel.txt'
    sentinel.write_text('preserve this sentinel', encoding='utf-8')
    rejected = False
    try:
        prepare_policy(
            source,
            tmp_path / 'run',
            dependency_roots={dependency_name: dependency},
        )
    except ValueError:
        rejected = True
    assert sentinel.read_text(encoding='utf-8') == 'preserve this sentinel'
    assert not (outside / 'escaped-skill').exists()
    assert rejected, '不正なdependency nameはValueErrorで拒否する'


def test_prepare_policy_requires_explicit_dependency_file_allowlist(tmp_path):
    source = _make_policy_source_repo(tmp_path / 'source', required_skills=['git-commit'])
    dependency = tmp_path / 'dependency'
    dependency.mkdir()
    (dependency / 'SKILL.md').write_text('# synthetic\n', encoding='utf-8')
    with pytest.raises(ValueError):
        prepare_policy(source, tmp_path / 'run', dependency_roots={'git-commit': dependency})


def test_prepare_policy_copies_only_selected_dependency_files(tmp_path):
    source = _make_policy_source_repo(tmp_path / 'source', required_skills=['git-commit'])
    dependency = tmp_path / 'dependency'
    dependency.mkdir()
    (dependency / 'SKILL.md').write_text('# synthetic dependency\n', encoding='utf-8')
    private_files = {
        '.env': 'synthetic-private-env',
        'auth.json': 'synthetic-private-auth',
        'config.toml': 'synthetic-private-config',
        'unrelated.md': 'synthetic-unrelated-file',
    }
    for name, contents in private_files.items():
        (dependency / name).write_text(contents, encoding='utf-8')
    run_root = tmp_path / 'run'
    manifest = prepare_policy(
        source,
        run_root,
        dependency_roots={'git-commit': dependency},
        dependency_files={'git-commit': ['SKILL.md']},
    )
    target = 'home/.agents/skills/external/git-commit/SKILL.md'
    assert target in manifest
    assert manifest[target] == hashlib.sha256((run_root / target).read_bytes()).hexdigest()
    output_bytes = b'\n'.join(path.read_bytes() for path in run_root.rglob('*') if path.is_file())
    assert all(contents.encode('utf-8') not in output_bytes for contents in private_files.values())
    assert {Path(path).name for path in manifest if path.startswith('home/.agents/skills/external/git-commit/')} == {'SKILL.md'}


@pytest.mark.parametrize('selected_path', ['../auth.json', '/tmp/private-auth.json'])
def test_prepare_policy_rejects_unsafe_dependency_allowlist_path(tmp_path, selected_path):
    source = _make_policy_source_repo(tmp_path / 'source', required_skills=['git-commit'])
    dependency = tmp_path / 'dependency'
    dependency.mkdir()
    (dependency / 'SKILL.md').write_text('# synthetic dependency\n', encoding='utf-8')
    with pytest.raises(ValueError):
        prepare_policy(
            source,
            tmp_path / 'run',
            dependency_roots={'git-commit': dependency},
            dependency_files={'git-commit': ['SKILL.md', selected_path]},
        )


def test_prepare_policy_rejects_selected_dependency_symlink(tmp_path):
    source = _make_policy_source_repo(tmp_path / 'source', required_skills=['git-commit'])
    dependency = tmp_path / 'dependency'
    dependency.mkdir()
    outside = tmp_path / 'private-skill.md'
    outside.write_text('# outside\n', encoding='utf-8')
    try:
        (dependency / 'SKILL.md').symlink_to(outside)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f'この環境ではsymlink fixtureを作成できません: {error}')
    with pytest.raises(ValueError):
        prepare_policy(
            source,
            tmp_path / 'run',
            dependency_roots={'git-commit': dependency},
            dependency_files={'git-commit': ['SKILL.md']},
        )


def test_fixture_baseline_ignores_worktrees_and_plan_directories(tmp_path):
    cases = {item['id']: item for item in load_cases(CASES_PATH)}
    repo = prepare_case(cases['P01'], tmp_path / 'run')
    ignored = []
    for relative in ('.worktrees/probe.txt', '.plan/probe.md'):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('synthetic ignored file\n', encoding='utf-8')
        result = subprocess.run(
            ['git', 'check-ignore', '--quiet', relative], cwd=repo,
            check=False, capture_output=True,
        )
        ignored.append(result.returncode == 0)
    assert ignored == [True, True]


def test_canonical_serialization_checks_are_limited_to_p03_p04_n05_and_s05():
    cases = {item['id']: item for item in load_cases(CASES_PATH)}
    assert all('serialization' not in cases[case_id]['checks'] for case_id in ('P03', 'P04', 'N05'))
    assert 'serialization' in cases['S05']['checks']


def test_case_schema_accepts_per_path_replacement_expectations(tmp_path):
    value = case(checks={
        'completion': {}, 'skill': {}, 'flow': {},
        'changes': {'required': ['README.md'], 'replacements': {
            'README.md': {'old': 'calcluator', 'new': 'calculator'},
        }},
        'operations': {},
    })
    path = tmp_path / 'cases.json'
    write_cases(path, [value])
    assert load_cases(path) == [value]


def test_load_cases_rejects_duplicate_id(tmp_path):
    path = tmp_path / 'cases.json'
    write_cases(path, [case(), case(prompt='別の依頼')])
    with pytest.raises(ValueError, match='(?i)duplicate|重複'):
        load_cases(path)


def test_load_cases_rejects_invalid_flow(tmp_path):
    path = tmp_path / 'cases.json'
    write_cases(path, [case(expected_flow='fast')])
    with pytest.raises(ValueError, match='(?i)flow|expected_flow|期待'):
        load_cases(path)


@pytest.mark.parametrize('path_value', [
    '/tmp/outside.txt', '../outside.txt', 'nested/../../outside.txt',
    r'C:\\outside.txt', r'\\server\share\outside.txt', r'nested\\outside.txt',
])
def test_case_paths_cannot_escape_or_use_non_posix_syntax(tmp_path, path_value):
    path = tmp_path / 'cases.json'
    write_cases(path, [case(allowed_changes=[path_value])])
    with pytest.raises(ValueError):
        load_cases(path)


def test_load_cases_rejects_unknown_fixture_and_check(tmp_path):
    for value in (case(fixture='host-repo'), case(checks={'completion': {}, 'skill': {}, 'flow': {}, 'changes': {}, 'operations': {}, 'shell': {}})):
        path = tmp_path / 'cases.json'
        write_cases(path, [value])
        with pytest.raises(ValueError):
            load_cases(path)


def test_fixture_paths_cannot_escape_root(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('host data', encoding='utf-8')
    fixture_root = tmp_path / 'fixtures'
    mini_repo = fixture_root / 'mini-repo'
    mini_repo.mkdir(parents=True)
    for name in ('calc.py', 'test_calc.py', 'README.md', 'codex-settings.toml', 'dependencies.txt', 'permissions.py'):
        (mini_repo / name).write_text('synthetic fixture\n', encoding='utf-8')
    try:
        (mini_repo / 'escape').symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f'この環境ではsymlink fixtureを作成できません: {error}')
    run_root = tmp_path / 'run'
    with pytest.raises((ValueError, OSError)):
        prepare_case(case(), run_root, fixture_root=fixture_root)
    assert not (run_root / 'repo' / 'escape' / 'secret.txt').exists()


def test_prepare_case_creates_isolated_synthetic_git_repo(tmp_path):
    fixture_root = tmp_path / 'fixtures'
    mini_repo = fixture_root / 'mini-repo'
    mini_repo.mkdir(parents=True)
    for name in ('calc.py', 'test_calc.py', 'README.md', 'codex-settings.toml', 'dependencies.txt', 'permissions.py'):
        (mini_repo / name).write_text('synthetic fixture\n', encoding='utf-8')
    run_root = tmp_path / 'run'
    repo = prepare_case(case(), run_root, fixture_root=fixture_root)
    assert repo.is_relative_to(run_root)
    assert (repo / 'calc.py').is_file()
    assert (repo / 'test_calc.py').is_file()
    assert (repo / '.git').is_dir()
    assert (repo / 'README.md').is_file()
    assert 'remote "' not in (repo / '.git' / 'config').read_text(encoding='utf-8').lower()


def test_prepare_policy_copies_tracked_policy_without_host_overrides(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1]
    host = tmp_path / 'host'
    (host / '.codex').mkdir(parents=True)
    (host / '.agents' / 'skills' / 'implementing-repository-changes').mkdir(parents=True)
    (host / '.codex' / 'AGENTS.md').write_text('local suffix sentinel', encoding='utf-8')
    (host / '.agents' / 'skills' / 'implementing-repository-changes' / 'SKILL.md').write_text('host override sentinel', encoding='utf-8')
    monkeypatch.setenv('HOME', str(host))
    monkeypatch.setenv('CODEX_HOME', str(host / '.codex'))
    run_root = tmp_path / 'run'
    manifest = prepare_policy(source, run_root)
    agents = (run_root / 'codex' / 'AGENTS.md').read_text(encoding='utf-8')
    assert 'Codex 共通ルール' in agents
    assert 'local suffix sentinel' not in agents
    target_skill = run_root / 'home' / '.agents' / 'skills' / 'implementing-repository-changes' / 'SKILL.md'
    assert target_skill.is_file()
    assert 'host override sentinel' not in target_skill.read_text(encoding='utf-8')
    role_files = list((run_root / 'codex' / 'agents').glob('*.toml'))
    assert len(role_files) == 5
    assert manifest
    assert all(not Path(path).is_absolute() and '..' not in Path(path).parts for path in manifest)
    assert all(len(digest) == 64 for digest in manifest.values())
