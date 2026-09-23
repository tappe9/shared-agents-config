# 標準フロー

仕様追加、バグ修正、リファクタ、依存更新、挙動を変える設定変更、外部仕様・DB・API・認証・権限・課金・通知・定期処理に関わる変更で使用する。

1. `git status --short --branch` と worktree 一覧を確認し、既存差分を所有者の作業として保護する。Git 管理外のユーザー設定は、編集前にバックアップと復元手順を用意する。
2. Git リポジトリでは `superpowers:using-git-worktrees` を使い、clean な起点から隔離 worktree を作る。`.worktrees/` を使う場合は ignore 状態を確認する。
3. 作成元に `.env` がある場合だけ、宛先に存在しないことを確認して worktree へコピーする。値は表示せず、追跡・コミットしない。
4. 設計判断が必要なら `superpowers:brainstorming`、4ステップ以上または複数責務なら `superpowers:writing-plans` を使う。計画は元作業ディレクトリの `.plan/YYYY-MM-DD-HHmm-<topic>.md` に置き、コミットしない。
5. 機能追加・修正は `superpowers:test-driven-development` を適用する。先に失敗する再現テストまたは検証条件を作り、失敗理由を確認してから最小実装を行う。
6. 不具合や想定外の失敗は `superpowers:systematic-debugging` で原因を確定してから修正する。
7. サブエージェントはユーザーまたは上位指示が明示的に許可した場合だけ使う。通常レビューは `reviewer`、認証・権限・API契約・DB・データ整合性・秘密情報などは `reviewer_high_risk` を選ぶ。
8. 差分を小さく保ち、無関係な変更、生成物、秘密情報を含めない。
