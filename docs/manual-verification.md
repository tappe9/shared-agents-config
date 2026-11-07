# Windows／macOSの適用確認

この文書は、共通設定を各端末へ安全に適用するための手順の正本です。
端末別のCodex版、外部skillの版・導入元、role起動結果などを継続記録する台帳ではありません。

## 前提

- Superpowersと `git-commit` がインストール済みで、利用するCodexから使用できること。
- 共通ハーネスの変更はこのリポジトリの原本へ先に反映すること。
- 認証、MCP、project trust、通知などの管理対象外設定を原本へ取り込まないこと。
- 実機への適用時は、対象のCodexクライアントを終了すること。
- ローカルコマンドはリポジトリのGitルートで実行し、[READMEの準備節](../README.md#準備)で作成したvenvのPythonを使うこと。activateは不要です。

Windows / PowerShellでは `.\.venv\Scripts\python.exe`、macOSでは `./.venv/bin/python` を指定します。Codex終了後の外部ターミナルでも、原本リポジトリのGitルートへ移動して同じvenvを使います。

## 変更先の判断

共通ルール、role、skill、同期CLIが管理する設定など、Windows／macOSで揃える変更はこのリポジトリを原本として先に変更します。配置済みの管理領域だけを直接編集して、その変更を原本へ後追いで戻す運用にはしません。

変更先は次のように分けます。

| 変更内容 | 変更先 |
|---|---|
| Windows／macOSで共有するハーネス | このリポジトリの原本 |
| 端末だけのAGENTS追記 | 配置先AGENTSの管理マーカー外 |
| 認証、MCP、project trust、通知などの管理対象外設定 | 各端末 |
| 各開発プロジェクト固有のルール | そのプロジェクトの `AGENTS.md` |

## 通常の適用

### 1. 原本を確認・準備する

共通変更は配置先から始めず、まず `tappe9/shared-agents-config` のcheckoutを特定します。固定絶対パスは前提にしません。必要に応じて次のようにGit情報を確認します。

```bash
git rev-parse --show-toplevel
git remote -v
```

目的の原本であることを確認できなければ、推測した場所や `CODEX_HOME` の管理領域だけを変更しません。

原本を変更したら、まず次を実行します。

```powershell
.\.venv\Scripts\python.exe -m harness validate
.\.venv\Scripts\python.exe -m harness plan --json
```

```bash
./.venv/bin/python -m harness validate
./.venv/bin/python -m harness plan --json
```

- `validate`: 原本の構文・参照関係を検証します。
- `plan`: 配置先を変更せず、差分・競合を確認します。

commit、push、PR、mergeは既存の承認境界に従います。原本を先に変更する方針は、これらを無断で実行する許可ではありません。`apply` がcleanな原本を必要とすることだけを理由に、未承認のcommitを行いません。

適用するcommitが確定したら作業ツリーがcleanであることを確認し、そのcommitから `validate` と `plan` を再実行して最終状態を確認します。

### 2. Codexを終了して適用する

対象のCodexクライアントを終了します。その後、Codexとは別のPowerShell／Terminalから実行します。

```powershell
.\.venv\Scripts\python.exe -m harness apply
```

```bash
./.venv/bin/python -m harness apply
```

`apply` は管理対象だけを反映します。Codex稼働中に、自分自身が読み込んでいる管理対象へ直接 `apply` する方式は標準手順として動作確認済みとは扱いません。

### 3. 再起動後に確認する

Codexを再起動した後、次を実行して配置状態を確認します。

```powershell
.\.venv\Scripts\python.exe -m harness verify
```

```bash
./.venv/bin/python -m harness verify
```

`verify` は反映状態、競合、旧定義の残存を確認する読み取り専用の検証です。成功しても、新しいCodexセッションが変更後の設定を読み込んだことまで証明するものではありません。

設定変更やCodex更新で実動作確認が必要な場合だけ、新規セッションで対象機能を確認します。通常の適用ごとに全roleや全機能を検証・記録する必要はありません。

初回移行で既存AGENTSのローカル追記を保持する場合は、[初回導入と旧配置の移行](#初回導入と旧配置の移行)を参照してください。

### 同期時の扱い

原本の変更をGit管理し、作業ツリーがcleanな状態で `plan` →差分確認→ `apply` → `verify` の順に実行します。`apply` は未コミットの追跡変更や未追跡ファイルがある場合停止します。ignore済みの計画・仮想環境は除きます。

管理入力に `assume-unchanged` または `skip-worktree` が付いている場合、HEADと内容が一致していても `plan`、`apply`、`verify` は停止します。フラグと原本を確認し、必要な対応後に `plan` をやり直してください。ハーネスはフラグを自動解除しません。

同じコミット・同じ内容で再適用しても、管理対象ファイルやstateを再書き込みしません。コミットだけ進んだ場合は、内容確認後に反映メタデータだけ更新します。

管理対象の無効化skillが存在しない場合、新規の無効化エントリは作らずNOTEを出します。存在するuser skillの実パスだけを対象とし、同名のsystem／plugin版は名前だけで無効化しません。既存configはTOMLを解析して部分更新し、対象外のキーやコメントを保持します。

Skill overrideは実ディレクトリエントリ単位で照合します。別名hardlinkは別対象として扱い、大文字小文字などの表記差は同じ実エントリを確認できた場合に既存設定を更新します。

## 初回導入と旧配置の移行

実機に適用する前にCodexを終了してください。まず `plan` で対象を確認します。新規配置先には管理対象だけを作成します。未知の同名ファイルは無断で上書きしません。

既に共通AGENTSと端末ローカルの追記が混在している場合は、旧原本のコミットを根拠として移行します。過去の移行例の旧原本は `5c3b08a63dfc5bd8f81581c4bc078e9df712a12f` ですが、両端末がこの版であると断定せず、実際に一致するコミットを指定します。

```powershell
.\.venv\Scripts\python.exe -m harness plan --adopt-from 5c3b08a63dfc5bd8f81581c4bc078e9df712a12f
.\.venv\Scripts\python.exe -m harness apply --adopt-from 5c3b08a63dfc5bd8f81581c4bc078e9df712a12f
.\.venv\Scripts\python.exe -m harness verify
```

```bash
./.venv/bin/python -m harness plan --adopt-from 5c3b08a63dfc5bd8f81581c4bc078e9df712a12f
./.venv/bin/python -m harness apply --adopt-from 5c3b08a63dfc5bd8f81581c4bc078e9df712a12f
./.venv/bin/python -m harness verify
```

旧コミットはローカルGitから読み取ります。ネットワーク取得を自動実行しません。旧AGENTSのprefixと一致する場合だけ後続部分を保持します。比較ではLF／CRLFと先頭BOMの差を許容し、本文の差を勝手に吸収しません。一致しない場合は停止して境界を確認します。

配置先のAGENTSは次の形式になります。

```markdown
<!-- shared-agents-config:begin -->
共通AGENTSの内容
<!-- shared-agents-config:end -->
端末だけの追記
```

閉じマーカーの改行以降がローカル追記です。この部分は配置先で編集でき、同期時もバイト列を保持します。管理部分を直接編集すると競合になります。共通変更はリポジトリの原本に行ってください。ローカル追記のために `AGENTS.override.md` を新設する方式ではありません。

## 競合と失敗への対応

`conflict` は管理対象への端末側変更、未知の同名ファイル、旧AGENTSの境界不明などです。適用前に競合が見つかれば管理ファイルを書き換えません。`retired` は原本から消えた旧管理ファイルで、自動削除せず報告します。削除する場合は所有範囲と必要性を確認して手動で扱います。

同時適用はstate領域の排他ファイルで防止します。異常終了後に排他ファイルが残っている場合、別処理が動いていないことを確認してから扱ってください。通常処理では削除します。

ファイル単位の一時ファイルと置換で書き込みを保護し、直前の外部変更も検出します。ただし複数ファイルを一括トランザクションとして扱うものではありません。I/O失敗時は残りを停止し、変更済みの論理IDと失敗箇所を報告します。検証成功前に新しい成功stateを記録しません。原因を解消後、再度 `plan` で現在の状態を確認します。

配布元symlink、管理先配下のsymlink／junction、管理先と配布元の重なりは拒否します。POSIXの既存modeは保持しますが、Windowsの個別ACLまで保持できたとは未検証で断定しません。他アプリとの完全な同時更新を保証するものではないので、実機適用時はCodexを終了します。

## 問題がある場合



`CODEX_HOME/shared-agents-config/state.json` に原本コミット、管理ファイルのハッシュ、管理skill設定、旧定義、検証結果を保存します。これは安全な同期・競合検出・反映状態の照合に必要な自動管理情報です。端末構成の手作業台帳ではなく、個人config全体や認証情報も保存しません。



必要に応じて次を実行します。

```powershell
.\.venv\Scripts\python.exe -m harness doctor
```

```bash
./.venv/bin/python -m harness doctor
```

`doctor` は、明示された依存パス、global override、project scopeの設定、skill overrideなど、
現在確認できる問題を補助的に診断します。

global override、project scopeの設定、skill overrideなど、実際に確認できる問題は警告します。明示的に指定した依存パスに必須Skillが存在しなければ、不足として報告します。

外部skillの導入元・revision・version、Codexクライアント版、実セッションでのrole・model・sandboxの確認結果を
記録していないだけでは警告にしません。

明示的に依存ファイルの場所も調べたい場合だけ、[local.example.toml](../local.example.toml) を参考にlocal configを設定します。
`doctor --record` はトラブル調査で診断結果を保存したい場合の任意機能であり、通常の適用手順には含めません。必要な場合も、上記のOS別venv Pythonを指定し、トラブル調査のためにのみオプションを追加します。

```powershell
.\.venv\Scripts\python.exe -m harness doctor --record
```

```bash
./.venv/bin/python -m harness doctor --record
```

## 実動作確認

設定変更やCodex更新で実動作確認が必要な場合は、その変更に必要な範囲だけ確認します。通常の適用ごとに全roleや全機能を検証・記録する必要はありません。

モデルやroleを変更する場合は、適用前に対象アカウント・workspace・Codexクライアントで必要なモデルを利用できることを確認します。利用できなければ対象端末の更新を保留します。[公式の設定手順](https://learn.chatgpt.com/docs/developer-settings#change-settings-for-one-run)も参照できます。

適用後は新規セッションで対象機能を小さく確認し、必要に応じて実際のrole・model・推論強度・sandboxを操作履歴から確認します。設定ファイルの値やモデルの自己申告だけを実起動の証拠にしません。

`validate`、自動テスト、CI、`verify`、`doctor` は、それぞれ原本・配布処理・配置・診断範囲の検証です。未確認のSkill読み込みや実セッション動作まで確認済みとは扱いません。`doctor` のexit 0も、モデルへのアクセスやsandboxの実効性を保証しません。

Skillの現在の評価ケースと判定方法は [評価ガイド](../evals/README.md)、既存のSG/VP期待シナリオと過去の記録は [trigger matrix](../tests/implementing-repository-changes-trigger-matrix.md) を参照してください。実測していないケースは未確認のまま扱います。
