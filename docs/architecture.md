# 仕組みと運用

## 処理の流れ

1. PRの差分を取得し、`include_globs` / `exclude_globs` / `max_files` で対象を絞り込み
2. 差分を1つのプロンプトにまとめてLLMへ送信（`max_diff_chars` を超える分は切り詰め、その旨をモデルに通知）
3. JSON形式のレビュー結果をパースし、行位置を特定できた指摘はインラインコメント、それ以外はまとめコメントに振り分け
4. 既存コメントと重複しないものだけをPRに投稿
5. メンテナが `workflow_dispatch` で再実行可能

## ワークフロー構成

- [`self-ai-review.yml`](../.github/workflows/self-ai-review.yml) — トリガー役。ユニットテスト実行後、draft/フォークPR/Dependabotを除外して再利用ワークフローを呼び出します。
- [`ai-review.yml`](../.github/workflows/ai-review.yml) — 実処理（`workflow_call`）。`src/reviewer.py` を1回実行し、GitHub Appトークンでコメントを投稿します。`secrets: inherit` は使わず必要なシークレットのみ渡す設計です。

他リポジトリで使う場合は上記2ファイルをコピーし、`checkout` 対象とシークレット名を自リポジトリに合わせて調整してください。エントリポイントは単一の `src/reviewer.py`（`--repo` / `--pr` / `--prompt`）です。

## 安全な運用ポイント

- ⛔ マージ時は実行しない（`pull_request` のみ）
- 🛌 Draft PRはスキップ
- 🔐 SecretsはフォークPRへ渡さない
- 🛡️ `review_prompt` はenv経由で渡し、シェルインジェクションを防止
- 🔁 API呼び出しは429/5xx/接続エラーのみ指数バックオフで再試行（認証エラー等は即時失敗）
- 💳 APIクォータ切れ（`insufficient_quota`）時はCIを失敗させず、PRに通知コメントを1回だけ投稿してスキップ

## 依存関係の自動更新

- **Dependabot**（[設定](../.github/dependabot.yml)）: pip / GitHub Actions を毎週月曜9時（JST）にチェック。minor/patchは1つのPRにグループ化。
- **Mergify**（[設定](../.mergify.yml)）: テスト通過したDependabot PRをマージキュー経由でsquash自動マージ。利用には [Mergify GitHub App](https://github.com/apps/mergify) のインストールが必要です。

## 既知の制約

- コメントの重複防止はdiff position基準のため、PRに新しいコミットが積まれるとpositionがずれて重複コメントが発生することがあります。
