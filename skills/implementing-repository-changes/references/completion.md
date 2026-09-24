# 完了フロー

1. `superpowers:verification-before-completion` を使い、変更後の状態で必要な検証を新しく実行する。過去の成功や推測だけで完了を主張しない。
2. standard、複数ファイル、共有ロジック、テスト追加、高リスク変更では `superpowers:requesting-code-review` を行う。サブエージェント利用は `AGENTS.md` の共通方針に従い、通常は `reviewer`、高リスク変更は `reviewer_high_risk` へ独立レビューを依頼する。明示的な利用禁止、上位指示・実行環境の制約、機能未提供、起動失敗の場合だけ、理由を記録して自己レビューへ切り替える。利用許可の再確認を求めず、実施していないものを独立レビュー済みと報告しない。独立レビューの手配と統合は親が担当し、子は自身の検証結果を親へ返す。レビューskillが別のrole名を案内しても、AGENTSの既存roleに対応づけ、未許可roleへの切替や権限緩和は行わない。
3. 完了報告には次を含める。
   - 変更概要と影響範囲
   - 実行した確認コマンド
   - 成功、失敗、未実施理由
   - 未確認事項と残リスク
   - 実施した委譲と独立レビュー、代替対応と理由
4. commit が明示的に求められた場合だけ `git-commit` を使う。push、PR作成、merge、release、production 変更、worktree 削除はそれぞれ別の承認境界として扱う。
5. 統合作業が承認された場合だけ `superpowers:finishing-a-development-branch` を使い、対象 branch と最新検証結果を再確認する。
