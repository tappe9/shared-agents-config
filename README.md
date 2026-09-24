# shared-agents-config

WindowsとmacOSで、Codexの共通ルール・サブエージェント・個人skillを同じ方針で管理し、Git上の原本と各端末の反映状態を照合するためのリポジトリです。

## 管理対象

| 原本 | 配置先 | 所有範囲 |
|---|---|---|
| `AGENTS.md` | `CODEX_HOME/AGENTS.md` | 管理マーカー内の共通部分 |
| `agents/*.toml` | `CODEX_HOME/agents/` | 管理対象ファイル |
| Git追跡済みの `skills/<name>/**` | `~/.agents/skills/<name>/` | 管理対象ファイル |
| `config/skills-policy.toml` | `CODEX_HOME/config.toml` | 対象user skillの無効化設定だけ |
| `config/dependencies.toml` | 配布せず診断に使用 | 必須の外部skillと出所 |

`CODEX_HOME` はCLIの `--codex-home`、環境変数 `CODEX_HOME`、ホーム配下の `.codex` の順に決定します。user skillの配置先はホーム配下の `.agents/skills` で、`CODEX_HOME` には連動しません。

認証ファイル、MCP、project trust、通知、対象外のskill設定は配布原本に取り込みません。プロジェクト間の関係やアプリ固有の制約は、そのプロジェクトの `AGENTS.md` で管理します。個人skillの原本は `skills/` に置き、この管理リポジトリ内の `.agents/skills/` へ複製しません。

既存の5 role、model、推論強度、sandbox、詳細フロー、commit／push／PR／mergeの承認境界を維持します。開発用 `.env` をworktreeへコピーする既存手順も変更しません。

## 準備

Python 3.11以上とGitが必要です。以下はリポジトリ直下で実行します。アプリの通常運用には `requirements.txt`、テストには `requirements-dev.txt` を使用します。依存はtomlkit、PyYAML、pytestです。

