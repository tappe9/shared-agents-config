# shared-agents-config

Codex の個人環境で使う共通 `AGENTS.md`、サブエージェント定義、個人 skill、管理対象の設定 fragment の配布元です。

## 構成

- `AGENTS.md`: 常時必要な安全境界と skill routing
- `agents/`: 許可済みサブエージェント role
- `skills/implementing-repository-changes/`: 変更実行が承認された時だけ読む詳細な開発フロー
- `config/skills.config.toml`: 重複する user skill だけを無効化する merge 用 fragment
- `tests/`: skill の trigger matrix と検証記録

Supabase の schema 名やアプリ固有の禁止事項は、対象リポジトリの `AGENTS.md` で管理します。共通 `AGENTS.md` には置きません。

## 配布元と配置先

| 配布元 | 個人環境の配置先 | 同期方針 |
|---|---|---|
| `AGENTS.md` | `/Users/tapppe/.codex/AGENTS.md` | common prefix として同期 |
| `agents/*.toml` | `/Users/tapppe/.codex/agents/*.toml` | ファイル単位で同期 |
| `skills/<name>/` | `/Users/tapppe/.agents/skills/<name>/` | directory 単位で同期 |
| `config/skills.config.toml` | `/Users/tapppe/.codex/config.toml` | 対象の `[[skills.config]]` だけを merge |

個人環境側を直接編集せず、このリポジトリを原本として更新してから反映します。ただし、Obsidian Vault path のような端末固有情報は `~/.codex/AGENTS.md` の local-only suffix として保持し、このリポジトリへ追加しません。

個人 skill の原本は意図的に `skills/` に置きます。`.agents/skills/` にも置くと、この管理リポジトリ内では repo scope と user scope から同名 skill が二重検出されるためです。

`config/skills.config.toml` は `~/.codex/config.toml` を置き換える完全な設定ファイルではありません。MCP、plugin、project trust、通知、認証、その他の端末固有設定をこのリポジトリへコピーせず、管理対象の配列要素だけを既存設定へ merge します。

## Superpowers の実行元

Codex Desktop では `/Users/tapppe/.codex/plugins/cache/openai-curated-remote/superpowers/6.4.1` を唯一の Superpowers runtime source とします。

- legacy symlink `/Users/tapppe/.agents/skills/superpowers` は再作成しない
- standalone の `brainstorming`、`requesting-code-review`、`skill-creator` は `config/skills.config.toml` で無効化する
- standalone CLI の marketplace snapshot 5.1.3 は導入しない
- skill inventory はセッション開始時に確定するため、設定反映後は Codex Desktop を再起動し、新規セッションで source path と重複の有無を確認する

## 同期確認

`implementing-repository-changes` の source と配置先は次で一致を確認します。

```bash
diff -qr \
  /Users/tapppe/Documents/GitHub/shared-agents-config/skills/implementing-repository-changes \
  /Users/tapppe/.agents/skills/implementing-repository-changes
```

`agents/*.toml` は対応する `/Users/tapppe/.codex/agents/*.toml` と `cmp -s` で確認します。`AGENTS.md` は common prefix の一致と、local-only suffix が重複していないことを別々に検証します。

## Backup と rollback

反映前に `~/.codex/AGENTS.md` と `~/.codex/config.toml` を timestamp 付き directory へ保存します。新規 skill は directory 単位で識別し、legacy symlink は target の `readlink` 結果と symlink 自体を保存します。値や秘密情報はログや Git に出力しません。

rollback では保存した設定ファイルを戻し、新規追加した skill directory を明示的に退避し、必要な場合だけ保存済み symlink を元位置へ戻します。古い backup を上書きするだけでは新規追加ファイルは消えないため、復元対象を個別に確認します。復元後も Codex Desktop を再起動して fresh session と strict diagnostics で確認します。
