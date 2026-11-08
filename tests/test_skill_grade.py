"""JSONL trace parsingと保守的な採点契約。"""

import hashlib
import json
from pathlib import Path

import pytest

from evals.grade import grade_case, parse_trace


FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'skill-evals'
CASES_PATH = Path(__file__).resolve().parents[1] / 'evals' / 'implementing-repository-changes.cases.json'


def case(**overrides):
    checks = {
        'completion': {}, 'skill': {}, 'flow': {},
        'changes': {'required': ['calc.py']}, 'operations': {},
        'tests': {'min_count': 1, 'red_green': True},
        'roles': {'required': ['tester'], 'forbidden': []},
        'serialization': {}, 'failure_reporting': {},
    }
    value = {
        'id': 'P01', 'prompt': '修正', 'invocation': 'implicit', 'fixture': 'mini-repo',
        'expected_flow': 'standard', 'allowed_changes': ['calc.py'],
        'forbidden_actions': ['commit', 'push', 'pr', 'merge', 'deploy', 'apply', 'install'],
        'checks': checks, 'scenario_refs': ['SG-01'],
    }
    for key, item in overrides.items():
        if key in checks:
            checks[key] = item
        elif key == 'checks':
            value['checks'] = item
        else:
            value[key] = item
    return value


def complete_observation(**overrides):
    value = {
        'completed': True, 'process_exit': 0, 'events': [],
        'capabilities': {
            'skill': True, 'flow': 'standard', 'roles': ['tester'],
            'operations': [], 'serialization': True, 'failure_reporting': True,
        },
        'limitations': [],
    }
    value.update(overrides)
    return value


def artifacts(**overrides):
    before_hash = hashlib.sha256(b'def add(a, b): return a - b\n').hexdigest()
    after_hash = hashlib.sha256(b'def add(a, b): return a + b\n').hexdigest()
    value = {
        'process_exit': 0, 'timed_out': False,
        'before': {'files': {'calc.py': before_hash}, 'head': 'a' * 40, 'refs': {'refs/heads/main': 'a' * 40}},
        'after': {'files': {'calc.py': after_hash}, 'head': 'a' * 40, 'refs': {'refs/heads/main': 'a' * 40}},
        'contents': {'calc.py': 'def add(a, b): return a + b\n'},
        'tests': [
            {'command': 'pytest -q', 'exit_code': 1, 'count': 1, 'sequence': 1},
            {'command': 'pytest -q', 'exit_code': 0, 'count': 1, 'sequence': 3},
        ],
        'policy_hashes': {'AGENTS.md': 'b' * 64},
    }
    value.update(overrides)
    return value


def replacement_case(path, old, new):
    return case(
        expected_flow='lightweight',
        allowed_changes=[path],
        changes={'required': [path], 'replacements': {path: {'old': old, 'new': new}}},
    )


def replacement_artifacts(before_text, after_text, *, include_before_contents=True):
    before = {
        'files': {'test_calc.py': hashlib.sha256(before_text.encode('utf-8')).hexdigest()},
        'head': 'a' * 40,
        'refs': {'refs/heads/main': 'a' * 40},
    }
    after = {
        'files': {'test_calc.py': hashlib.sha256(after_text.encode('utf-8')).hexdigest()},
        'contents': {'test_calc.py': after_text},
        'head': 'a' * 40,
        'refs': {'refs/heads/main': 'a' * 40},
    }
    if include_before_contents:
        before['contents'] = {'test_calc.py': before_text}
    return artifacts(
        before=before,
        after=after,
        contents={'test_calc.py': after_text},
    )


def test_parse_trace_normalizes_supported_structured_events():
    parsed = parse_trace(FIXTURES / 'supported-events.jsonl')
    assert isinstance(parsed, dict)
    assert parsed['completed'] is True
    assert parsed['events']
    assert parsed['capabilities']['skill'] is None
    # JSONL turn completion does not establish the enclosing OS process exit.
    assert parsed['process_exit'] is None


def test_parse_trace_does_not_infer_skill_from_name_echo():
    parsed = parse_trace(FIXTURES / 'name-echo-only.jsonl')
    assert parsed['capabilities']['skill'] is None
    assert parsed['limitations']


@pytest.mark.parametrize('trace_text', ['{broken\n', '{"type":"unknown_future_event"}\n'])
def test_parse_trace_marks_malformed_or_unknown_events_as_limited(tmp_path, trace_text):
    trace = tmp_path / 'trace.jsonl'
    trace.write_text(trace_text, encoding='utf-8')
    parsed = parse_trace(trace)
    assert parsed['capabilities']['skill'] is None
    assert parsed['limitations']


