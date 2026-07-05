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

1. **ワークフローを1枚配置** — [`examples/caller-workflow.yml`](examples/caller-workflow.yml) を参考に、自リポジトリに `.github/workflows/ai-review.yml` として配置。`uses:` はタグ（`@v1.0.0` 等）かコミットSHAで固定してください（`@main` は最新コミットを都度取得するため非推奨）。
2. **Secretsを設定** — `LLM_API_KEY`（LLMのAPIキー。旧名 `OPENAI_API_KEY` も可）だけでOK。コメントは標準の `GITHUB_TOKEN` で投稿されるため、GitHub Appの作成・インストールは不要です（独自の名前で投稿したい場合のみ任意で `GH_APP_ID` / `GH_APP_PRIVATE_KEY` を追加できます）。
3. **必要なら設定を上書き** — [`examples/ai-review-config.example.yml`](examples/ai-review-config.example.yml) を参考に、自リポジトリに設定上書きファイル（例: `.github/ai-review-config.yml`）を作成し、caller workflow の `with.config_path` で指定。モデル・`fail_level`・対象ファイルglob等をリポジトリごとに変更できます（省略時はBot既定の設定を使用）。

```yaml
# .github/ai-review-config.yml の例（このリポジトリ向けだけの上書き）
model: anthropic/claude-sonnet-5
fail_level: CRITICAL
include_globs: ["**/*.ts", "**/*.tsx"]
```

> このリポジトリ自身（enprocode/ai-review-bot）のように、Bot本体を開発・カスタマイズしたい場合は [`docs/development.md`](docs/development.md) を参照してください。

## ドキュメント

| ドキュメント | 内容 |
|------|------|
| [設定リファレンス](docs/configuration.md) | Secrets・config.yaml全キー・他プロバイダの使い方 |
| [仕組みと運用](docs/architecture.md) | 処理の流れ・ワークフロー構成・安全設計・既知の制約 |
| [開発ガイド](docs/development.md) | ローカル実行・テスト・ベストプラクティス |
| [トラブルシューティング](docs/troubleshooting.md) | Botのコメント別の原因と対処 |

## ライセンス

MIT License

## コントリビューション

Issue・PR歓迎です。レビュー観点の拡張や新しいモデル対応など、ぜひご協力ください。
