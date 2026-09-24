# Windows／macOSへの適用とトラブル確認

この文書は、共通ハーネスを各端末へ適用するときの短い手順です。端末・Codexクライアント・外部skillの版、確認日、実機テスト結果を記録する台帳ではありません。

## 通常更新

1. 共通設定を変更する場合は、先にこのリポジトリの原本を更新し、必要なテストを行います。
2. 適用先で動作中のCodexを終了します。
3. 作業ツリーがcleanであることを確認し、`python -m harness validate` を実行します。
4. `python -m harness plan` で差分、競合、旧定義を確認します。
5. 問題がなければ `python -m harness apply` を実行します。
6. `python -m harness verify` で管理対象と反映状態を確認します。
7. 必要に応じてCodexを再起動し、今回変更した機能だけを確認します。

`plan` で競合が出た場合は、管理対象への端末側変更を無断で上書きせず、原本とローカル変更の境界を確認してください。MCP、認証、project trust、通知、端末固有のAGENTS追記などの管理対象外設定は保持します。

## 初回導入・旧配置からの移行

既存の共通AGENTSと端末ローカル追記が混在している場合は、実際に一致する旧原本コミットを指定して確認します。

```bash
python -m harness plan --adopt-from COMMIT
python -m harness apply --adopt-from COMMIT
python -m harness verify
```

未知のprefixや同名ファイルは推測で取り込みません。`plan` が競合を報告した場合は停止して内容を確認します。

## 問題が発生した場合

まず次を確認します。

```bash
python -m harness plan
python -m harness verify
```

必要な場合だけ `python -m harness doctor` を実行し、override、project scope、skill override、明示した外部skillパスなどを確認します。診断結果を一時的に残したい場合だけ `python -m harness doctor --record` を使用します。

確認ポイント:

- `AGENTS.override.md` が共通指示を隠していないか。
- `config.toml` の管理対象skill overrideが相対パスや消失したパスを指していないか。
- `retired` として報告された旧role／skillが残っていないか。
- 端末固有のAGENTS追記とMCP・認証等の管理対象外設定が保持されているか。
- 明示的に診断対象へ指定したSuperpowers／`git-commit` のパスが実在するか。

外部skillの導入元、version／revision、Codexクライアント版、確認日は通常運用では記録しません。CI結果もMarkdownへ転記せずGitHub Actionsを参照します。

サブエージェントの挙動そのものを変更した場合など、変更内容に応じた確認が必要なときだけ [trigger matrix](../tests/implementing-repository-changes-trigger-matrix.md) を使用します。毎回SG-01〜09を実施・記録する運用にはしません。
