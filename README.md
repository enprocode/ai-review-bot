# 🤖 AI Review Bot
[![Self AI Review](https://github.com/enprocode/ai-review-bot/actions/workflows/self-ai-review.yml/badge.svg)](https://github.com/enprocode/ai-review-bot/actions/workflows/self-ai-review.yml)

GitHub Actions ベースの **AIコードレビューBot** です。  
Pull Request を自動解析し、設計・可読性・バグリスクなどをAIがコメントします。  
セキュア運用（フォークPR対応・マージ時実行防止）にも配慮しています。

---

## 🚀 主な機能

- ✅ 差分をAIで解析し、PRごとに**自動コードレビューコメント**を投稿  
- ⚡️ **大規模PRも分割処理**で安定実行  
- 🧪 **設計・可読性・パフォーマンス・バグ検知**など多観点チェック  
- 🔒 **フォークPRセーフ設計**（Secretsを渡さない）  
- 👩‍💻 `workflow_dispatch` で手動再レビューも可能  
- ⛔ **マージ時・Draft PRでは実行しない**安全運用

---

## 📦 セットアップ

### 1️⃣ ワークフロー作成

このリポジトリには実際に動く2つのワークフローが同梱されています。

- [`.github/workflows/self-ai-review.yml`](.github/workflows/self-ai-review.yml) — トリガー役。ユニットテストを実行後、draft/フォークPRを除外して再利用ワークフローを呼び出します。
- [`.github/workflows/ai-review.yml`](.github/workflows/ai-review.yml) — 実処理。`src/reviewer.py` を1回実行し、GitHub App トークンでコメントを投稿します（`secrets: inherit` は使わず必要なシークレットのみ渡す設計）。

他リポジトリで使う場合は上記2ファイルをコピーし、`checkout` 対象とシークレット名を自リポジトリに合わせて調整してください。エントリポイントは常に単一の `src/reviewer.py`（`--repo` / `--pr` / `--prompt` を受け取る）で、`scripts/run_review.py` や `scripts/post_comments.py` のような分割スクリプトはありません。

---

### 2️⃣ Secretsを設定

| 名前 | 説明 |
|------|------|
| `OPENAI_API_KEY` | LLMのAPIキー（OpenAI / Azure OpenAI / OpenRouter等） |
| `GITHUB_TOKEN` | 自動コメント投稿に使用（デフォルトで付与） |

> 🔒 フォークPRでは `OPENAI_API_KEY` は渡されません。安全設計のため外部APIを利用しないレビュー処理が推奨されます。

---

## ⚙️ 設定一覧（`src/config.yaml`）

実行時の挙動は環境変数ではなく `src/config.yaml` で設定します（`OPENAI_API_KEY` / `GITHUB_TOKEN` の2つのみ環境変数/Secretsから参照）。

| キー | 説明 | 例 |
|------|------|----|
| `model` | 使用モデル名 | `gpt-5` |
| `max_tokens` | 出力トークン数上限 | `800` |
| `style` | レビューのトーン | `concise` |
| `enable_inline` | インラインコメント有効化 | `true` |
| `fail_level` | このレベル以上の指摘でCI失敗（未設定なら無効） | `MAJOR` |
| `include_globs` / `exclude_globs` | レビュー対象/除外パターン | `**/*.py` |
| `max_files` | 1PRあたりの対象ファイル数上限 | `200` |
| `max_diff_chars` | LLMに渡すdiffの文字数上限 | `8000` |
| `max_findings` | 指摘の最大件数 | `50` |
| `log_level` | ログレベル | `INFO` |

---

## 🧩 安全な運用ポイント

- ⛔ **マージ時は実行しない** (`pull_request` のみ)
- 🛌 **Draft PRはスキップ**
- 🔐 **SecretsはフォークPRへ渡さない**
- 🔎 **モデル呼び出しのログ/出力をサニタイズ**
- 🧱 **外部API使用時は `pull_request_target` + HEAD SHA指定**

---

## 🧠 処理の流れ

1. PRの差分を取得  
2. ファイル単位にチャンク分割  
3. 各チャンクをLLMに渡し、レビュー生成  
4. コメントをPRに自動投稿（重複防止）  
5. メンテナが `workflow_dispatch` で再実行可能  

---

## 💡 ベストプラクティス

- 小さなPR単位でレビュー品質UP  
- コーディング規約・Lint設定をLLMプロンプトに反映  
- 大規模リポジトリは `paths-ignore` で対象を縮小  
- レビュー結果をWikiにまとめて改善を続ける  

---

## 🔧 ローカル開発

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip -r requirements.txt

# ユニットテスト実行
python -m unittest discover -s tests

# ローカルでレビューを試す（OPENAI_API_KEY / GITHUB_TOKEN が必要）
python src/reviewer.py --repo owner/repo --pr 123
```

> ローカルでも `act` コマンドでGitHub Actionsをエミュレート可能です。

---

## 🛡️ セキュリティに関する注意

- 外部APIキーはフォークPRで使用しない運用を推奨  
- コード変更を行わず、コメント投稿のみ実行  
- 機密情報や内部IDは送信前にマスキング推奨  

---

## 🦯 ロードマップ

- [ ] セキュリティ / テスト / パフォーマンス用プリセット強化  
- [ ] リスクレベル別コメント優先度  
- [ ] Code Scanning (SARIF) 出力連携  
- [ ] 多言語レビュー対応  

---

## 🪿 ライセンス

このリポジトリは **MIT License** の下で公開されています。

---

## 🤝 コントリビューション

Issue・PR歓迎です！  
レビュー観点の拡張や新しいモデル対応など、ぜひご協力ください。

