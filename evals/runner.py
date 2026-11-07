"""offline採点と、モデルを起動しないlive評価の事前確認。"""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from typing import Sequence

from harness.paths import assert_safe_target, validate_relative_name
from evals.cases import load_cases
from evals.grade import grade_case, parse_trace


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals/implementing-repository-changes.cases.json"


def _stop_owned_probe(process: subprocess.Popen) -> None:
    # 新しいsession/groupで起動した自分のprobeだけを停止する。
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
        try:
            subprocess.run(
                [str(executable), "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=2, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        process.kill()
    except ProcessLookupError:
        pass


def _capture_probe(args: list[str], *, cwd: Path, env: dict[str, str],
                   timeout_seconds: float) -> tuple[int, str]:
    options = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
    }
    process = subprocess.Popen(
        args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", **options,
    )
    try:
        stdout, _stderr = process.communicate(timeout=timeout_seconds)
    except BaseException:
        cleanup_deadline = time.monotonic() + 5
        _stop_owned_probe(process)
        # killの送信と、終了を回収したことは別に確認する。
        process.communicate(timeout=max(0.001, cleanup_deadline - time.monotonic()))
        raise
    if type(process.returncode) is not int or not isinstance(stdout, str):
        raise ValueError("probeの終了状態を確認できません")
    return process.returncode, stdout


def probe_cli(codex_bin: Path, *, timeout_seconds: float = 10) -> dict:
    """信頼するCLIのversion/helpだけを一時homeで確認する。"""
    result = {
        "status": "unverified", "supported": False, "version": None,
        "limitations": [
            "検証済みのlive adapterがないため、モデルは起動しません",
            "Skill/role/全操作記録の観測契約は未確認です",
            "隔離認証とMCP/apps/plugins等の遮断を証明できません",
            "必要依存と方針の実読込は未確認です",
        ],
    }
    try:
        if (type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 600):
            raise ValueError("probeの時間上限が不正です")
        deadline = time.monotonic() + min(timeout_seconds, 10)

        def remaining() -> float:
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise subprocess.TimeoutExpired("preflight", timeout_seconds)
            return seconds

        binary = str(Path(codex_bin).expanduser().absolute())
        with tempfile.TemporaryDirectory(prefix="skill-eval-probe-") as temporary:
            root = Path(temporary).resolve()
            for name in ("home", "codex", "config", "data", "cache", "tmp"):
                (root / name).mkdir(mode=0o700)
            child_env = {key: value for key, value in os.environ.items() if key in {
                "PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC",
            }}
            child_env.update({
                "HOME": str(root / "home"), "USERPROFILE": str(root / "home"),
                "CODEX_HOME": str(root / "codex"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "APPDATA": str(root / "config"), "LOCALAPPDATA": str(root / "data"),
                "TMPDIR": str(root / "tmp"), "TMP": str(root / "tmp"), "TEMP": str(root / "tmp"),
                "LANG": "C.UTF-8", "NO_COLOR": "1",
            })
            code, banner = _capture_probe([binary, "--version"], cwd=root, env=child_env, timeout_seconds=remaining())
            version = re.fullmatch(r"codex(?:-cli)? ([A-Za-z0-9.+-]{1,80})\s*", banner)
            if code != 0 or version is None:
                result["limitations"].append("CLI versionの正常な応答を確認できません")
                return result
            result["version"] = version.group(1)
            code, help_text = _capture_probe([binary, "exec", "--help"], cwd=root, env=child_env, timeout_seconds=remaining())
            required = ("--json", "--ephemeral", "--ignore-user-config", "--sandbox")
            if code != 0 or not all(flag in help_text for flag in required):
                result["limitations"].append("必要なCLI引数の対応を確認できません")
    except subprocess.TimeoutExpired:
        result["limitations"].append("version/helpの確認がtimeoutしました")
    except (OSError, ValueError):
        result["limitations"].append("CLIの起動前確認を完了できません")
    return result


def run_case(case: dict, *, codex_bin: Path, run_root: Path,
             timeout_seconds: int = 180) -> dict:
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise ValueError("timeout-secondsは1〜600を指定してください")
    preflight = probe_cli(codex_bin, timeout_seconds=timeout_seconds)
    # adapterの実装と検証が済むまで、helpの結果や外部フラグで実行を開放しない。
    return {
        "case_id": case.get("id"), "status": "unverified", "checks": [],
        "execution_started": False, "preflight": preflight,
        "limitations": list(preflight.get("limitations", [])) + [
            "preflightのみです。fixture・方針をモデルへ投入していません",
        ],
    }


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def _parser() -> Parser:
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "grade", "run"):
        command = commands.add_parser(name)
        command.add_argument("--cases", type=Path, default=CASES)
        if name != "validate":
            command.add_argument("--case", required=True)
            command.add_argument("--output", type=Path)
        if name == "grade":
            command.add_argument("--trace", type=Path, required=True)
            command.add_argument("--artifacts", type=Path, required=True)
        elif name == "run":
            command.add_argument("--live", action="store_true", required=True)
            command.add_argument("--codex-bin", type=Path, required=True)
            command.add_argument("--timeout-seconds", type=int, default=180)
    return parser


def _save_report(output: Path, report: dict) -> None:
    if output.is_absolute() or len(output.parts) != 2 or output.parts[0] != ".eval-runs":
        raise ValueError("outputは .eval-runs/NAME を指定してください")
    validate_relative_name(output.parts[1])
    destination = ROOT / output
    assert_safe_target(ROOT, destination)
    if destination.exists():
        raise ValueError("outputの既存directoryは上書きしません")
    destination.parent.mkdir(mode=0o700, exist_ok=True)
    destination.mkdir(mode=0o700)
    target = destination / "result.json"
    assert_safe_target(ROOT, target)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=True, indent=2) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        cases = load_cases(args.cases)
        if args.command == "validate":
            report = {"status": "pass", "cases": len(cases)}
        else:
            case = next((case for case in cases if case["id"] == args.case), None)
            if case is None:
                raise ValueError("指定したcase IDはありません")
            if args.command == "grade":
                observation = parse_trace(args.trace)
                artifacts = json.loads(args.artifacts.read_text(encoding="utf-8"))
                report = grade_case(case, observation, artifacts)
            else:
                with tempfile.TemporaryDirectory(prefix="skill-eval-run-") as temporary:
                    report = run_case(case, codex_bin=args.codex_bin, run_root=Path(temporary),
                                      timeout_seconds=args.timeout_seconds)
            if args.output is not None:
                _save_report(args.output, report)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return {"pass": 0, "fail": 1, "unverified": 2}[report["status"]]
    except (OSError, ValueError, UnicodeError) as error:
        print(json.dumps({"status": "unverified", "limitations": [str(error)]}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
