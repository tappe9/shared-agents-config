# Skillの静的検証

## 目的と対象

Git追跡済みの管理対象Skill `skills/<name>/SKILL.md` を、端末へ配布する前にローカルの `harness validate` とCIで検査します。外部pluginやuser Skillは対象に含みません。検証基準は一次資料の固定revisionに基づき、実行時にネットワークから最新仕様を取得しません。

今回の検査対象は、必須の `name` と `description`、管理ディレクトリとの一致、および既存のYAML構文・重複キー・参照先検査です。Agent Skills仕様全体を網羅する検証ではありません。

## 固定している仕様

基準にした一次資料は次のrevisionです。

- 公開仕様: https://agentskills.io/specification
- 仕様原文: [agentskills/agentskills docs/specification.mdx at revision 83021e2be457a9b6679148719c1f6074f0ad975e](https://github.com/agentskills/agentskills/blob/83021e2be457a9b6679148719c1f6074f0ad975e/docs/specification.mdx)
- 参照validator: [同revisionの `skills-ref/src/skills_ref/validator.py`](https://github.com/agentskills/agentskills/blob/83021e2be457a9b6679148719c1f6074f0ad975e/skills-ref/src/skills_ref/validator.py)

| 項目 | 検査内容 |
|---|---|
| 必須項目 | `name` と `description` は空白だけでない文字列 |
| `name` の長さ | YAML解析後の元の文字列で1〜64文字 |
| `name` の文字 | Unicode英数字またはASCIIの `-` のみ |
| `name` の大小文字 | `name == name.lower()` を満たす |
| `name` のハイフン | 先頭・末尾の `-` と連続した `--` を禁止 |
| `description` の長さ | YAML解析後の元の文字列で1〜1024文字 |
| ディレクトリ名 | `name` と `skills/<name>/` の名前が完全一致 |
| 重複 | 有効なSkill間で `name` が重複しない |

長さはバイト数やtoken数ではなくPython文字列の `len()` で数えます。日本語などのUnicode文字を許可します。改行や末尾空白も、YAMLから得た文字列に含まれる場合は長さに含みます。

参照validatorは `name` の前後空白除去やNFKC正規化を行いますが、本ハーネスではその補正に追従しません。ディレクトリ名との完全一致を保つため、元の値で検証します。必須項目の違反、YAML解析失敗、重複キーなどは固定診断だけを出し、入力値やYAML例外の内容は表示しません。

## 必須要件と推奨事項

未知のfrontmatter項目や任意のmetadataは許容し、追加の互換性フィールドを必須にしません。本文の行数にも上限を設けません。

仕様や運用上の推奨に従うと保守しやすくなりますが、500行未満の本文などの推奨事項だけを理由に有効なSkillを拒否しません。推奨事項はこの検証のエラー条件ではありません。

## 検証の限界

この検査は原本の静的な構造と必須フィールドを検証します。実際のSkill選択、roleやモデルの起動、プロンプトに対するモデルの挙動、実端末での適用結果は確認しません。それらの実動作確認は静的検証とは別に行います。

## ローカルコマンド

Gitルートで次を実行します。

### Windows / PowerShell

```powershell
.\.venv\Scripts\python.exe -m harness validate
```

### macOS

```bash
./.venv/bin/python -m harness validate
```

validateが `invalid-skill` を返した場合、配布・同期の既存経路がその問題をblockerとして扱います。
