# 仕組みと運用

## 処理の流れ

0. レビュー済みコミット（コメント内の不可視マーカーで記録）はスキップ。追加pushの場合は前回レビュー以降に変更されたファイルのみレビュー（増分レビューによるトークン節約）
1. PRの差分を取得し、`include_globs` / `exclude_globs` / `max_files` で対象を絞り込み
2. 差分を1つのプロンプトにまとめてLLMへ送信（`max_diff_chars` を超える分は切り詰め、その旨をモデルに通知）
3. JSON形式のレビュー結果をパースし、行位置を特定できた指摘はインラインコメント、それ以外はまとめコメントに振り分け
4. 既存コメントと重複しないものだけをPRに投稿
5. メンテナが `workflow_dispatch` で再実行可能

## ワークフロー構成

- [`self-ai-review.yml`](../.github/workflows/self-ai-review.yml) — このリポジトリ自身専用のトリガー役。ユニットテスト実行後、draft/フォークPR/Dependabotを除外して再利用ワークフローを呼び出します。
- [`ai-review.yml`](../.github/workflows/ai-review.yml) — 実処理（`workflow_call`）。呼び出し元とは別に `enprocode/ai-review-bot` 自体をcheckoutして `src/reviewer.py` を1回実行し、標準の `GITHUB_TOKEN`（`github-actions[bot]`名義）でコメントを投稿します。`secrets: inherit` は使わず必要なシークレットのみ渡す設計です。GitHub Appの作成・インストールは不要です。

`ai-review.yml` は他リポジトリからの直接参照（`uses: enprocode/ai-review-bot/.github/workflows/ai-review.yml@<tag>`）を前提に設計されています。呼び出し元は `src/` や `ai-review.yml` 自体をコピーする必要はなく、[`examples/caller-workflow.yml`](../examples/caller-workflow.yml) のような薄いワークフロー1枚だけで動作します。エントリポイントは単一の `src/reviewer.py`（`--repo` / `--pr` / `--prompt` / `--config-override`）です。

設定はデフォルトで `enprocode/ai-review-bot` 側の `src/config.yaml` を全呼び出し元で共有します。呼び出し元リポジトリごとにモデル・`fail_level`・対象globなどを変えたい場合は、`with.config_path` で自リポジトリ内の上書きファイルを指定してください（[`examples/ai-review-config.example.yml`](../examples/ai-review-config.example.yml) 参照、詳細は [設定リファレンス](configuration.md)）。`caller` パスにcheckoutされた呼び出し元リポジトリ内のファイルを `load_config()` がマージします。

## 安全な運用ポイント

- マージ時は実行しない（`pull_request` のみ）
- Draft PRはスキップ
- SecretsはフォークPRへ渡さない
- `review_prompt` はenv経由で渡し、シェルインジェクションを防止
- API呼び出しは408/5xx/接続エラーのみ指数バックオフで再試行（認証エラー等は即時失敗）。OpenAI SDK自体のリトライは `max_retries=1` に制限し、多重リトライによる待ち時間の浪費を防止
- レートリミット（429）は `Retry-After` 秒数（最大60秒）を待って同一モデルへ最大2回まで自動再試行し、それでも解消しなければ次の候補モデルへ切り替える
- クレジット/クォータ切れ・認証エラー・再試行し尽くしたレートリミット（`skip_reason()` で判定）はCIを失敗させず、PRに通知コメントを1回だけ投稿してスキップ

## 依存関係の自動更新

