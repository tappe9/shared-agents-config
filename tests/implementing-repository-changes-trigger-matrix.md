# implementing-repository-changes trigger matrix

## 期待値

| Prompt | Skill | Flow |
|---|---:|---|
| `このIssueを実装してPR作成まで進めて` | 起動 | standard |
| `READMEの誤字だけ直して` | 起動 | lightweight |
| `Codex設定を変更して重複skillを無効化して` | 起動 | standard |
| `このリポジトリを調査して報告して` | 非起動 | none |
| `実装計画だけ作って` | 非起動 | none |
| `このPRをレビューして` | 非起動 | `superpowers:requesting-code-review` |
| `このPRをマージして` | 非起動 | merge boundary |

## RED — 2026-09-20

- fresh CLI の skill inventory に `implementing-repository-changes` は存在しなかった。
- source の `SKILL.md` と3つの reference の存在検査は exit 1 となった。
- 変更依頼だけに限定された router がないため、positive 3件は起動不能、global AGENTS の詳細フローは negative 4件でも常時コンテキストに含まれる状態だった。

## GREEN

2026-09-20 に source と user 配置の両方で schema validation を実行し、`Skill is valid!` を確認した。source と配置先は `diff -qr` で一致した。

fresh Codex CLI 0.152.1 / `gpt-5.6-luna` / low reasoning で最終 metadata を読み込み、次の順で期待どおり判定された。

```text
trigger / standard
trigger / lightweight
trigger / standard
non-trigger / none
non-trigger / none
non-trigger / none
non-trigger / none
source path: r0/implementing-repository-changes/SKILL.md
```

初回 GREEN では `Codex設定を変更` が non-trigger になったため、description に `Codex configuration` と standard の条件を明記して再検証した。

## Fresh verification — 2026-09-23

Codex CLI 0.155.0-alpha.16 / `gpt-5.6-luna` / low reasoning の ephemeral session で再検証し、user skill は `r0/implementing-repository-changes/SKILL.md` の1件だけ、無効化対象の standalone 3件は非表示、system `skill-creator` は `r1/skill-creator/SKILL.md` に残ることを確認した。

7件の分類は `standard / lightweight / standard / none / none / none / none` で期待値と一致した。

strict diagnostics は `21 ok | 1 idle | 3 notes | 1 warn | 0 fail`。唯一の warning は、管理対象 fragment 外にある既存の `features.rmcp_client` が現在の CLI では未認識であることによる。skill config の parse error、skill path error、fail は0件だった。