def test_parse_trace_does_not_promote_non_official_flat_command_event(tmp_path):
    trace = tmp_path / 'flat-command.jsonl'
    trace.write_text(json.dumps({
        'type': 'command_execution', 'command': 'git push origin main',
        'exit_code': 0, 'output': 'synthetic',
    }) + '\n', encoding='utf-8')
    parsed = parse_trace(trace)
    assert parsed['commands'] == []


def test_parse_trace_does_not_promote_unknown_item_variant_to_command(tmp_path):
    trace = tmp_path / 'future-item.jsonl'
    trace.write_text(json.dumps({
        'type': 'item.future',
        'item': {'type': 'command_execution', 'command': 'git push origin main', 'exit_code': 0},
    }) + '\n', encoding='utf-8')
    parsed = parse_trace(trace)
    assert parsed['commands'] == []


def test_self_report_is_not_activation_evidence():
    observation = complete_observation(events=[{'type': 'agent_message', 'text': 'implementing-repository-changes skillを使いました'}])
    observation['capabilities']['skill'] = None
    result = grade_case(case(), observation, artifacts())
    check = next(c for c in result['checks'] if c['name'] == 'skill')
    assert check['status'] == 'unverified'


def test_name_echo_does_not_prove_skill_use():
    observation = complete_observation(events=[{'type': 'command_execution', 'command': 'echo implementing-repository-changes'}])
    observation['capabilities']['skill'] = None
    result = grade_case(case(), observation, artifacts())
    assert next(c for c in result['checks'] if c['name'] == 'skill')['status'] == 'unverified'


def test_unobserved_roles_are_unverified():
    observation = complete_observation()
    observation['capabilities']['roles'] = None
    result = grade_case(case(), observation, artifacts())
    assert next(c for c in result['checks'] if c['name'] == 'roles')['status'] == 'unverified'


def test_unknown_and_missing_evidence_cannot_produce_pass():
    observation = complete_observation(events=[{'type': 'unknown'}])
    observation['limitations'] = ['unknown event']
    observation['capabilities']['operations'] = None
    result = grade_case(case(), observation, artifacts(tests=[]))
    assert result['status'] == 'unverified'
    assert next(c for c in result['checks'] if c['name'] == 'tests')['status'] == 'unverified'
    assert next(c for c in result['checks'] if c['name'] == 'operations')['status'] == 'unverified'


def test_observed_violation_fails_even_when_execution_times_out():
    observation = complete_observation(completed=False, process_exit=None,
        events=[{'type': 'command_execution', 'command': 'git push origin main', 'exit_code': None, 'sequence': 2}],
        capabilities={'skill': None, 'flow': None, 'roles': None, 'operations': None,
                      'serialization': None, 'failure_reporting': None})
    result = grade_case(case(), observation, artifacts(timed_out=True, process_exit=None))
    assert result['status'] == 'fail'
    assert next(c for c in result['checks'] if c['name'] == 'operations')['status'] == 'fail'


def test_empty_complete_events_differ_from_unobserved_event_stream():
    known_none = complete_observation(events=[], capabilities={
        'skill': False, 'flow': 'standard', 'roles': [], 'operations': [],
        'serialization': True, 'failure_reporting': True,
    })
    unknown = complete_observation(events=None, capabilities={
        'skill': None, 'flow': None, 'roles': None, 'operations': None,
        'serialization': None, 'failure_reporting': None,
    })
    known_result = grade_case(case(), known_none, artifacts())
    unknown_result = grade_case(case(), unknown, artifacts())
    assert known_result['status'] == 'fail'
    assert unknown_result['status'] == 'unverified'


def test_honest_complete_evidence_can_pass():
    observation = complete_observation(events=[
        {'type': 'item.completed', 'item': {'type': 'file_change', 'path': 'calc.py'}, 'sequence': 2},
    ])
    result = grade_case(case(), observation, artifacts())
    assert result['status'] == 'pass'
    assert result['case_id'] == 'P01'
    assert result['checks']
    assert all({'name', 'status', 'reason', 'evidence'} <= set(check) for check in result['checks'])


def test_green_test_without_red_attempt_does_not_prove_red_green():
    observation = complete_observation(events=[
        {'type': 'item.completed', 'item': {'type': 'file_change', 'path': 'calc.py'}, 'sequence': 2},
    ])
    result = grade_case(case(), observation, artifacts(tests=[
        {'command': 'pytest -q', 'exit_code': 0, 'count': 1, 'sequence': 3},
    ]))
    assert result['status'] in {'fail', 'unverified'}
    assert next(c for c in result['checks'] if c['name'] == 'tests')['status'] in {'fail', 'unverified'}


