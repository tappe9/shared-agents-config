# 完了フロー

1. `superpowers:verification-before-completion` を使い、変更後の状態で必要な検証を新しく実行する。過去の成功や推測だけで完了を主張しない。
2. standard、複数ファイル、共有ロジック、テスト追加、高リスク変更では `superpowers:requesting-code-review` を行う。サブエージェントが許可されていなければ、独立レビューを実施できない制約を明記して自己レビューする。
3. 完了報告には次を含める。
   - 変更概要と影響範囲
   - 実行した確認コマンド
   - 成功、失敗、未実施理由
   - 未確認事項と残リスク
4. commit が明示的に求められた場合だけ `git-commit` を使う。push、PR作成、merge、release、production 変更、worktree 削除はそれぞれ別の承認境界として扱う。
5. 統合作業が承認された場合だけ `superpowers:finishing-a-development-branch` を使い、対象 branch と最新検証結果を再確認する。
