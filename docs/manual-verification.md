# Windows／macOSの適用確認

この文書は、共通設定を各端末へ安全に適用するための最小手順です。
端末別のCodex版、外部skillの版・導入元、role起動結果などを継続記録する台帳ではありません。

## 前提

- Superpowersと `git-commit` がインストール済みで、利用するCodexから使用できること。
- 共通ハーネスの変更はこのリポジトリの原本へ先に反映すること。
- 認証、MCP、project trust、通知などの管理対象外設定を原本へ取り込まないこと。
- 実機への適用時は、対象のCodexクライアントを終了すること。

## 通常の適用

原本の変更をGit管理し、作業ツリーがcleanな状態で次の順に実行します。

```bash
python -m harness validate
python -m harness plan
python -m harness apply
python -m harness verify
```

- `validate`: 原本の構文・参照関係を検証します。
- `plan`: 配置先を変更せず、差分・競合を確認します。
- `apply`: 管理対象だけを反映します。
- `verify`: 反映状態、競合、旧定義の残存を確認します。

初回移行で既存AGENTSのローカル追記を保持する必要がある場合は、READMEの `--adopt-from COMMIT` 手順を使用します。

## 問題がある場合

必要に応じて次を実行します。

```bash
python -m harness doctor
```

`doctor` は、明示された依存パス、global override、project scopeの設定、skill overrideなど、
現在確認できる問題を補助的に診断します。

外部skillの導入元・revision・version、Codexクライアント版、実セッションでのrole・model・sandboxの確認結果を
記録していないだけでは警告にしません。

明示的に依存ファイルの場所も調べたい場合だけ、`local.example.toml` を参考にlocal configを設定します。
`doctor --record` はトラブル調査で診断結果を保存したい場合の任意機能であり、通常の適用手順には含めません。

## 実動作確認

設定変更やCodex更新で実動作の確認が必要な場合は、その変更に必要な範囲だけ確認します。
自動テスト、配置検証、`doctor` の成功だけを根拠に、未確認のCodexセッション動作まで確認済みとは扱いません。

サブエージェント方針を変更する場合の確認ケースは
[trigger matrix](../tests/implementing-repository-changes-trigger-matrix.md) を参照できますが、
通常の設定適用ごとに全ケースを実施・記録する必要はありません。
