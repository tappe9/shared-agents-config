# Skill動作評価

`implementing-repository-changes` の入力と期待値を [18件のケース](implementing-repository-changes.cases.json)で管理し、記録と成果物を決定的に採点します。同期CLIの `harness verify` とは別の検証です。

## 現在できること

| 操作 | 対応範囲 |
|---|---|
| `validate` | ケースschema・重複ID・パス・期待値の検証。外部コマンドを起動しない |
| `grade` | JSONLと添付した成果物の部分判定。証明できない項目は未確認 |
| `run --live` | 信頼するCLIのversion/helpによる起動前確認。現時点では検証済みlive adapterがなく、モデルを起動せず未確認で終了 |

2026-11-07の調査対象はCodex CLI 0.156.1です。JSONL出力はありますが、Skill選択・flow・role起動・全操作記録の完全性と、認証・外部capabilityを含む隔離の契約は未確認です。**現在のparserから標準ケース全体の実動作合格を出すことはできません。** 変更範囲やテスト結果など、証拠のある項目を個別に判定する基盤として使います。

ファイルの配置、静的テスト、モデルの自己申告、文字列にSkill名が含まれることを、実際のSkill選択やrole起動の証拠にしません。旧CLIのGREEN記録は [過去の履歴](../tests/implementing-repository-changes-trigger-matrix.md)に分けています。

## ローカル実行