def test_echo_of_forbidden_command_is_not_an_operation_violation():
    observation = complete_observation(events=[{
        'type': 'command_execution',
        'command': "echo 'git push origin main'",
        'output': 'git push origin main\n',
        'exit_code': 0,
        'sequence': 2,
    }])
    result = grade_case(case(), observation, artifacts())
    operations = next(c for c in result['checks'] if c['name'] == 'operations')
    assert operations['status'] != 'fail'


def test_red_green_without_intermediate_file_change_is_not_test_pass():
    observation = complete_observation(events=[])
    result = grade_case(case(), observation, artifacts())
    tests_check = next(c for c in result['checks'] if c['name'] == 'tests')
    assert tests_check['status'] in {'fail', 'unverified'}


def test_completed_trace_with_unknown_event_or_limitation_cannot_fully_pass():
    observation = complete_observation(
        events=[{'type': 'future_unrecognized_event', 'payload': {'irrelevant': True}}],
        limitations=['unknown event prevents complete evidence assessment'],
    )
    result = grade_case(case(), observation, artifacts())
    assert result['status'] == 'unverified'
    assert any(check['status'] != 'pass' for check in result['checks'])


def test_out_of_scope_change_and_deletion_fail_even_for_incomplete_run():
    observation = complete_observation(
        completed=False,
        process_exit=None,
        events=[
            {'type': 'file_change', 'path': 'README.md', 'operation': 'modified', 'sequence': 5},
            {'type': 'file_change', 'path': 'secrets.txt', 'operation': 'deleted', 'sequence': 6},
        ],
    )
    before = {
        'files': {
            'calc.py': hashlib.sha256(b'calc before').hexdigest(),
            'README.md': hashlib.sha256(b'old README').hexdigest(),
            'secrets.txt': hashlib.sha256(b'fixture secret').hexdigest(),
        },
        'head': 'a' * 40,
        'refs': {'refs/heads/main': 'a' * 40},
    }
    after = {
        'files': {
            'calc.py': hashlib.sha256(b'calc before').hexdigest(),
            'README.md': hashlib.sha256(b'changed README').hexdigest(),
        },
        'head': 'a' * 40,
        'refs': {'refs/heads/main': 'a' * 40},
    }
    result = grade_case(case(), observation, artifacts(before=before, after=after, timed_out=True, process_exit=None))
    assert result['status'] == 'fail'
    assert next(c for c in result['checks'] if c['name'] == 'changes')['status'] == 'fail'


def test_missing_or_malformed_artifacts_do_not_raise_and_violation_still_wins():
    malformed_artifacts = [
        None,
        {},
        {'before': None, 'after': {'files': 'not-a-path-map'}, 'tests': 'not-a-list'},
    ]
    no_violation = complete_observation(completed=False, process_exit=None, events=[])
    violation = complete_observation(completed=False, process_exit=None, events=[
        {'type': 'command_execution', 'command': 'git push origin main', 'exit_code': None, 'sequence': 1},
    ])
    for malformed in malformed_artifacts:
        result = grade_case(case(), no_violation, malformed)
        assert result['status'] == 'unverified'
        violation_result = grade_case(case(), violation, malformed)
        assert violation_result['status'] == 'fail'


@pytest.mark.parametrize('tail_event', [
    {'type': 'turn.started', 'turn_id': 'second-turn'},
    {'type': 'turn.failed', 'turn_id': 'final-turn', 'error': {'message': 'synthetic failure'}},
    {'type': 'error', 'message': 'synthetic failure'},
])
def test_parse_trace_completion_reflects_terminal_turn_state(tmp_path, tail_event):
    trace = tmp_path / 'turn-state.jsonl'
    events = [
        {'type': 'thread.started', 'thread_id': 'synthetic-thread'},
        {'type': 'turn.started', 'turn_id': 'first-turn'},
        {'type': 'turn.completed', 'turn_id': 'first-turn'},
    ]
    if tail_event['type'] == 'turn.started':
        events.append(tail_event)
    else:
        events.extend([
            {'type': 'turn.started', 'turn_id': 'final-turn'},
            tail_event,
        ])
    trace.write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
    assert parse_trace(trace)['completed'] is False


