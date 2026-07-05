# 開発ガイド

## セットアップとテスト

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip -r requirements.txt

# ユニットテスト実行
python -m unittest discover -s tests

# ローカルでレビューを試す（LLM_API_KEY / GITHUB_TOKEN が必要）
python src/reviewer.py --repo owner/repo --pr 123
```

> `act` コマンドでGitHub Actionsをローカルエミュレートすることも可能です。

## ベストプラクティス

- 小さなPR単位でレビュー品質UP
- コーディング規約・Lint設定を `system_prompt` に反映
- 大規模リポジトリは `include_globs` / `exclude_globs` で対象を縮小

## セキュリティに関する注意

- 外部APIキーはフォークPRで使用しない運用を推奨
- Botはコード変更を行わず、コメント投稿のみ実行
- 機密情報や内部IDは送信前にマスキング推奨

## リリース手順（メンテナ向け）

他リポジトリは `uses: enprocode/ai-review-bot/.github/workflows/ai-review.yml@1` のようにメジャーバージョンの浮動タグを参照する想定です（`actions/checkout@v4` などと同じ慣例）。リリースは [`VERSION`](../VERSION) ファイルとそれを検知する [`release.yml`](../.github/workflows/release.yml) で自動化されています。

**手順は [`VERSION`](../VERSION) を書き換えてPRを作成・mainにマージするだけです。** マージ後、`release.yml` が自動で以下を行います。

1. `VERSION` の中身（semver、`v`プレフィックスなし。例: `1.2.0`）をパッチタグとして作成・push
2. メジャー部分（例: `1.2.0` なら `1`）のタグを同じコミットへforce-moveしてpush
3. GitHub Releaseを自動生成（リリースノートは前回タグとの差分から自動生成）

同じバージョンのタグが既に存在する場合はスキップされるため、`VERSION` を上げ忘れたまま他の変更だけをマージしても誤って再リリースされることはありません。

- `@1` を参照している呼び出し元は、次回のワークフロー実行時から自動的に新しいコードを使うようになる（呼び出し元は何もする必要がない）
- 破壊的変更（inputs/secretsの削除・必須化、既定挙動の変更など）を含む場合は、既存の `@1` 利用者に影響が出るため、README/リリースノート等で事前告知した上で `VERSION` のメジャー部分を上げる
- ピンポイントで固定したい利用者向けに、パッチタグ（例: `1.2.0`）は動かさず残しておく
- `workflow_dispatch` で手動実行も可能（`VERSION` の値でタグ作成が行われる。緊急時やCI再実行用）
