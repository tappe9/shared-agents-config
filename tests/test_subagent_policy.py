"""原本文言・設定値・配布の回帰検査。モデルの実行挙動は検証しない。"""

from pathlib import Path
import re
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLOW = "skills/implementing-repository-changes/references"
EXPECTED = {
    "explorer": ("gpt-6-luna", "xhigh", "read-only"),
    "implementer": ("gpt-6-luna", "xhigh", "workspace-write"),
    "reviewer": ("gpt-6-luna", "xhigh", "read-only"),
    "reviewer_high_risk": ("gpt-6-sol", "high", "read-only"),
    "tester": ("gpt-6-luna", "high", "workspace-write"),
}


def read_text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def subagent_policy() -> str:
    text = read_text("AGENTS.md")
    return text.split("## サブエージェント\n", 1)[1].split("\n## ", 1)[0]


def test_common_policy_delegates_without_reconfirmation():
    policy = subagent_policy()
    assert "追加の利用確認なし" in policy
    assert "委譲を原則" in policy
    assert "明示的に許可した場合だけ" not in policy


def test_common_policy_keeps_exceptions_and_authority_boundary():
    policy = subagent_policy()
    for clause in (
        "明示的な利用禁止", "上位指示", "実行環境",
        "操作の承認", "新しい role", "事前", "承認",
        "再委譲", "親",
    ):
        assert clause in policy


def test_common_role_settings_and_allowlist_are_unchanged():
    files = {p.stem: p for p in (ROOT / "agents").glob("*.toml")}
    assert set(files) == set(EXPECTED)
    for name, expected in EXPECTED.items():
        data = tomllib.loads(files[name].read_text(encoding="utf-8-sig"))
        assert data["name"] == name
        assert tuple(data[k] for k in (
            "model", "model_reasoning_effort", "sandbox_mode"
        )) == expected
    lines = [line for line in read_text("AGENTS.md").splitlines()
             if "`agent_type`" in line]
    allowed = set(re.findall(r"`([^`]+)`", "\n".join(lines))) - {"agent_type"}
    assert allowed == set(EXPECTED)


@pytest.mark.parametrize("relative", [
    f"{FLOW}/standard-flow.md", f"{FLOW}/completion.md",
])
def test_flow_uses_common_policy_without_per_request_permission(relative):
    text = read_text(relative)
    assert "AGENTS.md" in text
    assert "サブエージェント" in text
    assert "明示的に許可した場合だけ" not in text
    assert "サブエージェントが許可されていなければ" not in text


def test_standard_flow_keeps_red_before_implementation_and_serializes_conflicts():
    text = read_text(f"{FLOW}/standard-flow.md")
    for clause in ("失敗理由", "最小実装", "同じファイル", "共有DB", "直列化"):
        assert clause in text


def test_completion_names_real_fallback_reasons():
    text = read_text(f"{FLOW}/completion.md")
    for clause in ("明示的な利用禁止", "機能未提供", "起動失敗", "独立レビュー済み"):
        assert clause in text
    for operation in ("commit", "push", "PR", "merge", "release", "worktree"):
        assert operation in text


def test_tester_supports_before_and_after_implementation_without_weakening_rules():
    data = tomllib.loads(read_text("agents/tester.toml"))
    assert "実装前" in data["description"]
    assert "実装後" in data["description"]
    text = data["developer_instructions"]
    for clause in (
        "仕様", "失敗理由", "期待値を変更しない", "テスト失敗を隠さない",
        "アプリケーションコードは原則変更しない", "親",
    ):
        assert clause in text


@pytest.mark.parametrize("relative", [
    "AGENTS.md", f"{FLOW}/standard-flow.md", f"{FLOW}/completion.md",
    "README.md", "docs/manual-verification.md",
])
def test_active_guidance_has_no_old_permission_gate(relative):
    text = read_text(relative)
    for old in (
        "ユーザーまたは上位指示が明示的に許可した場合だけ",
        "サブエージェントが許可されていなければ",
        "そのテスト用の明示承認がある場合だけ",
    ):
        assert old not in text


def test_new_behavior_cases_are_documented_separately():
    text = read_text("tests/implementing-repository-changes-trigger-matrix.md")
    assert "## Issue #6 動作確認ケース" in text
    for number in range(1, 10):
        assert f"SG-{number:02d}" in text


def test_actual_policy_payload_is_deployed_and_idempotent(sandbox):
    from harness.content import extract_local_suffix, managed_common, render_agents, source_files
    from harness.sync import apply_plan, build_plan, verify_deployment

    payload = source_files(ROOT)
    for name, raw in payload.items():
        sandbox.write(name, raw)
    for name in ("config/skills-policy.toml", "config/dependencies.toml"):
        sandbox.write(name, (ROOT / name).read_bytes())
    sandbox.commit()

    home = sandbox.layout.codex_home
    home.mkdir(parents=True, exist_ok=True)
    suffix = b"\n## Local\r\nkeep-local-rule\r\n"
    (home / "AGENTS.md").write_bytes(render_agents(payload["AGENTS.md"], suffix))
    local_config = b'model = "local-parent-test-value"\n'
    (home / "config.toml").write_bytes(local_config)

    first = apply_plan(sandbox.layout, build_plan(sandbox.layout))
    assert first.problems == []
    deployed = (home / "AGENTS.md").read_bytes()
    assert "追加の利用確認なし" in managed_common(deployed).decode("utf-8")
    assert extract_local_suffix(deployed) == suffix
    assert (home / "config.toml").read_bytes() == local_config
    assert verify_deployment(sandbox.layout) == []
    for role in EXPECTED:
        assert (home / "agents" / f"{role}.toml").read_bytes() == payload[f"agents/{role}.toml"]

    second = apply_plan(sandbox.layout, build_plan(sandbox.layout))
    assert second.problems == []
    assert second.changed_ids == []
    assert verify_deployment(sandbox.layout) == []
