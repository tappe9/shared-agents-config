# shared-agents-config

WindowsとmacOSで使用するCodexの共通設定を原本として管理し、その変更履歴と各端末への安全な適用を行うためのリポジトリです。ハーネス改善やCodex更新に伴う設定変更は、このリポジトリの原本を先に見直してから各環境へ適用します。

## 管理対象

| 原本 | 配置先 | 所有範囲 |
|---|---|---|
| `AGENTS.md` | `CODEX_HOME/AGENTS.md` | 管理マーカー内の共通部分 |
| `agents/*.toml` | `CODEX_HOME/agents/` | 管理対象ファイル |
| Git追跡済みの `skills/<name>/**` | `~/.agents/skills/<name>/` | 管理対象ファイル |
| `config/skills-policy.toml` | `CODEX_HOME/config.toml` | 対象user skillの無効化設定だけ |
| `config/dependencies.toml` | 配布せず検証・診断に使用 | 必須の外部skill宣言 |

`CODEX_HOME` はCLIの `--codex-home`、環境変数 `CODEX_HOME`、ホーム配下の `.codex` の順に決定します。user skillの配置先はホーム配下の `.agents/skills` で、`CODEX_HOME` には連動しません。

認証ファイル、MCP、project trust、通知、対象外のskill設定は配布原本に取り込みません。プロジェクト間の関係やアプリ固有の制約は、そのプロジェクトの `AGENTS.md` で管理します。個人skillの原本は `skills/` に置き、この管理リポジトリ内の `.agents/skills/` へ複製しません。

既存の5 role、推論強度、sandbox、commit／push／PR／mergeの承認境界を維持します。開発用 `.env` をworktreeへコピーする既存手順も変更しません。

## モデル構成

通常の4 roleは `gpt-6-luna`、高リスクレビューの `reviewer_high_risk` は `gpt-6.1-sol`（推論強度 `high`、`read-only`）を使用します。親エージェントのmodel設定は管理対象外です。

モデルの利用可否はアカウント・workspace・対象Codexクライアントに依存します。モデルやroleを変更する場合は、[実動作確認](docs/manual-verification.md#実動作確認)に従い、必要な範囲で利用可否と実セッションの動作を確認します。

## 外部skillの前提

各環境には **Superpowersと `git-commit` がインストールされ、利用するCodexから使用できること**を前提とします。
`config/dependencies.toml` は共通指示が必要とする外部skill名だけを宣言します。

外部skill自体のインストール、更新、配布元、version／revisionの管理はこのリポジトリの対象外です。
Codexクライアントごとの版、端末ごとの確認日、実セッションでのrole・model・sandbox確認結果も継続的な台帳にはしません。

## 運用方針

共通ルール・worktreeの配置・サブエージェントの利用条件・検証結果の再利用は [AGENTS.md](AGENTS.md) を参照してください。範囲を切り出せる作業は既存5 roleへ分担し、軽微な作業は親が直接対応します。委譲しても操作の承認範囲は増えません。

## 準備

Python 3.11以上とGitが必要です。以下はリポジトリ直下で実行します。アプリの通常運用には `requirements.txt`、テストには `requirements-dev.txt` を使用します。runtime依存はtomlkit、PyYAML、jsonschema、テスト追加分はpytestです。バージョン範囲は各requirementsファイルを正とします。
venvを作成する前のPython確認・作成コマンドだけはホストのPythonを使います。作成後のローカルCLIとテストでは、以降の例のようにvenv内のPythonを指定します。

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

リポジトリのGitルートで、準備節のvenv Pythonから `-m harness <コマンド>` を実行します。activateは不要です。初回導入・更新・外部ターミナルでのapply・再起動後のverifyは、[適用手順](docs/manual-verification.md)を参照してください。

全サブコマンドで `--repo`、`--home`、`--codex-home`、`--local-config` を指定できます。オプションはサブコマンドの後に記述します。実機ではCodexが使用する配置先に合わせ、テストではhomeとCODEX_HOMEの両方を一時領域へ向けます。

| コマンド | 動作 | 終了コード |
|---|---|---|
| validate | 原本の構文、参照先、role一覧、依存を検証。配置先に書き込まない | 0正常、2不正 |
| plan | 配布差分と競合を表示。配置先に書き込まない | 0一致、1差分、2競合・不正 |
| apply | 排他取得後に再評価し、管理対象を反映・検証・記録 | 0成功、2失敗 |
| verify | 管理対象、反映コミット、旧定義を照合。書き込まない | 0一致、1不一致、2読取等の異常 |
| doctor | 明示した依存パス・override等を読み取り診断 | 0診断対象に問題なし、1実際の警告、2確認できた必須依存不足等 |

`plan` の終了コード1は「反映する差分あり」であり、構文エラーではありません。差分出力には論理IDと操作区分を使い、configやローカル追記の本文を出力しません。`doctor --record` はトラブル調査で診断記録を保存したい場合だけ使います。

## 文書の入口

| 知りたいこと | 参照先 |
|---|---|
| 原本・モジュール・配布の関係 | [構成](architecture.md) |
| 依頼の書き方と操作範囲 | [プロンプト例](PROMPTS.md) |
| 原本変更から適用・確認まで | [通常の適用](docs/manual-verification.md#通常の適用) |
| 既存AGENTSを初めて移行する | [初回導入と旧配置の移行](docs/manual-verification.md#初回導入と旧配置の移行) |
| 競合・部分失敗・診断 | [競合と失敗](docs/manual-verification.md#競合と失敗への対応)・[診断](docs/manual-verification.md#問題がある場合) |
| モデル・role変更後に必要な確認 | [実動作確認](docs/manual-verification.md#実動作確認) |
| roleの静的検査とschemaの更新 | [role検証仕様](docs/role-validation.md) |
| Skillの評価方法と観測の限界 | [評価ガイド](evals/README.md) |
| 既存のSG/VP期待シナリオと過去実績 | [trigger matrix](tests/implementing-repository-changes-trigger-matrix.md) |

## テスト

Windows / PowerShellでは `.\.venv\Scripts\python.exe -m pytest -q`、macOSでは `./.venv/bin/python -m pytest -q` を使います。文書差分は `git diff --check` で確認します。

通常pytestは一時Gitリポジトリ・合成データ・fake実行だけを使用し、個人設定、認証、実モデルは使いません。CIはWindows／macOS × Python 3.11／3.14です。CI結果はGitHub Actionsを正とし、実行URLや端末別結果を別のMarkdown台帳へ転記しません。

静的検査や配置確認の成功と、実際のSkill選択・role起動・モデルの動作確認は別です。実モデル評価は明示した手動実行に限り、観測できない項目を合格にしません。
