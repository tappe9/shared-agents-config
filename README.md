# shared-agents-config

AI コーディングエージェント向けの共通運用設定リポジトリ。

## 概要

チームで共通の `AGENTS.md` を管理し、各プロジェクトで一貫した AI エージェント運用を実現する。  
主に [Superpower スキル](https://github.com/codeape-io/superpowers)を使った開発フローを定義している。

## 使い方

### 各プロジェクトの AGENTS.md から参照する

プロジェクト固有の `AGENTS.md` の冒頭で、このリポジトリの内容を参照元として指定する。

```markdown
# AGENTS.md

共通ルール・スキル運用は [shared-agents-config](https://github.com/tappe9/shared-agents-config) の AGENTS.md に従う。

## プロジェクト固有の設定

（以下にプロジェクト固有のルールを記載）
```

### 直接コピーして使う

`AGENTS.md` をプロジェクトにコピーし、プロジェクト固有のセクションを追記する。
