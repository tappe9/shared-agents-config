# 個人環境設定

## 常時適用するルール

- 回答・コードコメント・ドキュメントは日本語を優先する
- 既存の変更を壊さない。破壊的コマンド（`git reset --hard`、`git checkout -- .` など）は使わない
- 機能の用途・公開範囲を尊重し、導線や挙動を勝手に変えない
- 不明点は推測で埋めすぎず、前提と影響範囲を明示する
- 指示が衝突する場合は「ユーザー指示 > AGENTS.md > 各スキルの詳細手順」の順で解決する。ただし、安全性・破壊的操作回避・既存制約は常に優先する
- 機密情報、token、接続文字列、個人情報、`.env` の値を回答・ログ・Gitへ出力しない

## Skill routing

- 依頼に一致する skill がある場合は使用する
- ユーザーがリポジトリファイルまたはローカル開発設定の変更実行を承認した場合だけ `implementing-repository-changes` を使う
- 調査、説明、計画、レビュー、merge、監視だけの依頼では `implementing-repository-changes` を使わない

## サブエージェント

- サブエージェントはユーザーまたは上位指示が明示的に許可した場合だけ使用する
- 許可する `agent_type` は `explorer`、`implementer`、`reviewer`、`reviewer_high_risk`、`tester` に限る
- 通常レビューは `reviewer`、認証・権限・API契約・DB・データ整合性・秘密情報などの高リスクレビューは `reviewer_high_risk` を使う
- 新しい role が必要なら、`agents/` の定義追加と許可リスト更新について事前にユーザー承認を得る

## 計画ファイル

- 作業計画は元作業ディレクトリの `.plan/YYYY-MM-DD-HHmm-<topic>.md` に作成し、Git管理・コミット対象にしない
- `<topic>` は英小文字 kebab-case とし、`current.md` は作成しない
