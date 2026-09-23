---
name: implementing-repository-changes
description: Use when the user authorizes implementing or fixing code, refactoring, updating dependencies, correcting documentation or tests, or modifying Codex configuration or other local development settings. Route implementation, fixes, refactoring, dependencies, Codex configuration, and other behavioral changes to standard flow; route only strictly non-behavioral documentation, comments, wording, type annotations, or tests to lightweight flow. Do not use for investigation-only, explanation-only, planning-only, review-only, merge-only, or monitoring requests.
---

# リポジトリ変更の実装

ユーザーが変更の実行を承認していることを最初に確認する。調査、説明、計画、レビュー、merge、監視だけの依頼では、この skill を使用しない。

1. 変更を分類する。
   - 文書、コメント、文言、型注釈、テストだけで、製品・設定の挙動を変えない変更は `references/lightweight-flow.md` を読む。
   - 仕様追加、バグ修正、リファクタ、依存更新、設定の挙動変更、API・DB・権限などの高リスク変更は `references/standard-flow.md` を読む。
   - 境界が不明なら standard とする。
2. 実装前に、フロー、挙動変更の有無、worktree の有無、影響範囲を1〜3行で示す。
3. 選んだ flow の手順だけを読み、実行する。
4. 完了を主張する直前に `references/completion.md` を読む。

リポジトリの `AGENTS.md` とユーザー指示を優先し、既存差分と秘密情報を保護する。
