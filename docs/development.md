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
