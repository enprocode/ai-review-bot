# 設定リファレンス

## Secrets（GitHub リポジトリ設定）

| 名前 | 説明 |
|------|------|
| `LLM_API_KEY` | LLMのAPIキー。旧名 `OPENAI_API_KEY` も後方互換で利用可 |
| `GH_APP_ID` / `GH_APP_PRIVATE_KEY` | コメント投稿用 GitHub App の認証情報 |

> 🔒 フォークPRにはSecretsは渡されません（GitHub Actionsの仕様）。

## `src/config.yaml`

実行時の挙動はすべてこのファイルで設定します。環境変数から参照するのは `LLM_API_KEY`（旧名可）と `GITHUB_TOKEN` のみです。

| キー | 説明 | デフォルト/例 |
|------|------|----|
| `model` | 使用モデル名 | `gpt-5` |
| `base_url` | OpenAI互換エンドポイント。未設定ならOpenAI公式 | `https://openrouter.ai/api/v1` |
| `system_prompt` | レビューの基本方針 | （config.yaml参照） |
| `style` | レビューのトーン | `concise` |
| `max_tokens` | 出力トークン数上限 | `800` |
| `enable_inline` | `true`: インラインコメント / `false`: まとめコメントのみ | `true` |
| `fail_level` | このレベル以上の指摘でCI失敗（`CRITICAL`/`MAJOR`/`MINOR`/`SUGGESTION`、未設定なら無効） | `MAJOR` |
| `include_globs` / `exclude_globs` | レビュー対象/除外パターン | `**/*.py` |
| `max_files` | 1PRあたりの対象ファイル数上限 | `200` |
| `max_diff_chars` | LLMに渡すdiffの文字数上限（超過分は切り詰め） | `8000` |
| `max_findings` | 指摘の最大件数 | `50` |
| `batch_size` | インラインコメントの1レビューあたり投稿件数 | `20` |
| `log_level` | ログレベル | `INFO` |

## OpenAI以外のプロバイダを使う

`base_url` にOpenAI互換エンドポイントを指定するだけで、OpenRouter / Azure OpenAI / Groq / Ollama 等が使えます。APIキーは `LLM_API_KEY` に使用プロバイダのものを設定してください。

例: OpenRouter経由でClaudeを使う場合

```yaml
model: anthropic/claude-sonnet-5
base_url: https://openrouter.ai/api/v1
```

`response_format`（JSON強制）や `max_completion_tokens` に未対応のプロバイダでは、自動的にパラメータを外して再試行します。
