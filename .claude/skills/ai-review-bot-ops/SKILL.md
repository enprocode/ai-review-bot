---
name: ai-review-bot-ops
description: このリポジトリ（ai-review-bot）自身のPRにBotの通知コメントが来たときの一次対応手順。CI通知やレビューコメントのトリアージ、config.yaml調整の判断基準を示す。「AIレビューBot」「skip_reason」「fail_level」等に関する作業で使用する。
---

# ai-review-bot 運用ルール

このSkillは、ai-review-bot自身のPRにBotのコメント（通知・レビュー指摘）が付いたときの一次対応手順です。詳細な原因と対処は [docs/troubleshooting.md](../../docs/troubleshooting.md) を参照してください。ここでは判断フローだけを示します。

## トリアージの手順

1. **コメントに `comment_id` があるか確認する。**
   - ない（`### 🤖 AIレビューBot` のまとめコメント、通知コメント）→ 返信・resolve不要。内容だけ確認する。
   - ある（インラインコメント）→ 個別に検証してから返信・resolveする。

2. **通知コメント（スキップ系）は基本的にコード修正不要。**
   - 「クレジット/クォータ切れ」「認証エラー」「レートリミット」→ 環境側の問題。[docs/troubleshooting.md](../../docs/troubleshooting.md) の該当セクションに従い、必要ならユーザーに課金/Secrets設定を促す。
   - 「モデルから有効な応答が得られませんでした」→ ログで `finish_reason` と出力冒頭を確認。`max_tokens` 不足か、モデルのJSON不遵守か切り分ける。

3. **インラインの指摘は鵜呑みにせず検証する。**
   - 差分だけを見て「存在しない」と判定していないか（実際は差分外に定義がある）を必ずコード側で確認する。
   - 「行の移動」を「削除」と誤認していないか確認する。
   - 検証の結果、誤検知なら **コード変更はせず**、スレッドに理由を1行で返信して resolve する。
   - 実在するバグなら修正し、テストを通してからpushし、スレッドに変更内容を1行で返信して resolve する。

4. **CIが `fail_level` により赤くなっている場合、それ自体はバグではない。**
   - 指摘の中身が誤検知ばかりなら `fail_level` の緩和（`CRITICAL` へ）や `enable_inline: false` をユーザーに提案する。ユーザーの明示的な合意なしに `fail_level` は変更しない。

## config.yaml を変更してよい場合 / だめな場合

- **変更してよい**: モデルのJSON不運守やレートリミットが続く → `fallback_models` の順序入れ替え、`model` の変更。トークン消費を減らしたい → `max_diff_chars` / `max_findings` / `max_tokens` の調整。
- **ユーザーに確認してから変更する**: `fail_level` の変更、`enable_inline` の切り替え、無料モデルから有料モデルへの切り替え（コスト発生を伴うため）。

## 変更後の確認

- 必ず `python -m unittest discover -s tests` を通す。
- pushしてCIの結果を確認する（`gh pr checks 5` または `gh run watch`）。
- ドキュメント（README / docs/）と実装が乖離しないよう、挙動を変えたら該当ドキュメントも同じコミットで更新する。
