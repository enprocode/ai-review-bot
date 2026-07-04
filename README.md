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

1. **ワークフローをコピー** — [`self-ai-review.yml`](.github/workflows/self-ai-review.yml)（トリガー役）と [`ai-review.yml`](.github/workflows/ai-review.yml)（実処理）の2ファイルを自リポジトリに配置。
2. **Secretsを設定** — `LLM_API_KEY`（LLMのAPIキー。旧名 `OPENAI_API_KEY` も可）、GitHub App認証情報（`GH_APP_ID` / `GH_APP_PRIVATE_KEY`）。
3. **動作を調整** — [`src/config.yaml`](src/config.yaml) でモデル・対象ファイル・コメント形式などを設定。

```yaml
# config.yaml の最小例
model: gpt-5
enable_inline: true
fail_level: MAJOR
```

## ドキュメント

| ドキュメント | 内容 |
|------|------|
| [設定リファレンス](docs/configuration.md) | Secrets・config.yaml全キー・他プロバイダの使い方 |
| [仕組みと運用](docs/architecture.md) | 処理の流れ・ワークフロー構成・安全設計・既知の制約 |
| [開発ガイド](docs/development.md) | ローカル実行・テスト・ベストプラクティス |

## ライセンス

MIT License

## コントリビューション

Issue・PR歓迎です。レビュー観点の拡張や新しいモデル対応など、ぜひご協力ください。
