from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .content import commit_sha, validate_sources
from .diagnostics import inspect_runtime
from .paths import Problem, assert_safe_target, resolve_layout
from .sync import apply_plan, atomic_write, build_plan, load_state, verify_deployment


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Arguments can contain personal paths or values; never echo them.
        raise ValueError('invalid-arguments')


def _problem(problem: Problem) -> dict:
    return {'code': problem.code, 'target_id': problem.target_id, 'message': problem.message}


def _emit(report: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return
    for operation in report.get('operations', []):
        print(operation['action'] + ' ' + operation['target_id'])
    for key in ('changed_ids', 'adopted_ids'):
        for target in report.get(key, []):
            print(key + ': ' + target)
    for key in ('problems', 'notes'):
        for problem in report.get(key, []):
            print(problem['code'] + ' ' + problem['target_id'] + ': ' + problem['message'])
    if 'source_commit' in report:
        print('source_commit: ' + report['source_commit'])
    if report.get('source_dirty'):
        print('dirty-source: commit source changes before apply')
    if not report.get('problems'):
        print('status: ' + report.get('status', 'checked'))


def _parser() -> Parser:
    parser = Parser(description='Synchronize only shared Codex harness configuration.')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('validate', 'plan', 'apply', 'verify', 'doctor'):
        command = commands.add_parser(name)
        command.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
        command.add_argument('--home', type=Path, default=Path.home())
        command.add_argument('--codex-home', type=Path)
        command.add_argument('--local-config', type=Path)
        if name in {'plan', 'verify'}:
            command.add_argument('--json', action='store_true')
        if name in {'plan', 'apply'}:
            command.add_argument('--adopt-from')
        if name == 'doctor':
            command.add_argument('--record', action='store_true')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    as_json = False
    try:
        args = _parser().parse_args(argv)
        as_json = getattr(args, 'json', False)
        layout = resolve_layout(args.repo, home=args.home, codex_home=args.codex_home, env=os.environ)
        if args.local_config is not None:
            layout = replace(layout, local_config=args.local_config.expanduser().absolute())
        if args.command == 'validate':
            problems = validate_sources(layout.repo)
            _emit({'problems': [_problem(p) for p in problems], 'status': 'valid'}, False)
            return 2 if problems else 0
        if args.command == 'doctor':
            checks = inspect_runtime(layout)
            code = 2 if any(c.status == 'missing' for c in checks) else (
                1 if any(c.status == 'warn' for c in checks) else 0)
            report = {'schema_version': 1, 'source_commit': commit_sha(layout.repo),
                      'applied_source_commit': load_state(layout)[0].get('source_commit'),
                      'checked_at': datetime.now(timezone.utc).isoformat(),
                      'checks': [{'name': c.name, 'status': c.status, 'evidence_kind': c.evidence_kind,
                                  'message': c.message} for c in checks]}
            if args.record:
                target = layout.state_dir / 'diagnostics.json'
                assert_safe_target(layout.codex_home, target)
                if target.is_relative_to(layout.home):
                    assert_safe_target(layout.home, target)
                before = target.read_bytes() if target.exists() else None
                raw = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode()
                atomic_write(layout.codex_home, target, raw, before)
            for check in checks:
                print(check.status + ' ' + check.name + ' [' + check.evidence_kind + ']: ' + check.message)
            if args.record:
                print('diagnostics: recorded')
            return code
        if args.command == 'verify':
            problems = verify_deployment(layout)
            mismatch_codes = {'not-recorded', 'commit-mismatch', 'dirty-source', 'retired',
                              'mismatch', 'orphaned-override', 'conflict'}
            code = 2 if any(p.code not in mismatch_codes for p in problems) else (1 if problems else 0)
            _emit({'problems': [_problem(p) for p in problems], 'status': 'verified'}, as_json)
            return code
        plan = build_plan(layout, adopt_from=args.adopt_from)
        if args.command == 'apply':
            result = apply_plan(layout, plan)
            _emit({'changed_ids': result.changed_ids, 'adopted_ids': result.adopted_ids,
                   'problems': [_problem(p) for p in result.problems],
                   'notes': [_problem(p) for p in result.notes], 'status': 'applied'}, False)
            return 2 if result.problems else 0
        different = (not plan.state or plan.state.get('source_commit') != plan.source_commit
                     or any(op.action != 'unchanged' for op in plan.operations)
                     or any(p.code == 'orphaned-override' for p in plan.notes))
        _emit({'source_commit': plan.source_commit, 'source_dirty': plan.source_dirty,
               'operations': [{'target_id': op.target_id, 'action': op.action} for op in plan.operations],
               'problems': [_problem(p) for p in plan.problems],
               'notes': [_problem(p) for p in plan.notes],
               'status': 'differences' if different else 'aligned'}, as_json)
        return 2 if plan.problems else (1 if different else 0)
    except (OSError, ValueError, TypeError):
        _emit({'problems': [{'code': 'command-failed', 'target_id': 'command',
                            'message': 'Command failed; check arguments, permissions and configuration syntax.'}]}, as_json)
        return 2


if __name__ == '__main__':
    sys.exit(main())
