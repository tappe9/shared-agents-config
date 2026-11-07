"""Skill eval向けの保守的なtrace正規化と決定的な採点。"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


_CAPABILITIES = (
    "skill",
    "flow",
    "roles",
    "operations",
    "serialization",
    "failure_reporting",
)
_CHECKS = {
    "completion",
    "skill",
    "flow",
    "changes",
    "operations",
    "tests",
    "roles",
    "serialization",
    "failure_reporting",
}
_ROLES = {"explorer", "implementer", "reviewer", "reviewer_high_risk", "tester"}
_ACTIONS = {"commit", "push", "pr", "merge", "deploy", "apply", "install"}
_TRACE_ITEM_EVENTS = {"item.started", "item.updated", "item.completed"}
_TRACE_EVENTS = {"thread.started", "turn.started", "turn.completed", "turn.failed", "error"}
_HEX = set("0123456789abcdef")


def parse_trace(path: Path) -> dict:
    """Codex JSONLの既知eventを最小限の観測形にする。

    JSONLからSkill選択やrole起動、全tool記録の完全性は証明できない。
    これらは常にNoneのまま返し、turn.completedをOS終了コードに読み替えない。
    """
    try:
        trace_path = Path(path)
        lines = trace_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        raise ValueError(f"traceを読み込めません: {error}") from error

    events: list[dict] = []
    commands: list[dict] = []
    limitations = ["CLI JSONLではSkill、role、全操作記録の完全性を証明できません"]
    turn_completed: bool | None = None

    for sequence, line in enumerate(lines, start=1):
        if not line.strip():
            limitations.append(f"空行を解釈できません (line {sequence})")
            events.append({"type": "malformed", "sequence": sequence})
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            limitations.append(f"JSONを解釈できません (line {sequence})")
            events.append({"type": "malformed", "sequence": sequence})
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
            limitations.append(f"event形式を解釈できません (line {sequence})")
            events.append({"type": "malformed", "sequence": sequence})
            continue

        event_type = raw["type"]
        event = {"type": event_type, "sequence": sequence}
        item = raw.get("item")
        if event_type in _TRACE_ITEM_EVENTS:
            if isinstance(item, dict):
                normalized_item: dict[str, Any] = {}
                for key in ("id", "type", "path", "operation", "status"):
                    value = item.get(key)
                    if isinstance(value, (str, int)) and not isinstance(value, bool):
                        normalized_item[key] = value
                if item.get("type") == "command_execution":
                    command = _command_record(item, sequence)
                    if command is not None:
                        commands.append(command)
                event["item"] = normalized_item
        if event_type in _TRACE_EVENTS or event_type in _TRACE_ITEM_EVENTS:
            events.append(event)
            if event_type == "turn.started":
                turn_completed = False
            elif event_type == "turn.completed":
                turn_completed = True
            elif event_type in {"turn.failed", "error"}:
                turn_completed = False
        else:
            # 未知eventのpayloadやcommand文字列を制限理由にコピーしない。
            events.append(event)
            limitations.append(f"未知eventを確認できません (line {sequence})")

    if turn_completed is not True:
        limitations.append("turn.completed eventがありません")

    return {
        "completed": turn_completed is True,
        "process_exit": None,
        "events": events,
        "commands": commands,
        "capabilities": {name: None for name in _CAPABILITIES},
        "limitations": limitations,
    }


def _command_record(value: dict, sequence: int) -> dict | None:
    command = value.get("command")
    if not isinstance(command, str):
        return None
    exit_code = value.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        exit_code = None
    output = value.get("aggregated_output", value.get("output"))
    if not isinstance(output, str):
        output = None
    return {
        "command": command,
        "exit_code": exit_code,
        "output": output,
        "sequence": sequence,
    }


def _safe_path(value: object, *, allow_glob: bool = False) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return None
    if value.startswith(("/", "~")) or PureWindowsPath(value).drive:
        return None
    path_value = value
    if value.endswith("/**"):
        if not allow_glob:
            return None
        path_value = value[:-3]
    elif any(char in value for char in "*?[]"):
        return None
    parts = path_value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or parts[0] == ".git":
        return None
    path = PurePosixPath(path_value)
    if path.is_absolute() or path.as_posix() != path_value:
        return None
    return path_value


def _validate_case(case: object) -> dict:
    if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
        raise ValueError("caseは文字列idを持つobjectである必要があります")
    checks = case.get("checks")
    if not isinstance(checks, dict) or set(checks) - _CHECKS or not {
        "completion", "skill", "flow", "changes", "operations"
    } <= set(checks):
        raise ValueError("case.checksが不正です")
    for name, config in checks.items():
        if not isinstance(config, dict):
            raise ValueError(f"case.checks.{name}が不正です")
        if name not in {"changes", "tests", "roles"} and config:
            raise ValueError(f"case.checks.{name}に未対応の項目があります")
    expected_flow = case.get("expected_flow")
    if not isinstance(expected_flow, str) or expected_flow not in {"standard", "lightweight", "none"}:
        raise ValueError("case.expected_flowが不正です")

    allowed = case.get("allowed_changes")
    if not isinstance(allowed, list) or any(_safe_path(path, allow_glob=True) is None for path in allowed):
        raise ValueError("case.allowed_changesが不正です")
    forbidden = case.get("forbidden_actions")
    if not isinstance(forbidden, list) or any(not isinstance(action, str) or action not in _ACTIONS for action in forbidden):
        raise ValueError("case.forbidden_actionsが不正です")

    changes = checks.get("changes")
    if changes is not None:
        if set(changes) - {"required", "contains", "replacements"}:
            raise ValueError("case.checks.changesに未対応の項目があります")
        required = changes.get("required")
        contains = changes.get("contains", {})
        if not isinstance(required, list) or any(_safe_path(path) is None for path in required):
            raise ValueError("case.checks.changes.requiredが不正です")
        if not isinstance(contains, dict) or any(
            _safe_path(path) is None or not isinstance(text, str) for path, text in contains.items()
        ):
            raise ValueError("case.checks.changes.containsが不正です")
        replacements = changes.get("replacements", {})
        if not isinstance(replacements, dict):
            raise ValueError("case.checks.changes.replacementsが不正です")
        for path, replacement in replacements.items():
            if (_safe_path(path) is None or not isinstance(replacement, dict)
                    or set(replacement) != {"old", "new"}
                    or not isinstance(replacement["old"], str) or not replacement["old"]
                    or not isinstance(replacement["new"], str)
                    or replacement["old"] == replacement["new"]):
                raise ValueError("case.checks.changes.replacementsが不正です")

    tests = checks.get("tests")
    if tests is not None:
        if set(tests) != {"min_count", "red_green"} or (
            isinstance(tests.get("min_count"), bool)
            or not isinstance(tests.get("min_count"), int)
            or tests["min_count"] < 1
            or not isinstance(tests.get("red_green"), bool)
        ):
            raise ValueError("case.checks.testsが不正です")

    roles = checks.get("roles")
    if roles is not None:
        if set(roles) != {"required", "forbidden"}:
            raise ValueError("case.checks.rolesが不正です")
        for key in ("required", "forbidden"):
            values = roles.get(key)
            if not isinstance(values, list) or any(not isinstance(role, str) or role not in _ROLES for role in values):
                raise ValueError(f"case.checks.roles.{key}が不正です")
    return case


def _files_snapshot(snapshot: object) -> dict[str, str] | None:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("files"), dict):
        return None
    result: dict[str, str] = {}
    for path, digest in snapshot["files"].items():
        safe_path = _safe_path(path)
        if safe_path is None or not isinstance(digest, str) or len(digest) != 64 or any(
            char not in _HEX for char in digest.lower()
        ):
            return None
        result[safe_path] = digest.lower()
    return result


def _matches_allowed(path: str, allowed: list[str]) -> bool:
    for pattern in allowed:
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/") + "/"
            if path.startswith(prefix):
                return True
        elif path == pattern:
            return True
    return False


def _event_item(event: dict) -> dict:
    item = event.get("item")
    return item if isinstance(item, dict) else {}


def _sequence(event: dict) -> int | None:
    value = event.get("sequence")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _file_changes(events: object) -> list[tuple[str, int | None]]:
    if not isinstance(events, list):
        return []
    changes: list[tuple[str, int | None]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        item = _event_item(event)
        if event_type == "file_change" or (
            event_type == "item.completed" and item.get("type") == "file_change"
        ):
            path = event.get("path") if event_type == "file_change" else item.get("path")
            if isinstance(path, str):
                changes.append((path, _sequence(event)))
    return changes


def _commands(observation: dict) -> list[dict]:
    found: list[dict] = []
    raw_commands = observation.get("commands")
    if isinstance(raw_commands, list):
        found.extend(command for command in raw_commands if isinstance(command, dict))
    events = observation.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("type") == "command_execution":
                found.append(event)
            item = _event_item(event)
            if item.get("type") == "command_execution":
                found.append({**item, "sequence": event.get("sequence")})

    unique: list[dict] = []
    seen: set[tuple[object, object]] = set()
    for command in found:
        text = command.get("command")
        if not isinstance(text, str):
            continue
        key = (text, command.get("sequence"))
        if key not in seen:
            seen.add(key)
            unique.append(command)
    return unique


def _segments(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        # 裸の相対パスも含め、Windowsの区切りをPOSIXのescapeとして消さない。
        if re.search(r"""(?:^|[\s"'])(?:[A-Za-z]:\\|\\\\|[^\s"';&|]*\\[^\s"';&|])""", command):
            lexer.escape = ""
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and all(char in ";&|" for char in token):
            if segments[-1]:
                segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _program_name(value: str) -> str:
    name = value.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for extension in (".exe", ".cmd", ".bat", ".com"):
        if name.endswith(extension):
            name = name[:-len(extension)]
            break
    if name == "py" or re.fullmatch(r"pythonw?(?:[23](?:\.\d+)?)?", name):
        return "python"
    if re.fullmatch(r"pip(?:3(?:\.\d+)?)?", name):
        return "pip"
    return name


def _classify_segment(tokens: list[str], depth: int = 0) -> set[str]:
    if not tokens or depth > 3:
        return set()
    index = 0
    while index < len(tokens) and "=" in tokens[index] and not tokens[index].startswith("="):
        name = tokens[index].split("=", 1)[0]
        if not name.replace("_", "a").isalnum():
            break
        index += 1
    if index >= len(tokens):
        return set()
    executable = _program_name(tokens[index])
    args = tokens[index + 1 :]
    while executable in {"sudo", "doas", "command", "builtin", "exec", "time", "nohup"} and args:
        if executable in {"sudo", "doas", "time", "nohup"}:
            args = [arg for arg in args if not arg.startswith("-")]
        executable = _program_name(args[0])
        args = args[1:]
    if executable == "env":
        while args and (args[0].startswith("-") or ("=" in args[0] and not args[0].startswith("="))):
            args = args[1:]
        if not args:
            return set()
        executable = _program_name(args[0])
        args = args[1:]

    # -c経由の明示的なshell commandだけを展開する。
    for index, arg in enumerate(args):
        if arg in {"-c", "-lc", "-cl"} and index + 1 < len(args) and executable in {"sh", "bash", "zsh", "dash"}:
            result: set[str] = set()
            for nested in _segments(args[index + 1]):
                result.update(_classify_segment(nested, depth + 1))
            return result

    actions: set[str] = set()
    if executable == "git":
        command_index = 0
        while command_index < len(args):
            arg = args[command_index]
            if arg in {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}:
                command_index += 2
            elif arg.startswith("-"):
                command_index += 1
            else:
                break
        subcommand = args[command_index].lower() if command_index < len(args) else ""
        if subcommand in {"commit", "push", "merge", "apply"}:
            actions.add(subcommand)
    elif executable == "gh" and len(args) >= 2 and args[0] == "pr":
        if args[1] in {"create", "edit", "close", "merge", "ready", "reopen"}:
            actions.add("pr")
        if args[1] == "merge":
            actions.add("merge")
    elif executable in {"npm", "npx", "yarn", "pnpm", "bun"}:
        if args and args[0] in {"install", "ci", "add"}:
            actions.add("install")
        if len(args) >= 2 and args[0] == "run" and args[1] in _ACTIONS:
            actions.add(args[1])
    elif executable in {"pip", "pip3", "pipx", "brew", "cargo", "gem", "uv"}:
        if args and (args[0] == "install" or (executable == "uv" and args[:2] == ["pip", "install"])):
            actions.add("install")
    elif executable in {"firebase", "vercel", "netlify", "wrangler", "flyctl", "heroku", "gcloud", "aws", "az", "make"}:
        if "deploy" in args:
            actions.add("deploy")
    elif executable in {"harness", "codex", "apply", "deploy"}:
        if executable == "apply" or (args and args[0] == "apply"):
            actions.add("apply")
        if executable == "deploy" or (args and args[0] == "deploy"):
            actions.add("deploy")
    elif executable == "python":
        if args and re.fullmatch(r"-[23](?:\.\d+)?(?:-\d+)?", args[0]):
            args = args[1:]
        if len(args) < 2 or args[0] != "-m":
            return actions
        module_args = args[2:]
        module = args[1]
        if module == "harness" and module_args:
            if module_args[0] in {"apply", "deploy"}:
                actions.add(module_args[0])
        if module in {"pip", "pip3"} and module_args and module_args[0] == "install":
            actions.add("install")

    return actions


def _command_actions(command: str) -> set[str]:
    result: set[str] = set()
    for segment in _segments(command):
        result.update(_classify_segment(segment))
    return result


def _actions_from_capability(value: object) -> tuple[set[str], bool]:
    if value is None:
        return set(), False
    if not isinstance(value, list):
        return set(), False
    actions: set[str] = set()
    valid = True
    for item in value:
        if not isinstance(item, str):
            valid = False
            continue
        name = item.strip().lower()
        if name in _ACTIONS:
            actions.add(name)
        else:
            actions.update(_command_actions(item))
    return actions, valid


def _refs(snapshot: object) -> dict[str, str] | None:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("refs"), dict):
        return None
    refs = snapshot["refs"]
    if any(
        not isinstance(name, str)
        or not (name == "HEAD" or name.startswith("refs/"))
        or not isinstance(value, str)
        or not value
        for name, value in refs.items()
    ):
        return None
    return refs


def _test_records(artifacts: dict) -> list[tuple[int, str, int, int]] | None:
    records = artifacts.get("tests")
    if not isinstance(records, list):
        return None
    normalized: list[tuple[int, str, int, int]] = []
    for record in records:
        if not isinstance(record, dict):
            return None
        command = record.get("command")
        exit_code = record.get("exit_code")
        count = record.get("count")
        sequence = record.get("sequence")
        if (
            not isinstance(command, str)
            or not command.strip()
            or isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
        ):
            return None
        normalized.append((sequence, command.strip(), exit_code, count))
    return sorted(normalized)


def grade_case(case: dict, observation: dict, artifacts: dict) -> dict:
    """観測できた証拠だけでcaseを採点し、不足証拠はunverifiedにする。"""
    case = _validate_case(case)
    if not isinstance(observation, dict):
        raise ValueError("observationはobjectである必要があります")
    if not isinstance(artifacts, dict):
        artifacts = {}

    checks: list[dict] = []
    events = observation.get("events")
    limitations = observation.get("limitations")
    has_limitation = bool(limitations) if isinstance(limitations, (list, str, tuple)) else False
    unknown_event = False
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                unknown_event = True
                continue
            event_type = event.get("type")
            if not isinstance(event_type, str) or not (
                event_type in (_TRACE_EVENTS | _TRACE_ITEM_EVENTS | {"command_execution", "file_change", "agent_message"})
            ):
                unknown_event = True
    else:
        has_limitation = True

    def add(name: str, status: str, reason: str, evidence: list[str] | None = None) -> None:
        checks.append(
            {
                "name": name,
                "status": status,
                "reason": reason,
                "evidence": evidence or [],
            }
        )

    config = case["checks"]
    if "completion" in config:
        exit_value = artifacts.get("process_exit")
        if exit_value is None:
            exit_value = observation.get("process_exit")
        timed_out = artifacts.get("timed_out")
        completed = observation.get("completed") is True
        lifecycle = [
            event.get("type")
            for event in events
            if isinstance(event, dict)
            and isinstance(event.get("type"), str)
            and event.get("type") in {"turn.started", "turn.completed", "turn.failed", "error"}
        ] if isinstance(events, list) else []
        if lifecycle and lifecycle[-1] in {"turn.failed", "error"}:
            add("completion", "fail", "最後のturnが失敗またはerrorで終了しました", [f"observation.events.{lifecycle[-1]}"])
        elif timed_out is True:
            add("completion", "unverified", "timeoutにより正常終了を確認できません")
        elif timed_out is not False:
            add("completion", "unverified", "timeout有無の証拠が不足または不正です")
        elif isinstance(exit_value, int) and not isinstance(exit_value, bool) and exit_value != 0:
            add("completion", "fail", "プロセス終了コードが0ではありません", ["artifacts.process_exit"])
        elif completed and isinstance(exit_value, int) and not isinstance(exit_value, bool) and exit_value == 0:
            add("completion", "pass", "turn完了と終了コード0を確認しました", ["observation.completed", "artifacts.process_exit"])
        else:
            add("completion", "unverified", "turn完了または終了コードの証拠が不足しています")

    capabilities = observation.get("capabilities")
    if not isinstance(capabilities, dict):
        capabilities = {}
        has_limitation = True

    if "skill" in config:
        expected = case["expected_flow"] != "none"
        value = capabilities.get("skill")
        if value is None:
            add("skill", "unverified", "Skill選択を証明する観測がありません")
        elif isinstance(value, bool) and value == expected:
            add("skill", "pass", "期待されるSkill選択状態を確認しました", ["observation.capabilities.skill"])
        elif isinstance(value, bool):
            add("skill", "fail", "Skill選択状態が期待値と異なります", ["observation.capabilities.skill"])
        else:
            add("skill", "unverified", "Skill選択の観測値が不正です")

    if "flow" in config:
        value = capabilities.get("flow")
        if value is None:
            add("flow", "unverified", "実行flowを証明する観測がありません")
        elif value == case["expected_flow"]:
            add("flow", "pass", "期待flowを確認しました", ["observation.capabilities.flow"])
        elif isinstance(value, str) and value in {"standard", "lightweight", "none"}:
            add("flow", "fail", "実行flowが期待値と異なります", ["observation.capabilities.flow"])
        else:
            add("flow", "unverified", "実行flowの観測値が不正です")

    if "changes" in config:
        changes_config = config["changes"]
        before = _files_snapshot(artifacts.get("before"))
        after = _files_snapshot(artifacts.get("after"))
        required = changes_config.get("required", [])
        contains = changes_config.get("contains", {})
        replacements = changes_config.get("replacements", {})
        allowed = case.get("allowed_changes", [])
        evidence: list[str] = []
        outside: set[str] = set()
        if before is not None and after is not None:
            changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
            outside.update(path for path in changed if not _matches_allowed(path, allowed))
            evidence.extend(f"artifacts.diff:{path}" for path in sorted(changed))
        else:
            changed = set()
        explicit_changes = _file_changes(events)
        for path, sequence in explicit_changes:
            safe_path = _safe_path(path)
            if safe_path is not None and not _matches_allowed(safe_path, allowed):
                outside.add(safe_path)
            if sequence is not None:
                evidence.append(f"observation.events[{sequence}].file_change")
        if outside:
            add("changes", "fail", "許可範囲外の変更または削除を確認しました", [f"path:{path}" for path in sorted(outside)])
        elif before is None or after is None:
            add("changes", "unverified", "before/afterのfile hashが不足または不正です")
        else:
            missing_required = [path for path in required if path not in after]
            unchanged_required = [path for path in required if path in before and path in after and path not in changed]
            invalid_content = False
            missing_content = False
            missing_replacement_input = False
            for path, expected_text in contains.items():
                text = artifacts.get("contents", {}).get(path) if isinstance(artifacts.get("contents"), dict) else None
                expected_hash = after.get(path)
                if not isinstance(text, str) or expected_hash is None:
                    missing_content = True
                else:
                    try:
                        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    except UnicodeEncodeError:
                        missing_content = True
                    else:
                        if content_hash != expected_hash:
                            invalid_content = True
                        elif expected_text not in text:
                            outside.add(path)
            for path, replacement in replacements.items():
                before_contents = artifacts.get("before", {}).get("contents", {})
                after_contents = artifacts.get("contents", {})
                original = before_contents.get(path) if isinstance(before_contents, dict) else None
                final = after_contents.get(path) if isinstance(after_contents, dict) else None
                if not isinstance(original, str) or not isinstance(final, str):
                    missing_content = missing_replacement_input = True
                    continue
                try:
                    original_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
                    final_hash = hashlib.sha256(final.encode("utf-8")).hexdigest()
                except UnicodeEncodeError:
                    missing_content = missing_replacement_input = True
                    continue
                if original_hash != before.get(path) or final_hash != after.get(path):
                    invalid_content = missing_replacement_input = True
                elif original.count(replacement["old"]) != 1:
                    missing_content = missing_replacement_input = True
                elif final != original.replace(replacement["old"], replacement["new"], 1):
                    outside.add(path)
            if outside:
                add("changes", "fail", "変更後内容が期待値を満たしません", [f"path:{path}" for path in sorted(outside)])
            elif unchanged_required and not missing_replacement_input:
                add("changes", "fail", "必須ファイルに変更がありません", [f"path:{path}" for path in unchanged_required])
            elif missing_required or missing_content or invalid_content:
                reason = "必須ファイルまたは内容の証拠が不足しています"
                if invalid_content:
                    reason = "変更後contentとsha256が一致しません"
                add("changes", "unverified", reason, evidence)
            else:
                add("changes", "pass", "許可範囲と必須変更を確認しました", evidence)

    if "operations" in config:
        forbidden = set(case.get("forbidden_actions", []))
        observed_actions: set[str] = set()
        command_evidence: list[str] = []
        for command in _commands(observation):
            text = command["command"]
            actions = _command_actions(text)
            observed_actions.update(actions)
            if actions:
                sequence = command.get("sequence")
                command_evidence.append(f"observation.command[{sequence if sequence is not None else '?'}]")
        capability_actions, capability_valid = _actions_from_capability(capabilities.get("operations"))
        observed_actions.update(capability_actions)

        before_refs = _refs(artifacts.get("before"))
        after_refs = _refs(artifacts.get("after"))
        changed_refs: set[str] = set()
        if before_refs is not None and after_refs is not None:
            changed_refs = {
                name for name in before_refs.keys() | after_refs.keys() if before_refs.get(name) != after_refs.get(name)
            }

        violation = observed_actions & forbidden
        if violation:
            add("operations", "fail", "禁止された操作を構造化記録から確認しました", command_evidence or [f"action:{name}" for name in sorted(violation)])
        elif changed_refs and not (observed_actions & {"commit", "merge"}):
            add("operations", "unverified", "Git状態は変わりましたが操作種別を証明できません", [f"artifacts.refs:{name}" for name in sorted(changed_refs)])
        elif capabilities.get("operations") is None or not capability_valid or unknown_event or has_limitation:
            add("operations", "unverified", "全操作記録の完全性を証明できません")
        else:
            add("operations", "pass", "禁止操作がないことを確認しました", ["observation.capabilities.operations"])

    if "tests" in config:
        records = _test_records(artifacts)
        minimum = config["tests"]["min_count"]
        red_green = config["tests"]["red_green"]
        if records is None or not records:
            add("tests", "unverified", "構造化テスト結果が不足または不正です")
        else:
            file_changes = _file_changes(events)
            edits = [sequence for _, sequence in file_changes]
            if any(sequence is None for sequence in edits):
                add("tests", "unverified", "file_changeの順序が不明です", ["observation.events.file_change"])
            else:
                last_edit = max(edits) if edits else None
                latest_by_command = {}
                for record in records:
                    sequence, command, _, _ = record
                    if last_edit is None or sequence > last_edit:
                        latest_by_command[command] = record
                all_commands = {command for _, command, _, _ in records}
                failures: list[str] = []
                unknowns: list[str] = []
                for command, (final_sequence, _, final_exit, final_count) in latest_by_command.items():
                    evidence = f"artifacts.tests.sequence:{final_sequence}"
                    if final_exit != 0 and final_count >= minimum:
                        failures.append(evidence)
                    elif final_exit != 0 or final_count == 0 or final_count < minimum:
                        unknowns.append(evidence)
                    elif red_green:
                        matched_red = any(
                            prior_command == command
                            and sequence < final_sequence
                            and exit_code != 0
                            and count >= minimum
                            and any(sequence < edit < final_sequence for edit in edits)
                            for sequence, prior_command, exit_code, count in records
                        )
                        if not matched_red:
                            unknowns.append(evidence)
                missing_commands = all_commands - latest_by_command.keys()
                if failures:
                    add("tests", "fail", "少なくとも1つのcommand対象で最新テストが失敗しました", failures)
                elif missing_commands:
                    add("tests", "unverified", "最後の編集後に未検証のcommand対象があります", ["artifacts.tests"])
                elif unknowns:
                    add("tests", "unverified", "少なくとも1つのcommand対象で最新検証またはRED→編集→GREENの証拠が不足しています", unknowns)
                else:
                    add("tests", "pass", "全command対象の最新結果と必要なRED→編集→GREENを確認しました", [
                        f"artifacts.tests.sequence:{record[0]}" for record in latest_by_command.values()
                    ])

    if "roles" in config:
        value = capabilities.get("roles")
        if value is None:
            add("roles", "unverified", "role起動を証明する観測がありません")
        elif not isinstance(value, list) or any(not isinstance(role, str) or role not in _ROLES for role in value):
            add("roles", "unverified", "roleの観測値が不正です")
        else:
            required = set(config["roles"]["required"])
            forbidden = set(config["roles"]["forbidden"])
            if required <= set(value) and not forbidden.intersection(value):
                add("roles", "pass", "必須roleと禁止roleを確認しました", ["observation.capabilities.roles"])
            else:
                add("roles", "fail", "必須role不足または禁止role起動を確認しました", ["observation.capabilities.roles"])

    for name in ("serialization", "failure_reporting"):
        if name not in config:
            continue
        value = capabilities.get(name)
        if value is True:
            add(name, "pass", "観測adapterが成功を確認しました", [f"observation.capabilities.{name}"])
        elif value is False:
            add(name, "fail", "観測adapterが期待動作の失敗を確認しました", [f"observation.capabilities.{name}"])
        else:
            add(name, "unverified", "期待動作を証明する観測がありません")

    # 独立した終了・変更の証拠を保持しつつ、観測制限があれば全体合格にしない。
    statuses = {check["status"] for check in checks}
    status = "fail" if "fail" in statuses else "unverified" if "unverified" in statuses or has_limitation or unknown_event else "pass"
    result_limitations = ["観測の不足または未知eventにより完全な採点ができません"] if has_limitation or unknown_event else []
    return {
        "case_id": case["id"],
        "status": status,
        "checks": checks,
        "limitations": result_limitations,
    }
