# AI Review Bot
[![Self AI Review](https://github.com/enprocode/ai-review-bot/actions/workflows/self-ai-review.yml/badge.svg)](https://github.com/enprocode/ai-review-bot/actions/workflows/self-ai-review.yml)

GitHub Actions ベースの AIコードレビューBot です。
Pull Request の差分をLLMで解析し、バグリスク・設計・可読性などの指摘を自動でコメントします。

## 主な機能

- PRごとに自動コードレビューコメントを投稿（インライン/まとめの切替可）
- OpenAIだけでなく、OpenAI互換プロバイダ（OpenRouter / Azure / Groq / Ollama等）に対応
- フォークPR・Draft PR・マージ時は実行しないセーフ設計
- 指摘の重大度に応じてCIを失敗させる `fail_level` 設定

## クイックスタート

他のリポジトリからは、このBotのコードを一切コピーせず、ワークフロー1枚を置くだけで使えます。

### 1. ワークフローを配置

自リポジトリに `.github/workflows/ai-review.yml` を作成し、以下を貼り付けます（[`examples/caller-workflow.yml`](examples/caller-workflow.yml) と同内容）。`uses:` の `@1` はメジャーバージョンの浮動タグで、リリースのたびにメンテナが最新のマイナー/パッチへ指し直すため、一度設置すれば以後の更新でワークフローを書き換える必要はありません（`actions/checkout@v4` などと同じ慣例）。破壊的変更が入る場合はメジャーバージョンが上がり、`@1` を使い続ける限り自動では追従しません。ビルドを完全に固定したい場合はパッチバージョン（例: `@1.1.0`、`v`プレフィックスなし）かコミットSHAを指定してください（`@main` は任意のコミットが即座に反映されるため非推奨）。利用可能なタグは [Tags](https://github.com/enprocode/ai-review-bot/tags) を参照してください。

```yaml
name: AI Review

on:
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review]

concurrency:
  group: ${{ format('{0}-{1}', github.workflow, github.event.pull_request.number) }}
  cancel-in-progress: true

permissions:
  contents: read
  pull-requests: write

jobs:
  ai-review:
    # フォーク/Draft PRやDependabotは除外（Secretsが渡らない・渡すべきでないため）
    if: ${{ github.actor != 'dependabot[bot]' && github.event.pull_request.draft == false && github.event.pull_request.head.repo.full_name == github.repository }}
    uses: enprocode/ai-review-bot/.github/workflows/ai-review.yml@1
    secrets:
      # 必須はこれだけ。コメントは標準の GITHUB_TOKEN（github-actions[bot]）で投稿される
      LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
```

### 2. Secretsを設定

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で `LLM_API_KEY` を1つ登録するだけです。GitHub Appの作成・インストールは不要です。

> ⚠️ **既定モデル（`openai/gpt-5-mini`）は [OpenRouter](https://openrouter.ai/) 経由で呼び出す設定になっています。** そのため `LLM_API_KEY` には **OpenAI公式ではなくOpenRouterのAPIキー**（`sk-or-...`）を設定してください。取得手順は[OpenRouterのセットアップ手順](docs/configuration.md#openrouter-のセットアップ手順)を参照。OpenAI公式や他プロバイダを使いたい場合は次の「設定を上書き」で `base_url` を変更できます。

### 3. 動作確認

適当なPRを作成すると、数分以内にBotからレビューコメントが投稿されます（Actionsタブでワークフローの実行状況を確認できます）。指摘がなければ「LGTM! 🎉」とコメントされます。

### 4. 必要なら設定を上書き（任意）

自リポジトリに設定上書きファイル（例: `.github/ai-review-config.yml`）を作成し、手順1のワークフローに `with.config_path: .github/ai-review-config.yml` を追加すると、モデル・`fail_level`・対象ファイルglob等をリポジトリごとに変更できます（省略時はBot既定の設定を使用）。[`examples/ai-review-config.example.yml`](examples/ai-review-config.example.yml) も参照してください。

```yaml
# .github/ai-review-config.yml の例（このリポジトリ向けだけの上書き）
model: gpt-5-mini
base_url: ""          # 空にするとOpenAI公式を直接使う（この場合 LLM_API_KEY はOpenAIのキー）
fallback_models: []   # 既定値はOpenRouter向けのモデル名なのでOpenAI公式利用時は空にする
fail_level: CRITICAL
include_globs: ["**/*.ts", "**/*.tsx"]
```

> このリポジトリ自身（enprocode/ai-review-bot）のように、Bot本体を開発・カスタマイズしたい場合は [`docs/development.md`](docs/development.md) を参照してください。

## ドキュメント

| ドキュメント | 内容 |
|------|------|
| [設定リファレンス](docs/configuration.md) | Secrets・config.yaml全キー・他プロバイダの使い方 |
| [仕組みと運用](docs/architecture.md) | 処理の流れ・ワークフロー構成・安全設計・既知の制約 |
| [開発ガイド](docs/development.md) | ローカル実行・テスト・ベストプラクティス・リリース手順 |
| [トラブルシューティング](docs/troubleshooting.md) | Botのコメント別の原因と対処 |

## ライセンス

MIT License

## コントリビューション

Issue・PR歓迎です。レビュー観点の拡張や新しいモデル対応など、ぜひご協力ください。