リポジトリのGitルートで、[準備済みvenv](../README.md#準備)のPythonを使います。activateは不要です。

Windows / PowerShell:

```powershell
.\.venv\Scripts\python.exe -m evals.runner validate
.\.venv\Scripts\python.exe -m evals.runner grade --case P01 --trace .eval-runs\sample\trace.jsonl --artifacts .eval-runs\sample\artifacts.json
```

macOS:

```bash
./.venv/bin/python -m evals.runner validate
./.venv/bin/python -m evals.runner grade --case P01 --trace .eval-runs/sample/trace.jsonl --artifacts .eval-runs/sample/artifacts.json
```

`grade` は指定ファイルを読むだけで、コマンドやテストを再実行しません。ケースを別ファイルから読む場合は `--cases PATH` をサブコマンドの後に付けます。入力には合成fixtureのデータを使い、認証情報・個人config・`.env` の値を含めません。

実モデル評価の起動前確認を明示的に行う場合だけ、次を使います。CLIは信頼できるインストール済み実行ファイルの絶対パスを指定します。

```powershell
.\.venv\Scripts\python.exe -m evals.runner run --live --case P01 --codex-bin 'C:\path\to\codex.exe' --timeout-seconds 180 --output .eval-runs\p01-preflight
```

```bash
./.venv/bin/python -m evals.runner run --live --case P01 --codex-bin /absolute/path/to/codex --timeout-seconds 180 --output .eval-runs/p01-preflight
```

`--live`、単一の `--case`、CLI指定が必要です。時間上限の入力範囲は1〜600秒、既定180秒です。現段階の結果はpreflightのみであり、モデルを実行したbaselineではありません。全ケース一括実行・自動再試行・安全条件を迂回するフラグはありません。

preflightのversion/helpは共通の期限を使い、指定上限と10秒の短い方で打ち切ります。timeout時の所有プロセス終了・回収には、別に最大5秒の猶予を使います。

## 結果の読み方

結果は `case_id / status / checks / limitations` を持ち、各checkに `name / status / reason / evidence` を返します。

| status | 意味 |
|---|---|
| `pass` | 必要な証拠が揃い、その項目の期待値を満たす |
| `fail` | 禁止操作・範囲外変更・対象検証の失敗などを観測した |
| `unverified` | 未実行、形式未対応、証拠不足、timeout、中断、終了不明、必要なテストが0件など |

全体はfailを優先し、次にunverified、全必須項目が証明された場合だけpassとします。timeoutでも観測済みの違反はfailのままです。テストの成功は同じコマンド・対象の最新の有効な結果を見ます。古いGREENや別対象の成功で、後続の失敗を隠しません。

終了コードは0が全必須pass（`validate` は入力正常）、1がfail、2がunverifiedまたは入力不正です。証拠がない `None` と、完全な観測の結果である空配列を区別します。artifact内に「完全に観測した」と書くだけでは、CLIの観測能力を補えません。

## 入力する記録と成果物

traceには公式exec JSONLの既知eventを使います。`turn.completed` はOSプロセスの終了コードではありません。未知eventや解釈できない形式は制約として残します。`grade_case` の内部観測形を、そのまま公式JSONLとみなさないでください。

artifacts JSONは次の実測情報を持ちます。存在しない証拠を埋めたり、成功フラグを創作したりしません。

- `process_exit`、`timed_out`: 実プロセスの終了状態。
- `before / after`: `files`（論理的な相対パス→SHA-256）、`head`、`refs`。
- `contents`: 内容の期待値を調べる対象ファイルの最終テキスト。
- `tests`: `command / exit_code / count / sequence` の記録。RED→編集→GREENはtraceの編集順序とも照合する。
- `policy_hashes`: 実際に投入した方針・Skill・role・必要依存の入力hash。

誤字修正のように変更を1か所へ限定するケースは、`changes.replacements` の `old / new` を使います。その場合は `before.contents` に変更前テキストも添付し、前後のhashと内容を照合します。内容は元ファイルのUTF-8を改行も含めて保持し、指定箇所の1回の置換以外が変わっていれば合格にしません。

traceと成果物は同じcase/runから採取します。添付されていない成果物を、モデルの説明文で補いません。traceやartifactの採点結果は、入力記録自体の真正性を保証するものではありません。

`cases.py` の準備APIは合成fixtureからremoteなしの一時Git repoを作り、追跡された原本AGENTS・対象Skill・5 roleを一時領域へ配置します。ホストのローカル追記・override・認証を検索しません。配置されたことと、対象CLIが実際に読み込んだことは別の証拠です。

外部依存を準備APIへ渡す場合は、`dependency_roots` に加え、同じIDごとの必要な相対ファイル一覧を `dependency_files` で指定します。`SKILL.md` を含む明示リストだけをコピーし、directory全体を取り込みません。認証・個人config・env・Git管理情報は選択対象にしません。fixtureは `.worktrees/` と `.plan/` を除外済みで、初期commit日時も固定しています。

## 保存とlive対応の条件

既定では一時データを破棄します。`--output` を付けた場合だけ、Git除外された `.eval-runs/NAME/` に結果を保存します。既存の出力先は上書きしません。raw traceや入力artifactを自動で外部公開・GitHub転記しません。

将来live adapterを追加する際は、CLIの引数とtrace形式、方針・依存の読込、操作者が準備した隔離認証、sandboxと外部capabilityの遮断、所有する子プロセスの終了・証拠収集を検証してから有効にします。homeの一時化やネットワーク制約だけで、MCP/apps/plugins等も遮断できたとはみなしません。認証や個人設定を自動コピーせず、保護ルール・sandboxを緩和して実行しません。

比較時はcase・fixture・CLI・model・依存・方針入力を揃え、変更したSkill hashを明示します。未確認は未確認のまま残し、再現した実動作の問題だけをSkill修正につなげます。外部Skillの導入・版の管理台帳は作りません。

## ケース追加とofflineテスト

ケースの正本は `implementing-repository-changes.cases.json`、入力制約は `cases.schema.json` です。ID、具体的prompt、暗黙/明示の区分、fixture、期待flow、許可変更、禁止操作、必要check、SG/VP参照を設定します。新しいcheckを追加するときは、欠落・誤動作・正しい動作を合成データで先にテストします。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_skill_cases.py tests/test_skill_grade.py tests/test_skill_runner.py -q
```

```bash
./.venv/bin/python -m pytest tests/test_skill_cases.py tests/test_skill_grade.py tests/test_skill_runner.py -q
```

通常pytest/CIは合成JSONLとfake実行だけで完結します。fixtureのテストは `.template` として保管し、評価用repoへ展開してから使用するため、通常pytestに混ざりません。18ケースは既存のSG/VP期待シナリオを全て実測・網羅したという意味ではありません。

参考: [OpenAI公式のSkill評価手順](https://developers.openai.com/blog/eval-skills)、[non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)、[CLI reference](https://learn.chatgpt.com/docs/cli/reference)。古い記事のコマンドをそのまま転記せず、対象CLIのhelpと仕様を確認します。
