# 設定リファレンス

## Secrets（GitHub リポジトリ設定）

| 名前 | 説明 |
|------|------|
| `LLM_API_KEY` | LLMのAPIキー。旧名 `OPENAI_API_KEY` も後方互換で利用可 |
| `GH_APP_ID` / `GH_APP_PRIVATE_KEY` | コメント投稿用 GitHub App の認証情報 |

> フォークPRにはSecretsは渡されません（GitHub Actionsの仕様）。

## `src/config.yaml`

実行時の挙動はすべてこのファイルで設定します。環境変数から参照するのは `LLM_API_KEY`（旧名可）と `GITHUB_TOKEN` のみです。

| キー | 説明 | デフォルト/例 |
|------|------|----|
| `model` | 使用モデル名（OpenRouterでは `プロバイダ名/モデル名` 形式） | `openai/gpt-5` |
| `base_url` | OpenAI互換エンドポイント。未設定ならOpenAI公式 | `https://openrouter.ai/api/v1` |
| `fallback_models` | `model` が利用不可のとき自動切替する代替モデルのリスト（OpenRouterのみ） | `["anthropic/claude-sonnet-5"]` |
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

`response_format`（JSON強制）や `max_completion_tokens` に未対応のプロバイダでは、自動的にパラメータを外して再試行します。

### OpenRouter のセットアップ手順

OpenRouter はキー1つで GPT / Claude / Gemini など複数のモデルを切り替えられるゲートウェイです。特定プロバイダのクォータ切れ時の避難先としても使えます。

1. **アカウント作成** — [openrouter.ai](https://openrouter.ai/) にサインアップ（Google/GitHubアカウント可）。
2. **クレジット購入** — [Credits](https://openrouter.ai/settings/credits) ページで残高をチャージ（従量課金。少額から可能）。
3. **APIキー発行** — [Keys](https://openrouter.ai/settings/keys) ページで「Create Key」。キーごとに利用上限額を設定できるので、CI用には上限を設けておくと安全です。発行されたキー（`sk-or-...`）は再表示できないため控えておきます。
4. **GitHubリポジトリに設定** — リポジトリの Settings → Secrets and variables → Actions で、`LLM_API_KEY` にキーを登録。
5. **config.yaml を変更**:

   ```yaml
   model: openai/gpt-5          # モデルは「プロバイダ名/モデル名」形式
   base_url: https://openrouter.ai/api/v1
   ```

   モデル名の例: `openai/gpt-5`, `anthropic/claude-sonnet-5`, `google/gemini-2.5-pro`。利用可能な一覧は [openrouter.ai/models](https://openrouter.ai/models) を参照。

利用状況・コストは [Activity](https://openrouter.ai/activity) ページで確認できます（Botからの呼び出しは `ai-review-bot` として表示されます）。

補足:

- `fallback_models` を設定すると、指定モデルが落ちている・レートリミット中のときにOpenRouterが自動で代替モデルに切り替えます。
- クレジット切れ（402）や認証エラー（401/403）の場合、CIは失敗せず、PRに通知コメントを投稿してスキップします。
