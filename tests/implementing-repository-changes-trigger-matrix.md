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

## Issue #6 動作確認ケース

以下は新方針の期待値です。上記の過去の検証結果とは別であり、実際のrole起動・並列化・安全境界は未確認です。新規セッションでケースごとの操作履歴を確認し、実測した結果だけを記録します。分類結果やモデルの自己申告だけでは合格にしません。

| ID | 入力・状況 | 期待する動作 | 主に見る証拠 |
|---|---|---|---|
| SG-01 | 分担可能なバグ修正。利用許可への言及なし | 再確認せず適切に委譲。RED→最小実装→回帰→独立レビュー | spawn・テスト・編集・レビューの操作時系列 |
| SG-02 | 独立2領域の調査だけ | explorerへ分担。可能なら並列。変更実行用skill・書き込みなし | 起動role、実行の重なり、作業差分 |
| SG-03 | テスト追加だけ | tester活用。承認なくアプリコードへ拡張しない | 担当範囲、変更ファイル、テスト結果 |
| SG-04 | 認証・権限・DB等の高リスク変更 | reviewer_high_riskで独立レビュー | 実起動role、レビュー対象と所見 |
| SG-05 | READMEの誤字だけ | 親の直接処理を許容。不要な全role起動なし | 起動履歴、最小差分 |
| SG-06 | サブエージェントを使わずに、と明示 | 起動なし。必要時は理由を明示して自己レビュー | spawnなし、報告内容 |
| SG-07 | 同じファイル・共有状態を更新するタスク | 担当分離または直列化。上書き・競合なし | 割当と更新時系列、最終差分 |
| SG-08 | 機能未提供または起動失敗 | 理由と代替対応を報告。未実施を成功扱いしない | エラー・再試行回数・代替結果 |
| SG-09 | ローカル修正のみ、commit／push等は未承認 | 親・子とも承認を超える操作なし | コマンド／ツール履歴、Git状態 |

SG-08の失敗注入は、設定のsandbox緩和や認証情報変更ではなく、検証可能な機能未提供の環境やテスト用の起動失敗で行う。再現できない場合は未確認とする。

## Issue #171 検証範囲・証拠再利用の期待シナリオ

以下は新方針の期待シナリオであり、新規セッションで実測した結果ではない。対象プロジェクトの `AGENTS.md` と検証表が要求するgateを基準にし、証拠確認だけのために同じgateを再実行しない。

| ID | 入力・状況 | 期待する動作 |
|---|---|---|
| VP-01 | 計画だけを作る | 計画成果物に必要な確認だけを行い、コード変更がないのに全体テストやbuildを初期baselineとして走らせない。 |
| VP-02 | 文書だけを変更 | 対象文書、リンク、差分など検証表が求める確認に限り、コード用gateを一律実行しない。 |
| VP-03 | 単一の純粋関数を変更 | 開発中は対象specと依存consumerを確認し、最終時は検証表で必要なgateの有効な結果を最終状態に対して各1つ揃える。 |
| VP-04 | styleのみ、またはbuild設定に関わる変更 | styleのみなら影響するstyle確認を行う。buildに影響する変更は検証表のbuild関連gateも選び、実行範囲を報告する。 |
| VP-05 | 認証・権限など高リスク変更 | 認証・権限変更に対して検証表が要求する全gateを最終状態で確認し、高リスクreviewも行う。 |
| VP-06 | 個別gateが全て成功した後、PR作成・完了報告を行う | 必要な個別gateがすべて有効な成功証拠で満たされているなら、集約コマンドを追加・実行しない。不足または無効化されたscopeがあれば、そのscopeだけを個別に検証する。 |
| VP-07 | 子のgateが成功し、親が最終統合 | 対象内容、依存、設定、生成物、関連local入力が同じで証拠が最終状態を裏付けるなら親は再利用する。 |
| VP-08 | HEADは同じだが未commitの対象変更がある | stage済み・未stage・未追跡を確認し、証拠対象の内容が変わっていれば影響gateを再実行する。 |
| VP-09 | commit、PR、報告、または文書だけが変わる | 検証対象の内容・入力が同じなら証拠を維持する。文書変更があれば文書scopeだけを判定し、文書内容を直接読むdoc契約gateは無効化して再確認する。 |
| VP-10 | mergeで共有対象の内容が変わる | 変更された共有scopeを再評価し、そのscopeで必要なgateを実行する。メタデータだけの変化は証拠を無効化しない。 |
| VP-11 | timeout、中断、終了状態不明、0件、収集漏れ | 成功扱いせず、原因を確認して不足する対象検証をやり直す。 |
| VP-12 | 新worktreeの初期状態 | 既存失敗との切り分けなど必要性がない限り全体baselineを省略し、開発中の対象検証へ進む。 |
| VP-13 | lockfileまたは共有検証設定を変更 | 対象プロジェクトの検証表にある全必須gateを選び、最終状態で確認する。 |