### Windows / PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m harness validate
```

3.11以外の対応済みPythonを使用する場合は、そのバージョン指定で仮想環境を作成します。activateやPowerShell実行ポリシーの変更は不要です。

### macOS

```bash
python3 --version
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m harness validate
```

`python3` が3.11以上であることを確認します。WSLはWindowsネイティブとは別のユーザー環境として扱い、パスを相互変換しません。

## コマンド

```text
python -m harness validate
python -m harness plan [--json] [--adopt-from COMMIT]
python -m harness apply [--adopt-from COMMIT]
python -m harness verify [--json]
python -m harness doctor [--record]
```

全サブコマンドで `--repo`、`--home`、`--codex-home`、`--local-config` を指定できます。オプションはサブコマンドの後に記述します。実機では、Codexが実際に使用しているホーム・CODEX_HOMEへ合わせてください。テストでは `--home` と `--codex-home` の両方を一時領域へ向けます。

| コマンド | 動作 | 終了コード |
|---|---|---|
| validate | 原本の構文、参照先、role一覧、依存を検証。配置先に書き込まない | 0正常、2不正 |
| plan | 配布差分と競合を表示。配置先に書き込まない | 0一致、1差分、2競合・不正 |
| apply | 排他取得後に再評価し、管理対象を反映・検証・記録 | 0成功、2失敗 |
| verify | 管理対象、反映コミット、旧定義を照合。書き込まない | 0一致、1不一致、2読取等の異常 |
| doctor | 外部依存・override等を読み取り診断 | 0正常、1未確認・警告、2必須依存不足等 |

`plan` の終了コード1は「反映する差分あり」であり、構文エラーではありません。差分出力には論理IDと操作区分を使い、configやローカル追記の本文を出力しません。`doctor` は通常書き込みません。`--record` を付けた場合だけ診断記録を保存します。

## 初回導入・旧配置の移行

実機に適用する前にCodexを終了してください。まず `plan` で対象を確認します。新規配置先には管理対象だけを作成します。未知の同名ファイルは無断で上書きしません。

既に共通AGENTSと端末ローカルの追記が混在している場合は、旧原本のコミットを根拠として移行します。今回調査した旧原本は `5c3b08a63dfc5bd8f81581c4bc078e9df712a12f` ですが、両端末がこの版であると断定せず、実際に一致するコミットを指定します。

```bash
python -m harness plan --adopt-from 5c3b08a63dfc5bd8f81581c4bc078e9df712a12f
python -m harness apply --adopt-from 5c3b08a63dfc5bd8f81581c4bc078e9df712a12f
python -m harness verify
```

Windows／Macでは上記の `python` を、準備した仮想環境のPython実行ファイルへ置き換えてください。

旧コミットはローカルGitから読み取ります。ネットワーク取得を自動実行しません。旧AGENTSのprefixと一致する場合だけ後続部分を保持します。比較ではLF／CRLFと先頭BOMの差を許容し、本文の差を勝手に吸収しません。一致しない場合は停止して境界を確認します。

配置先のAGENTSは次の形式になります。

```markdown
<!-- shared-agents-config:begin -->
共通AGENTSの内容
<!-- shared-agents-config:end -->
端末だけの追記
```

閉じマーカーの改行以降がローカル追記です。この部分は配置先で編集でき、同期時もバイト列を保持します。管理部分を直接編集すると競合になります。共通変更はリポジトリの原本に行ってください。ローカル追記のために `AGENTS.override.md` を新設する方式ではありません。

## 通常更新

原本の変更をGit管理し、作業ツリーがcleanな状態で `plan` →差分確認→ `apply` → `verify` の順に実行します。`apply` は未コミットの追跡変更や未追跡ファイルがある場合停止します。ignore済みの計画・仮想環境は除きます。

同じコミット・同じ内容で再適用しても、管理対象ファイルやstateを再書き込みしません。コミットだけ進んだ場合は、内容確認後に反映メタデータだけ更新します。

管理対象の無効化skillが存在しない場合、新規の無効化エントリは作らずNOTEを出します。存在するuser skillの実パスだけを対象とし、同名のsystem／plugin版は名前だけで無効化しません。既存configはTOMLを解析して部分更新し、対象外のキーやコメントを保持します。

## 競合・旧定義・失敗

`conflict` は管理対象への端末側変更、未知の同名ファイル、旧AGENTSの境界不明などです。適用前に競合が見つかれば管理ファイルを書き換えません。`retired` は原本から消えた旧管理ファイルで、自動削除せず報告します。削除する場合は所有範囲と必要性を確認して手動で扱います。

同時適用はstate領域の排他ファイルで防止します。異常終了後に排他ファイルが残っている場合、別処理が動いていないことを確認してから扱ってください。通常処理では削除します。

ファイル単位の一時ファイルと置換で書き込みを保護し、直前の外部変更も検出します。ただし複数ファイルを一括トランザクションとして扱うものではありません。I/O失敗時は残りを停止し、変更済みの論理IDと失敗箇所を報告します。検証成功前に新しい成功stateを記録しません。原因を解消後、再度 `plan` で現在の状態を確認します。

配布元symlink、管理先配下のsymlink／junction、管理先と配布元の重なりは拒否します。POSIXの既存modeは保持しますが、Windowsの個別ACLまで保持できたとは未検証で断定しません。他アプリとの完全な同時更新を保証するものではないので、実機適用時はCodexを終了します。

## 反映状態と依存診断

`CODEX_HOME/shared-agents-config/state.json` に原本コミット、管理ファイルのハッシュ、管理skill設定、旧定義、検証結果を保存します。個人config全体や認証情報は保存しません。

```bash
python -m harness doctor
python -m harness doctor --record
```

後者は同じディレクトリの `diagnostics.json` に結果を保存します。現在の原本コミットと適用済みコミットは別々に記録します。

`local.example.toml` を参考に、実機で確認した依存元を `CODEX_HOME/shared-agents-config/local.toml` に設定できます。`--local-config` による明示指定も可能です。system／pluginの実際の導入場所を確認して記入し、設定例の値を実測値だと扱わないでください。

診断は `observed`（取得した証拠）、`reported`（ローカル設定で申告）、`not_checked`（未確認）を区別します。plugin cacheの存在はファイルの存在証拠にすぎず、現在のCodexセッションでの利用証拠とはしません。CLIのバージョンからDesktopやIDEのバージョンを推測しません。外部skillの自動インストール、ログイン、モデル問い合わせは行いません。

`git-commit` の導入元は未確認です。実機inventoryで確認してから記録します。Superpowersの6.4.1は以前のREADMEの記録であり、現在両端末で有効と断定する値ではありません。

## テストと実機確認

```bash
python -m pytest -q
python -m harness validate
git diff --check
```

テストは一時Gitリポジトリと一時ホームだけを使用します。CI定義はWindows／macOS・Python 3.11／3.14です。実際の個人設定、認証、モデルは使用しません。

新規Codexセッションでの確認は [docs/manual-verification.md](docs/manual-verification.md)、検証証拠と未確認事項は [docs/compatibility.md](docs/compatibility.md) を参照してください。CI成功、配置成功、実機の読み込み成功は別に記録します。
