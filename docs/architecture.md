# 仕組みと運用

## 処理の流れ

0. レビュー済みコミット（コメント内の不可視マーカーで記録）はスキップ。追加pushの場合は前回レビュー以降に変更されたファイルのみレビュー（増分レビューによるトークン節約）
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

- マージ時は実行しない（`pull_request` のみ）
- Draft PRはスキップ
- SecretsはフォークPRへ渡さない
- `review_prompt` はenv経由で渡し、シェルインジェクションを防止
- API呼び出しは408/5xx/接続エラーのみ指数バックオフで再試行（認証エラー等は即時失敗）。OpenAI SDK自体のリトライは `max_retries=1` に制限し、多重リトライによる待ち時間の浪費を防止
- レートリミット（429）は `Retry-After` 秒数（最大60秒）を待って同一モデルへ最大2回まで自動再試行し、それでも解消しなければ次の候補モデルへ切り替える
- クレジット/クォータ切れ・認証エラー・再試行し尽くしたレートリミット（`skip_reason()` で判定）はCIを失敗させず、PRに通知コメントを1回だけ投稿してスキップ

## 依存関係の自動更新

- **Dependabot**（[設定](../.github/dependabot.yml)）: pip / GitHub Actions を毎週月曜9時（JST）にチェック。minor/patchは1つのPRにグループ化。
- **Mergify**（[設定](../.mergify.yml)）: テスト通過したDependabot PRをマージキュー経由でsquash自動マージ。利用には [Mergify GitHub App](https://github.com/apps/mergify) のインストールが必要です。

## 誤検知の抑制

差分ベースレビューの典型的な誤検知（差分外のインポートや設定キーを「存在しない」と断定する、行の移動を削除と誤認する等）を防ぐため、2段階の対策を行っています。

1. **プロンプトでの注意喚起**: `build_prompt()` に、差分外のコードの不在を断定しないこと・行の移動を削除と誤認しないこと・推測ベースの指摘をしないことを明示。
2. **ファイル全文での再検証（`verify_high_severity_findings()`）**: CRITICAL/MAJORの指摘は投稿前に、該当ファイルのHEAD時点の全文を取得し、その全文を根拠に指摘が依然として正しいかを別途LLMに確認させます。全文取得に失敗した場合、または「valid」と確認できなかった場合は、その指摘を破棄します（安全側に倒す設計）。SUGGESTION/MINORはトークン節約のため対象外です。

また出力がJSON形式に従わないモデルは `fallback_models` の候補へ自動的に切り替えます（`normalize_findings` が空/パース不能な出力を返した場合に次の候補モデルへフォールバック）。

なお、LLMベースである以上、誤検知を完全にゼロにする保証はありません。上記の再検証はあくまで発生率を大幅に下げる仕組みです。

## トークン消費の抑制（増分レビュー）

- レビュー投稿時、コミットSHAを不可視マーカー（`<!-- ai-review-bot:reviewed:<sha> -->`）としてコメント本文に埋め込みます。
- 次回実行時、HEADが前回レビュー済みSHAと同じならAPI呼び出し自体をスキップします。
- 追加pushの場合は `repo.compare(last_sha, head_sha)` で前回レビュー以降に変更されたファイルのみを対象にします（差分取得に失敗した場合は全ファイルにフォールバック）。
- 途中で出力が切れてもJSONの完全なオブジェクトだけを回収する `salvage_findings()` により、再送信（トークンの再消費）を避けます。

## 既知の制約

- コメントの重複防止はdiff position基準のため、PRに新しいコミットが積まれるとpositionがずれて重複コメントが発生することがあります。
- 無料モデル（`:free`）はJSON形式の遵守率が低く、複数の `fallback_models` を試すことでレイテンシが伸びる場合があります。安定運用にはクレジットを積んだ有料モデルを推奨します（[docs/configuration.md](configuration.md) 参照）。
- トラブルシューティングは [docs/troubleshooting.md](troubleshooting.md) を参照してください。