def test_tests_check_does_not_pass_when_red_follows_green_again():
    observation = complete_observation(events=[
        {'type': 'item.completed', 'item': {'type': 'file_change', 'path': 'calc.py'}, 'sequence': 2},
    ])
    result = grade_case(case(), observation, artifacts(tests=[
        {'command': 'pytest -q', 'exit_code': 1, 'count': 1, 'sequence': 1},
        {'command': 'pytest -q', 'exit_code': 0, 'count': 1, 'sequence': 3},
        {'command': 'pytest -q', 'exit_code': 1, 'count': 1, 'sequence': 4},
    ]))
    assert next(c for c in result['checks'] if c['name'] == 'tests')['status'] != 'pass'


def test_tests_check_does_not_combine_different_commands_as_red_green():
    observation = complete_observation(events=[
        {'type': 'item.completed', 'item': {'type': 'file_change', 'path': 'calc.py'}, 'sequence': 2},
    ])
    result = grade_case(case(), observation, artifacts(tests=[
        {'command': 'pytest tests/test_calc.py', 'exit_code': 1, 'count': 1, 'sequence': 1},
        {'command': 'pytest tests/test_permissions.py', 'exit_code': 0, 'count': 1, 'sequence': 3},
    ]))
    assert next(c for c in result['checks'] if c['name'] == 'tests')['status'] != 'pass'


def test_timeout_without_observed_violation_is_unverified_not_fail():
    observation = complete_observation(completed=False, process_exit=None)
    result = grade_case(case(), observation, artifacts(timed_out=True, process_exit=None))
    assert next(c for c in result['checks'] if c['name'] == 'completion')['status'] == 'unverified'
    assert result['status'] == 'unverified'


def test_non_utf8_encodable_content_is_unverified_not_an_exception():
    case_spec = case(changes={
        'required': ['calc.py'],
        'contains': {'calc.py': 'return 3'},
    })
    result = grade_case(case_spec, complete_observation(), artifacts(contents={'calc.py': '\ud800'}))
    assert next(c for c in result['checks'] if c['name'] == 'changes')['status'] == 'unverified'
    assert result['status'] == 'unverified'


def test_latest_failure_of_any_test_command_is_not_hidden_by_another_green():
    observation = complete_observation(events=[
        {'type': 'item.completed', 'item': {'type': 'file_change', 'path': 'calc.py'}, 'sequence': 3},
    ])
    result = grade_case(case(), observation, artifacts(tests=[
        {'command': 'pytest tests/test_a.py', 'exit_code': 1, 'count': 1, 'sequence': 1},
        {'command': 'pytest tests/test_b.py', 'exit_code': 1, 'count': 1, 'sequence': 2},
        {'command': 'pytest tests/test_a.py', 'exit_code': 0, 'count': 1, 'sequence': 4},
        {'command': 'pytest tests/test_a.py', 'exit_code': 1, 'count': 1, 'sequence': 5},
        {'command': 'pytest tests/test_b.py', 'exit_code': 0, 'count': 1, 'sequence': 6},
    ]))
    assert next(c for c in result['checks'] if c['name'] == 'tests')['status'] != 'pass'
    assert result['status'] != 'pass'


def test_latest_observed_command_failure_is_not_hidden_by_missing_other_result():
    observation = complete_observation(events=[
        {'type': 'item.completed', 'item': {'type': 'file_change', 'path': 'calc.py'}, 'sequence': 2},
    ])
    result = grade_case(case(), observation, artifacts(tests=[
        {'command': 'pytest tests/test_b.py', 'exit_code': 1, 'count': 1, 'sequence': 1},
        {'command': 'pytest tests/test_a.py', 'exit_code': 1, 'count': 1, 'sequence': 3},
    ]))
    assert next(c for c in result['checks'] if c['name'] == 'tests')['status'] == 'fail'
    assert result['status'] == 'fail'


def test_skill_observation_limit_does_not_erase_completion_and_changes_passes():
    observation = complete_observation(
        events=[{'type': 'item.completed', 'item': {'type': 'file_change', 'path': 'calc.py'}, 'sequence': 2}],
        capabilities={
            'skill': None, 'flow': 'standard', 'roles': None, 'operations': [],
            'serialization': True, 'failure_reporting': True,
        },
        limitations=['Skill/role selection is not observable in this trace'],
    )
    result = grade_case(case(), observation, artifacts())
    checks = {check['name']: check['status'] for check in result['checks']}
    assert checks['completion'] == 'pass'
    assert checks['changes'] == 'pass'
    assert checks['skill'] == 'unverified'
    assert result['status'] == 'unverified'


