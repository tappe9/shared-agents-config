# Windows／macOSの適用確認

この文書は、共通設定を各端末へ安全に適用するための最小手順です。
端末別のCodex版、外部skillの版・導入元、role起動結果などを継続記録する台帳ではありません。

## 前提

- Superpowersと `git-commit` がインストール済みで、利用するCodexから使用できること。
- 共通ハーネスの変更はこのリポジトリの原本へ先に反映すること。
- 認証、MCP、project trust、通知などの管理対象外設定を原本へ取り込まないこと。
- 実機への適用時は、対象のCodexクライアントを終了すること。

## 通常の適用

### 1. 原本を確認・準備する

共通変更は配置先から始めず、まず `tappe9/shared-agents-config` のcheckoutを特定します。固定絶対パスは前提にしません。必要に応じて次のようにGit情報を確認します。

```bash
git rev-parse --show-toplevel
git remote -v
```

目的の原本であることを確認できなければ、推測した場所や `CODEX_HOME` の管理領域だけを変更しません。

原本を変更したら、まず次を実行します。

```bash
python -m harness validate
python -m harness plan
```

- `validate`: 原本の構文・参照関係を検証します。
- `plan`: 配置先を変更せず、差分・競合を確認します。

commit、push、PR、mergeは既存の承認境界に従います。原本を先に変更する方針は、これらを無断で実行する許可ではありません。`apply` がcleanな原本を必要とすることだけを理由に、未承認のcommitを行いません。

適用するcommitが確定したら作業ツリーがcleanであることを確認し、そのcommitから `validate` と `plan` を再実行して最終状態を確認します。

### 2. Codexを終了して適用する

対象のCodexクライアントを終了します。その後、Codexとは別のPowerShell／Terminalから実行します。

```bash
python -m harness apply
```

`apply` は管理対象だけを反映します。Codex稼働中に、自分自身が読み込んでいる管理対象へ直接 `apply` する方式は標準手順として動作確認済みとは扱いません。

### 3. 再起動後に確認する

Codexを再起動した後、次を実行して配置状態を確認します。

```bash
python -m harness verify
```

`verify` は反映状態、競合、旧定義の残存を確認する読み取り専用の検証です。成功しても、新しいCodexセッションが変更後の設定を読み込んだことまで証明するものではありません。

設定変更やCodex更新で実動作確認が必要な場合だけ、新規セッションで対象機能を確認します。通常の適用ごとに全roleや全機能を検証・記録する必要はありません。

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
