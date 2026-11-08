# 構成

このリポジトリはWindows/macOS共通設定の原本と、その配置を安全に同期するCLIを管理します。[管理対象と所有範囲](../README.md#管理対象)を境界とし、認証や端末固有の設定は取り込みません。

## 原本から配置確認まで

1. `AGENTS.md`、`agents/`、`skills/`、`config/` の原本を変更する。
2. `validate` で原本の構文・参照を検査し、`plan` で配置差分と競合を確認する。
3. 承認されたcommitを、Codex終了後の外部ターミナルから `apply` する。
4. 再起動後に `verify` で配置状態を照合する。必要な場合だけ対象機能の実動作を別に確認する。

具体的なコマンド、初回移行、競合時の対応は [適用手順](manual-verification.md)を正とします。

## モジュールの責務

| 場所 | 責務 |
|---|---|
| `harness/__main__.py` | CLI引数・終了コード・結果表示 |
| `harness/content.py` | 原本の収集、構文・role・依存・Gitフラグの検証 |
| `harness/paths.py` | 配置先と安全なパス・実エントリの判定 |
| `harness/config_merge.py` | 所有するTOML項目だけを部分更新 |
| `harness/sync.py` | 差分計画、排他、ファイル反映、stateと配置照合 |
| `harness/diagnostics.py` | 明示された依存やoverride等の読み取り診断 |
| `evals/` | Skill評価ケース、記録の採点、手動評価の起動前確認 |
| `tests/` | 一時環境と合成データによる回帰検査 |

`apply` は複数ファイルの一括トランザクションではありません。同期の保護範囲と部分失敗時の扱いは [競合と失敗](manual-verification.md#競合と失敗への対応)を参照してください。

## 方針と評価

共通方針は [AGENTS.md](../AGENTS.md)、実装時のフローは [Skill本体](../skills/implementing-repository-changes/SKILL.md)、roleの静的仕様は [role-validation](role-validation.md)が正本です。各開発プロジェクト固有のルールは、そのプロジェクトのAGENTS.mdで管理します。

配置検証と実動作評価は別です。現在の評価期待値は [cases.json](../evals/implementing-repository-changes.cases.json)、操作方法と観測の限界は [評価ガイド](../evals/README.md)、依頼例は [PROMPTS](PROMPTS.md)を参照してください。評価データは端末別の設定・導入元・版を継続管理する台帳にはしません。