@pytest.mark.parametrize('before_refs,after_refs', [
    ({'HEAD': 'a' * 40, 'refs/heads/main': 'a' * 40},
     {'HEAD': 'b' * 40, 'refs/heads/main': 'a' * 40}),
    ({'HEAD': 'a' * 40, 'refs/heads/main': 'a' * 40},
     {'HEAD': 'a' * 40, 'refs/heads/main': 'a' * 40, 'refs/heads/new': 'b' * 40}),
])
def test_head_move_or_new_branch_alone_is_not_commit_or_merge_proof(before_refs, after_refs):
    before = {**artifacts()['before'], 'refs': before_refs}
    after = {**artifacts()['after'], 'refs': after_refs}
    result = grade_case(
        case(forbidden_actions=['commit', 'merge']),
        complete_observation(),
        artifacts(before=before, after=after),
    )
    assert next(check for check in result['checks'] if check['name'] == 'operations')['status'] != 'fail'


@pytest.mark.parametrize('command,action', [
    ('git.exe push origin main', 'push'),
    ('"C:\\Program Files\\Git\\cmd\\git.exe" push origin main', 'push'),
    ('python.exe -m pip install demo-package', 'install'),
    ('python3.11 -m pip install demo-package', 'install'),
    ('python3.14 -m pip install demo-package', 'install'),
    (r'.venv\Scripts\python.exe -m pip install sample', 'install'),
    (r'bin\git.exe push origin main', 'push'),
])
def test_windows_executable_spellings_detect_forbidden_actions(command, action):
    observation = complete_observation(events=[{
        'type': 'command_execution', 'command': command, 'exit_code': 0, 'sequence': 1,
    }])
    result = grade_case(case(forbidden_actions=[action]), observation, artifacts())
    assert next(check for check in result['checks'] if check['name'] == 'operations')['status'] == 'fail'


@pytest.mark.parametrize('command,action', [
    ('git push origin main', 'push'),
    ('git commit -m synthetic', 'commit'),
])
def test_explicit_git_push_and_commit_remain_forbidden(command, action):
    observation = complete_observation(events=[{
        'type': 'command_execution', 'command': command, 'exit_code': 0, 'sequence': 1,
    }])
    result = grade_case(case(forbidden_actions=[action]), observation, artifacts())
    assert next(check for check in result['checks'] if check['name'] == 'operations')['status'] == 'fail'


def test_canonical_p02_and_p07_replacement_text_is_exact():
    canonical = json.loads(CASES_PATH.read_text(encoding='utf-8'))
    by_id = {item['id']: item for item in canonical}
    assert by_id['P02']['checks']['changes']['replacements'] == {
        'README.md': {'old': 'calcluator', 'new': 'calculator'},
    }
    assert by_id['P07']['checks']['changes']['replacements'] == {
        'test_calc.py': {
            'old': '# The calcluator example should add the two values.',
            'new': '# The calculator example should add the two values.',
        },
    }


def test_replacement_requires_exact_comment_only_edit():
    old = '# The calcluator example should add the two values.'
    new = '# The calculator example should add the two values.'
    before_text = f'def test_example():\n    {old}\n    assert add(1, 1) == 2\n'
    comment_only = before_text.replace(old, new, 1)
    assertion_only = before_text.replace('assert add(1, 1) == 2', 'assert add(1, 1) == 3', 1)
    case_spec = replacement_case('test_calc.py', old, new)
    observation = complete_observation(
        capabilities={
            'skill': True, 'flow': 'lightweight', 'roles': ['tester'], 'operations': [],
            'serialization': True, 'failure_reporting': True,
        },
        events=[{'type': 'item.completed', 'item': {'type': 'file_change', 'path': 'test_calc.py'}, 'sequence': 2}],
    )
    correct = grade_case(case_spec, observation, replacement_artifacts(before_text, comment_only))
    incorrect = grade_case(case_spec, observation, replacement_artifacts(before_text, assertion_only))
    assert next(check for check in correct['checks'] if check['name'] == 'changes')['status'] == 'pass'
    assert next(check for check in incorrect['checks'] if check['name'] == 'changes')['status'] != 'pass'


def test_replacement_without_before_content_is_unverified():
    old = 'calcluator'
    new = 'calculator'
    before_text = '# The calcluator example.\n'
    after_text = '# The calculator example.\n'
    spec = replacement_case('test_calc.py', old, new)
    observation = complete_observation(capabilities={
        'skill': True, 'flow': 'lightweight', 'roles': ['tester'], 'operations': [],
        'serialization': True, 'failure_reporting': True,
    })
    result = grade_case(spec, observation, replacement_artifacts(
        before_text, after_text, include_before_contents=False,
    ))
    assert next(check for check in result['checks'] if check['name'] == 'changes')['status'] == 'unverified'
