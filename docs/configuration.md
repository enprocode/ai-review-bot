# 設定リファレンス

## Secrets（GitHub リポジトリ設定）

| 名前 | 説明 |
|------|------|
| `LLM_API_KEY` | LLMのAPIキー。旧名 `OPENAI_API_KEY` も後方互換で利用可 |

コメントは標準の `GITHUB_TOKEN`（`github-actions[bot]`名義）で投稿するため、GitHub Appの作成・インストールは不要です。

> フォークPRにはSecretsは渡されません（GitHub Actionsの仕様）。

## `src/config.yaml`

実行時の挙動はすべてこのファイルで設定します。環境変数から参照するのは `LLM_API_KEY`（旧名可）と `GITHUB_TOKEN` のみです。

| キー | 説明 | デフォルト/例 |
|------|------|----|
| `model` | 使用モデル名（OpenRouterでは `プロバイダ名/モデル名` 形式） | `openai/gpt-5` |
| `base_url` | OpenAI互換エンドポイント。未設定ならOpenAI公式 | `https://openrouter.ai/api/v1` |
| `fallback_models` | `model` が利用不可・出力がJSON形式に従わないときに自動切替する代替モデルのリスト | `["anthropic/claude-sonnet-5"]` |
| `reasoning_effort` | 推論モデルの思考トークン量（`low`/`medium`/`high`）。未対応モデルでは自動で外して再試行 | `low` |
| `language` | レビューコメントの言語。未設定なら日本語 | `日本語` / `English` |
| `system_prompt` | レビューの基本方針 | （config.yaml参照） |
| `style` | レビューのトーン | `concise` |
| `language` | レビューコメントの言語。未設定なら日本語 | `日本語` / `English` |
| `max_tokens` | 出力トークン数上限（推論モデルは思考トークンもここから消費） | `1500` |
| `reasoning_effort` | 推論モデルの思考トークン量（`low`/`medium`/`high`）。未対応モデルでは自動で外して再試行 | `low` |
| `enable_inline` | `true`: インラインコメント / `false`: まとめコメントのみ | `true` |
| `fail_level` | このレベル以上の指摘でCI失敗（`CRITICAL`/`MAJOR`/`MINOR`/`SUGGESTION`、未設定なら無効） | `MAJOR` |
| `include_globs` / `exclude_globs` | レビュー対象/除外パターン | `**/*.py` |
| `max_files` | 1PRあたりの対象ファイル数上限 | `200` |
| `max_diff_chars` | LLMに渡すdiffの文字数上限（超過分は切り詰め） | `4000` |
| `max_findings` | 指摘の最大件数（モデルへの指示にも反映） | `10` |
| `batch_size` | インラインコメントの1レビューあたり投稿件数 | `20` |
| `log_level` | ログレベル | `INFO` |

## 複数リポジトリでの使い回しとリポジトリごとの設定上書き

`ai-review.yml` を `uses: enprocode/ai-review-bot/.github/workflows/ai-review.yml@<tag>` で参照して使う場合、既定では全呼び出し元リポジトリが `enprocode/ai-review-bot` 側の `src/config.yaml` を共有します。リポジトリごとに `model` / `fail_level` / `include_globs` 等を変えたい場合は次の手順で上書きできます。

1. 呼び出し元リポジトリに上書き用YAMLファイルを作成（例: `.github/ai-review-config.yml`）。上書きしたいキーだけを書けばよく、書かなかったキーはBot既定値のまま使われます（[`examples/ai-review-config.example.yml`](../examples/ai-review-config.example.yml) 参照）。
2. 呼び出し元ワークフローの `with.config_path` にそのファイルへの相対パスを指定（[`examples/caller-workflow.yml`](../examples/caller-workflow.yml) 参照）。
3. `ai-review.yml` は呼び出し元リポジトリを `caller/` にcheckoutし、`caller/<config_path>` を `src/reviewer.py --config-override` に渡します。`load_config()` はBot既定の設定に対してこのファイルの内容を上書き（shallow merge）します。

`llm_api_key` / `github_token` はSecrets経由で渡されるため、上書きファイルに書く必要はありません（書いても無視されます）。

### `language` だけはワークフローの `with:` からも指定可能

`language`（レビューコメントの言語）だけは利用頻度が高いため、上書きファイルを作らずに呼び出し元ワークフローの `with.language` で直接指定できます（[`examples/caller-workflow.yml`](../examples/caller-workflow.yml) 参照）。

```yaml
with:
  language: English   # 例: English / 한국어。未指定なら config.yaml の設定（既定は日本語）
```

`with.language` は `config_path` で指定した上書きファイル内の `language` よりも優先されます。

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
   `openai/gpt-latest` のようなエイリアスを使うと、コード変更なしに最新版へ自動追従します（[OpenRouter Quickstart](https://openrouter.ai/docs/quickstart)参照）。

利用状況・コストは [Activity](https://openrouter.ai/activity) ページで確認できます（Botからの呼び出しは `ai-review-bot` として表示されます）。

補足:

- `fallback_models` を設定すると、指定モデルが落ちている・レートリミット中のときにOpenRouterが自動で代替モデルに切り替えます。
- クレジット切れ（402）や認証エラー（401/403）の場合、CIは失敗せず、PRに通知コメントを投稿してスキップします。

### 無料モデルを使う場合の注意

OpenRouterにはモデル名に `:free` が付く無料モデル（例: `deepseek/deepseek-chat-v3:free`）があり、クレジット消費なしでレビューを回せます。ただし以下に注意してください。

- **無料モデルはリクエスト内容がプロバイダの学習データに使われます。** このBotはPRの差分コードを丸ごと送信するため、プライベートリポジトリや業務コードでは無料モデルを使わないでください。
- 無料枠はレート制限が厳しめです。$10以上のクレジットを保有すると1日1,000リクエストまで緩和されます（このBotはPRあたり1リクエスト）。

使い分けの目安: 公開リポジトリでのお試しは無料モデル、業務利用はクレジットをチャージして有料モデル。
