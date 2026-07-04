# トラブルシューティング

Botが投稿するコメント別に、原因と対処をまとめます。

## 「⚠️ APIのクレジット/クォータ切れ のためレビューをスキップしました」

- **原因**: `skip_reason()` がHTTP 402、または `insufficient_quota` / `insufficient credit` 系のエラーメッセージを検知。
- **対処**: 使用中のプロバイダ（OpenAI/OpenRouter等）でクレジットを補充する。OpenRouterの場合は [Credits](https://openrouter.ai/settings/credits) を確認。コード側の対応は不要。

## 「⚠️ APIキーの認証エラー のためレビューをスキップしました」

- **原因**: HTTP 401/403。`LLM_API_KEY` が未設定、無効、または `base_url` との組み合わせが誤っている（例: OpenAIのキーをOpenRouterのbase_urlに向けている）。
- **対処**: リポジトリSecretsの `LLM_API_KEY` と `src/config.yaml` の `base_url` の組み合わせを確認する。

## 「⚠️ APIのレートリミット のためレビューをスキップしました」

- **原因**: HTTP 429（クレジット切れ以外）。無料モデルは特に上流プロバイダ側で頻繁に発生します。
- **対処**: 時間をおいて `workflow_dispatch` で再実行する。頻発する場合は `fallback_models` に別プロバイダのモデルを追加するか、有料モデルに切り替える。

## 「モデルから有効な応答が得られませんでした」

- **原因**: `model` と `fallback_models` の全候補で、空応答または出力がJSON形式に従わなかった。ログに各候補モデルの `finish_reason` や出力冒頭300文字が残っています。
  - `finish_reason=length` の場合は `max_tokens` 不足（推論モデルは思考トークンも消費するため、`reasoning_effort: low` を確認）。
  - 出力が英語の説明文で始まる場合は、モデルがJSON指示に従っていません（無料モデルで発生しやすい）。
- **対処**: ワークフローのログで実際の出力を確認し、`fallback_models` の順序を出力が安定するモデルに入れ替える。有料モデルへの切り替えが最も確実。

## AIレビューの指摘が明らかな誤検知

- **典型例**: 差分に写っていないコード（インポート文、既存のフォールバック処理等）を「存在しない」と断定する、行の移動を削除と誤認する。
- **背景**: プロンプトに誤検知防止の注意事項を含めていますが（[reviewer.py](../src/reviewer.py) の `build_prompt()`）、無料モデルでは完全には防げません。
- **対処**: 誤検知はコード修正せず、PRスレッドに理由を返信して解決（resolve）する。頻発する場合は `fail_level` を `CRITICAL` に緩めるか、`enable_inline: false` でまとめコメントのみにする。

## 同じコミットに何度もコメントが付く/レビューが実行されない

- **原因**: レビュー済みコミットは不可視マーカー（`<!-- ai-review-bot:reviewed:<sha> -->`）で記録され、同一HEADへの再実行はスキップされます（意図した挙動）。
- **確認方法**: ログに「HEAD `<sha>` は前回レビュー済みのためスキップします。」と出力されます。新しいレビューが必要な場合は新しいコミットをpushするか `workflow_dispatch` で強制実行してください。

## CIの `self / ai_review` が失敗する

- `fail_level`（デフォルト `MAJOR`）以上の指摘があると、意図的にCIを失敗させます（[maybe_fail_job()](../src/reviewer.py)）。バグではありません。
- 誤検知続きでCIを赤くしたくない場合は `fail_level` を `CRITICAL` にするか未設定にする。
