"""offline CLIのopt-in境界とlive起動前の安全停止契約。"""

import os
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import runner


def fake_process_factory(calls, *, timeout=False, killed=None, communicates=None):
    """実プロセスを作らずPopen+communicate境界だけを模擬する。"""
    killed = [] if killed is None else killed
    communicates = [] if communicates is None else communicates

    def fake_popen(args, *, cwd, env, **kwargs):
        normalized = list(map(str, args))
        calls.append({'args': normalized, 'cwd': Path(cwd), 'env': dict(env), 'kwargs': kwargs})

        class FakeProcess:
            pid = 4242 + len(calls) - 1
            returncode = None
            args = normalized

            def communicate(self, timeout=None):
                communicates.append((self.pid, timeout))
                if timeout and timeout and not any(pid == self.pid for pid, _ in communicates[:-1]) and timeout_enabled:
                    raise runner.subprocess.TimeoutExpired(normalized, timeout)
                self.returncode = 0
                output = b'codex 0.156.1\n' if '--version' in normalized else b'offline help\n'
                return (output.decode('utf-8'), '')

            def kill(self):
                killed.append(self.pid)

            def wait(self, timeout=None):
                return -9

        return FakeProcess()

    timeout_enabled = timeout
    return fake_popen, killed, communicates


def test_validate_does_not_launch_model(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('validate must not launch a model or external command')

    monkeypatch.setattr(runner.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(runner.subprocess, 'run', forbidden)
    assert runner.main(['validate']) == 0


def test_live_requires_single_case(tmp_path, monkeypatch):
    binary = tmp_path / 'codex'
    launched = []
    monkeypatch.setattr(runner, 'run_case', lambda *args, **kwargs: launched.append(True))
    assert runner.main(['run', '--live', '--codex-bin', str(binary)]) == 2
    assert launched == []


def test_unproven_isolation_never_launches_candidate_command(tmp_path, monkeypatch):
    marker = tmp_path / 'launched'
    binary = tmp_path / 'codex'
    # help/version probing may run, but an evaluation turn must not start unless
    # every required isolation/observation condition is positively established.
    monkeypatch.setattr(runner, 'probe_cli', lambda _binary, **_options: {
        'status': 'unverified', 'supported': False,
        'limitations': ['MCP/app隔離とSkill/role読込契約を証明できない'],
    })
    result = runner.run_case({'id': 'P01'}, codex_bin=binary, run_root=tmp_path / 'run')
    assert result['status'] == 'unverified'
    assert not marker.exists()


def test_probe_result_does_not_treat_version_or_help_as_isolation_proof(tmp_path, monkeypatch):
    binary = tmp_path / 'codex'
    binary.touch()
    calls = []
    fake_popen, _, _ = fake_process_factory(calls)
    monkeypatch.setattr(runner.subprocess, 'Popen', fake_popen)
    result = runner.probe_cli(binary)
    assert result['status'] == 'unverified'
    assert result['supported'] is False
    assert result['limitations']
    # Help/version (including an explicit `exec --help`) are safe probes; no
    # prompt or unbounded execution command may be launched by preflight.
    assert calls
    assert all('--version' in call['args'] or '--help' in call['args'] for call in calls)


def test_timeout_value_is_bounded_before_any_launch(tmp_path):
    binary = tmp_path / 'codex'
    with pytest.raises(ValueError):
        runner.run_case({'id': 'P01'}, codex_bin=binary, run_root=tmp_path / 'run', timeout_seconds=601)


def test_child_env_is_not_used_for_host_configuration(monkeypatch, tmp_path):
    # Even when host settings are populated, preflight/blocked evaluation must
    # not copy them into an evaluation run or its artifacts.
    private_home = tmp_path / 'private-home'
    private_codex = tmp_path / 'private-codex'
    monkeypatch.setenv('HOME', str(private_home))
    monkeypatch.setenv('CODEX_HOME', str(private_codex))
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-private-auth')
    private = private_codex
    private.mkdir()
    (private / 'config.toml').write_text('sentinel-private-setting', encoding='utf-8')
    binary = tmp_path / 'codex'
    calls = []
    fake_popen, _, _ = fake_process_factory(calls)
    monkeypatch.setattr(runner.subprocess, 'Popen', fake_popen)
    runner.probe_cli(binary)
    assert calls
    assert all(call['env'].get('HOME') != str(private_home) for call in calls)
    assert all(call['env'].get('CODEX_HOME') != str(private_codex) for call in calls)
    assert all(call['env'].get('OPENAI_API_KEY') != 'synthetic-private-auth' for call in calls)
    run_root = tmp_path / 'run'
    assert (private / 'config.toml').read_text(encoding='utf-8') == 'sentinel-private-setting'
    if run_root.exists():
        files = (path for path in run_root.rglob('*') if path.is_file())
        assert all(b'sentinel-private-setting' not in path.read_bytes() for path in files)


@pytest.mark.parametrize('platform', ['posix', 'nt'])
def test_probe_timeout_returns_unverified_without_attempting_prompt_run(tmp_path, monkeypatch, platform):
    binary = tmp_path / 'codex'
    calls = []
    killed = []
    communicates = []
    fake_popen, _, _ = fake_process_factory(calls, timeout=True, killed=killed, communicates=communicates)
    monkeypatch.setattr(runner.subprocess, 'Popen', fake_popen)
    owned_groups = []
    monkeypatch.setattr(runner, 'os', SimpleNamespace(
        name=platform,
        environ=os.environ,
        killpg=lambda pid, sig: owned_groups.append((pid, sig)),
    ))
    sigkill = object()
    monkeypatch.setattr(runner, 'signal', SimpleNamespace(SIGKILL=sigkill))
    if platform == 'nt':
        monkeypatch.setattr(runner.subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200, raising=False)
        taskkills = []

        def fake_run(args, **kwargs):
            normalized = list(map(str, args))
            taskkills.append((normalized, kwargs))
            return type('Completed', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()

        monkeypatch.setattr(runner.subprocess, 'run', fake_run)
    result = runner.probe_cli(binary)
    assert result['status'] == 'unverified'
    assert result['limitations']
    assert len(calls) == 1
    assert '--version' in calls[0]['args'] or '--help' in calls[0]['args']
    assert all(call['args'] == calls[0]['args'] for call in calls)
    assert killed == [4242]
    assert all(pid == 4242 for pid, _ in communicates)
    assert len(communicates) == 2, 'timeout後にcommunicateで所有プロセスを1回reapする'
    if platform == 'posix':
        assert owned_groups == [(4242, sigkill)]
    else:
        assert calls[0]['kwargs'].get('creationflags') == 0x200
        assert len(taskkills) == 1, 'taskkillを再試行しない'
        args, kwargs = taskkills[0]
        assert Path(args[0]).name.lower() == 'taskkill.exe'
        assert args[1:] == ['/PID', '4242', '/T', '/F']
        assert kwargs['timeout'] == 2


def test_capture_probe_timeout_kills_and_reaps_only_owned_process_tree(tmp_path, monkeypatch):
    calls = []
    killed = []
    communicates = []
    fake_popen, _, _ = fake_process_factory(calls, timeout=True, killed=killed, communicates=communicates)
    monkeypatch.setattr(runner.subprocess, 'Popen', fake_popen)
    owned_groups = []
    taskkills = []
    if os.name == 'nt':
        def fake_run(args, **kwargs):
            taskkills.append(list(map(str, args)))
            return type('Completed', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()

        monkeypatch.setattr(runner.subprocess, 'run', fake_run)
    else:
        def fake_killpg(pid, sig):
            owned_groups.append((pid, sig))

        monkeypatch.setattr(runner.os, 'killpg', fake_killpg)

    with pytest.raises(runner.subprocess.TimeoutExpired):
        runner._capture_probe(
            ['codex', '--version'],
            cwd=tmp_path,
            env={'PATH': os.environ.get('PATH', '')},
            timeout_seconds=1.0,
        )

    assert len(calls) == 1
    assert all(pid == 4242 for pid in killed)
    assert all(pid == 4242 for pid, _ in communicates)
    assert len(communicates) >= 2, 'timeout後にcommunicateで所有プロセスをreapする'
    if os.name == 'nt':
        assert killed == [4242]
        assert calls[0]['kwargs'].get('creationflags', 0) != 0
        assert taskkills and all('/T' in args and '4242' in args for args in taskkills)
    else:
        assert calls[0]['kwargs'].get('start_new_session') is True
        assert owned_groups and all(pid == 4242 for pid, _ in owned_groups)


def test_probe_cli_passes_remaining_budget_after_version_to_help(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(runner.time, 'monotonic', lambda: now[0])
    calls = []

    def fake_capture(args, *, cwd, env, timeout_seconds):
        calls.append((list(map(str, args)), timeout_seconds))
        if '--version' in args:
            now[0] = 4.0
            return 0, 'codex 0.156.1\n'
        return 0, 'offline help --json --ephemeral --ignore-user-config --sandbox\n'

    monkeypatch.setattr(runner, '_capture_probe', fake_capture)
    result = runner.probe_cli(tmp_path / 'codex', timeout_seconds=10.0)
    assert result['status'] == 'unverified'
    assert len(calls) == 2
    assert '--version' in calls[0][0]
    assert '--help' in calls[1][0]
    assert calls[0][1] == pytest.approx(10.0)
    assert calls[1][1] == pytest.approx(6.0)


def test_probe_cli_does_not_start_help_after_budget_expires(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(runner.time, 'monotonic', lambda: now[0])
    calls = []

    def fake_capture(args, *, cwd, env, timeout_seconds):
        calls.append((list(map(str, args)), timeout_seconds))
        now[0] = 10.1
        return 0, 'codex 0.156.1\n'

    monkeypatch.setattr(runner, '_capture_probe', fake_capture)
    result = runner.probe_cli(tmp_path / 'codex', timeout_seconds=10.0)
    assert result['status'] == 'unverified'
    assert len(calls) == 1
    assert '--version' in calls[0][0]


def test_run_case_passes_timeout_budget_into_probe(tmp_path, monkeypatch):
    seen = []

    def fake_probe(_binary, *, timeout_seconds):
        seen.append(timeout_seconds)
        return {'status': 'unverified', 'supported': False, 'limitations': ['preflight only']}

    monkeypatch.setattr(runner, 'probe_cli', fake_probe)
    result = runner.run_case(
        {'id': 'P01'}, codex_bin=tmp_path / 'codex', run_root=tmp_path / 'run', timeout_seconds=37,
    )
    assert result['status'] == 'unverified'
    assert seen == [37]