- **Dependabot**（[設定](../.github/dependabot.yml)）: pip / GitHub Actions を毎週月曜9時（JST）にチェック。minor/patchは1つのPRにグループ化。
- **Mergify**（[設定](../.github/.mergify.yml)）: テスト通過したDependabot PRをマージキュー経由でsquash自動マージ。利用には [Mergify GitHub App](https://github.com/apps/mergify) のインストールが必要です。

## リリースの自動化

[`VERSION`](../VERSION) ファイルの変更がmainにマージされると、[`release.yml`](../.github/workflows/release.yml) がパッチタグ作成・メジャー浮動タグ（`@1` 等）のforce-move・GitHub Release作成を自動で行います。手順や運用ルールは [開発ガイド](development.md#リリース手順メンテナ向け) を参照してください。

## 誤検知の抑制

差分ベースレビューの典型的な誤検知（差分外のインポートや設定キーを「存在しない」と断定する、行の移動を削除と誤認する等）を防ぐため、2段階の対策を行っています。

1. **プロンプトでの注意喚起**: `build_prompt()` に、差分外のコードの不在を断定しないこと・行の移動を削除と誤認しないこと・推測ベースの指摘をしないことを明示。
2. **ファイル全文での再検証（`verify_findings_with_file_contents()`）**: 全severityの指摘を投稿前に、該当ファイルのHEAD時点の全文を取得し、その全文を根拠に指摘が依然として正しいかを別途LLMに確認させます。「ファイル内の具体的な行を根拠に断定できる」場合のみvalidと判定させ、推測ベース（「〜の可能性がある」等）・設計の好み・一般論は破棄します。全文取得や検証自体に失敗した場合も破棄します（見逃しより誤検知防止を優先するfail-closed設計）。
3. **推測表現の決定論的フィルタ（`drop_speculative_findings()`）**: 「〜の可能性がある」「〜かもしれない」等の推測表現をタイトル/詳細に含む指摘は、LLMの判定を経ずにコード側で必ず破棄します。断定できる指摘（「〜が発生します」等）のみが次の再検証に進みます。
4. **却下済み指摘の再出現抑止（`fetch_dismissed_titles()`）**: 過去にレビュアーが「変更なし」と返信して却下した指摘のタイトルを収集し、再検証プロンプトに渡します。表現が変わっていても同趣旨の指摘は自動的に破棄されるため、同じ誤検知が繰り返し投稿されることを防ぎます。

また、LLM呼び出しには [OpenRouterのStructured Outputs](https://openrouter.ai/docs/features/structured-outputs)（strict JSONスキーマ強制）を使用し、JSON不遵守の出力を構造的に防ぎます。未対応プロバイダでは `json_object` → 無指定へ段階的にフォールバックし、それでも出力がJSON形式に従わないモデルは `fallback_models` の候補へ自動的に切り替えます。

なお、LLMベースである以上、誤検知を完全にゼロにする保証はありません。上記の再検証はあくまで発生率を大幅に下げる仕組みです。

## トークン消費の抑制（増分レビュー）

- レビュー投稿時、コミットSHAを不可視マーカー（`<!-- ai-review-bot:reviewed:<sha> -->`）としてコメント本文に埋め込みます。
- 次回実行時、HEADが前回レビュー済みSHAと同じならAPI呼び出し自体をスキップします。
- 追加pushの場合は `repo.compare(last_sha, head_sha)` で前回レビュー以降に変更されたファイルのみを対象にします（差分取得に失敗した場合は全ファイルにフォールバック）。
- 途中で出力が切れてもJSONの完全なオブジェクトだけを回収する `salvage_findings()` により、再送信（トークンの再消費）を避けます。
- トークン上限による打ち切り（`finish_reason=length`）は同一リクエストを再送しても結果が変わらないため、再試行せず打ち切ります。
- すべてのLLM呼び出しでトークン使用量（prompt/completion/total）をCIログに記録し、コストを可視化します。

## 既知の制約

- コメントの重複防止はdiff position基準のため、PRに新しいコミットが積まれるとpositionがずれて重複コメントが発生することがあります。
- 無料モデル（`:free`）はJSON形式の遵守率が低く、複数の `fallback_models` を試すことでレイテンシが伸びる場合があります。安定運用にはクレジットを積んだ有料モデルを推奨します（[docs/configuration.md](configuration.md) 参照）。
- トラブルシューティングは [docs/troubleshooting.md](troubleshooting.md) を参照してください。
