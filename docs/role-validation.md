# Role設定の静的検証

## 目的

`agents/*.toml` の誤設定を、端末へ配布する前に `python -m harness validate` とCIで検出します。
静的検証の成功は、モデルが契約上利用可能であることや、実際のsubagent起動成功を保証しません。

## 固定しているCodex仕様

検証はネットワーク上の最新仕様へ実行時に追従せず、次のOpenAI Codexリポジトリのスナップショットを固定して使用します。

- Codex commit: `7dae8c53d97e61cd774e4d6bcca5243c29ca615c`
- Schema source: `codex-rs/core/config.schema.json`
- Vendored file: `config/codex-config.schema.json`
- Reference: https://developers.openai.com/codex/config-reference/
- Subagents: https://developers.openai.com/codex/subagents/

これにより、CIはオフラインで再現でき、上流Schemaの更新だけで既存PRの検証結果が変わりません。

## 検証内容

- custom role固有の `name`、`description`、`developer_instructions` は非空文字列を必須とする。
- `name` は `agents/<name>.toml` のファイル名と一致させる。
- `model` は指定時のみ非空文字列を要求する。モデル名自体は固定リストで検証しない。
- `model_reasoning_effort` は、この仕様スナップショットで文書化されている `none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`、`ultra` を静的に許可する。実際に利用できる強度はモデルとクライアントに依存する。
- `sandbox_mode` とその他のCodex設定は固定Schemaで型・列挙値・未知キーを検証する。
- `model`、`model_reasoning_effort`、`sandbox_mode` を含む通常のCodex設定は、公式仕様で省略可能ならrole側でも省略を許可する。
- エラーには論理ファイルID、問題のキー、理由だけを含め、設定値は出力しない。

## Schema更新手順

Codex更新に合わせて検証基準を更新する場合だけ、次を同じPRで行います。

1. 採用する `openai/codex` commitを決める。
2. そのcommitの `codex-rs/core/config.schema.json` で `config/codex-config.schema.json` を置き換える。
3. この文書のcommit SHAと、必要に応じて `model_reasoning_effort` の許可値を更新する。
4. `python -m harness validate` と `python -m pytest -q` を実行する。
5. Schema更新とrole設定変更は分けてレビューできるよう、意図しないmodel・推論強度・sandbox変更を含めない。
