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

`.github/workflows/self-ai-review.yml` を作成し、以下を貼り付けます。

```yaml
name: AI Code Review (self)

on:
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review]

  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: self-ai-review-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  review:
    if: ${{ !github.event.pull_request.draft }}
    runs-on: ubuntu-latest

    steps:
      - name: Check out HEAD
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -U pip
          pip install -r requirements.txt

      - name: Run AI review
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          MODEL: gpt-4o-mini
          MAX_TOKENS: "2000"
          LANGUAGE: "ja"
        run: |
          python scripts/run_review.py \
            --repo "${{ github.repository }}" \
            --pr "${{ github.event.pull_request.number }}" \
            --model "${MODEL}" \
            --language "${LANGUAGE}" \
            --max-tokens "${MAX_TOKENS}"

      - name: Post comments
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python scripts/post_comments.py \
            --repo "${{ github.repository }}" \
            --pr "${{ github.event.pull_request.number }}"
```

---

### 2️⃣ Secretsを設定

| 名前 | 説明 |
|------|------|
| `OPENAI_API_KEY` | LLMのAPIキー（OpenAI / Azure OpenAI / OpenRouter等） |
| `GITHUB_TOKEN` | 自動コメント投稿に使用（デフォルトで付与） |

> 🔒 フォークPRでは `OPENAI_API_KEY` は渡されません。安全設計のため外部APIを利用しないレビュー処理が推奨されます。

---

## ⚙️ 環境変数一覧

| 変数名 | 説明 | 例 |
|--------|------|----|
| `MODEL` | 使用モデル名 | `gpt-4o-mini` |
| `MAX_TOKENS` | 出力トークン数上限 | `2000` |
| `LANGUAGE` | 出力言語 | `ja` / `en` |
| `REVIEW_SCOPE` | レビュー観点プリセット | `standard`, `security`, `test` |
| `DIFF_MAX_BYTES` | diff上限（大規模PR対策） | 50000 |
| `FAIL_ON_HIGH_RISK` | 高リスク検出でCI失敗扱い | true/false |

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

# テスト実行
python scripts/run_review.py --repo owner/repo --pr 123 --model gpt-５ --language ja
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

