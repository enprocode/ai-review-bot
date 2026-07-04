import os
import re
import json
import textwrap
import yaml
import time
import fnmatch
import logging
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI
from github import Github, Auth
import argparse

DEFAULT_MAX_DIFF_CHARS = 8000
DEFAULT_MAX_FINDINGS = 50
DEFAULT_BATCH_SIZE = 20
DEFAULT_MODEL = "gpt-5"

SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "MAJOR": "🟠",
    "MINOR": "🟡",
    "SUGGESTION": "🟢",
}
SEVERITY_ORDER = ["SUGGESTION", "MINOR", "MAJOR", "CRITICAL"]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def extract_output_text(resp: Any) -> str:
    """
    OpenAI Responses API の返却オブジェクトからテキストを抽出する。
    output_text が無い場合も想定し、content の text を走査する。
    """
    text = _get(resp, "output_text")
    if text:
        return str(text)
    output = _get(resp, "output")
    parts: List[str] = []
    if output:
        for item in output:
            content = _get(item, "content")
            if not content:
                continue
            for block in content:
                piece = _get(block, "text")
                if piece:
                    parts.append(str(piece))
    if parts:
        return "\n".join(parts)
    return ""


def load_config() -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base_dir, "config.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = f.read()
    expanded = os.path.expandvars(raw)
    return yaml.safe_load(expanded)


def retry(fn, tries: int = 3, base_sleep: float = 1.0):
    """指数バックオフ付きリトライ"""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(base_sleep * (2 ** i))


def extract_json_block(text: str) -> Optional[str]:
    """```json ... ``` を抜き出す"""
    m = re.search(r"```json\s*(.+?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


def to_inline_body(f: Dict[str, Any]) -> str:
    """各指摘の本文を整形"""
    parts = [
        f'{SEVERITY_EMOJI[f["severity"]]} **{f["severity"]}** — {f["title"]}',
        (f.get("detail") or ""),
        (f'**修正案:** {f["fix"]}' if f.get("fix") else "")
    ]
    return "\n\n".join([p for p in parts if p]).strip()


def build_prompt(files, user_prompt: str, max_diff_chars: int, style: Optional[str] = None) -> str:
    filenames = [f.filename for f in files]
    file_list = "\n".join(f"- {name}" for name in filenames)

    patches, used = [], 0
    for f in files:
        patch = f.patch or ""
        block = f"\n\n=== {f.filename} ===\n{patch}"
        block_len = len(block)
        if used + block_len > max_diff_chars:
            remaining = max_diff_chars - used
            if remaining > 0:
                patches.append(block[:remaining])
                used += remaining
            break
        patches.append(block)
        used += block_len
    diff_snippet = "".join(patches) if patches else "(変更差分は取得できませんでした)"
    style_directive = f"\nレビューは「{style}」なトーンでお願いします。" if style else ""

    return textwrap.dedent(f"""
    あなたは熟練したエンジニアとして、以下のPR差分をレビューしてください。{style_directive}
    出力は必ず ```json フェンス内に JSON配列のみ``` で返してください。

    JSONスキーマ:
    [
      {{
        "severity": "CRITICAL" | "MAJOR" | "MINOR" | "SUGGESTION",
        "file": "相対パス（例: src/main.py）",
        "line": 123,  // 右側(HEAD)の行番号を返すこと
        "title": "短い見出し",
        "detail": "背景/根拠を簡潔に記載",
        "fix": "具体的な修正案（任意）"
      }}
    ]

    【変更ファイル】
    {file_list}

    【差分（上限 {max_diff_chars} 文字）】
    {diff_snippet}

    【追加指示】
    {user_prompt or '(特になし)'}
    """).strip()


def normalize_findings(data: Any, max_findings: int) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return findings

    for item in data[:max_findings]:
        if not isinstance(item, dict):
            continue
        sev = str(item.get("severity", "SUGGESTION")).upper().strip()
        if sev not in SEVERITY_EMOJI:
            sev = "SUGGESTION"
        try:
            line = int(item.get("line")) if item.get("line") else None
        except Exception:
            line = None
        findings.append({
            "severity": sev,
            "file": item.get("file", "-"),
            "line": line,
            "title": (item.get("title") or "").strip() or "（タイトル未設定）",
            "detail": (item.get("detail") or "").strip(),
            "fix": (item.get("fix") or "").strip(),
        })
    return findings


def parse_findings_from_text(raw_text: str, max_findings: int) -> Tuple[List[Dict[str, Any]], bool]:
    """
    モデル出力テキストから指摘リストを抽出する。
    まずテキスト全体がJSONであることを試み、失敗したら ```json ``` ブロックを探す。
    """
    stripped = (raw_text or "").strip()
    if stripped:
        try:
            data = json.loads(stripped)
            return normalize_findings(data, max_findings), True
        except Exception:
            logging.debug("生テキストのJSONパースに失敗しました。フェンス付きブロックを探索します。")

    json_block = extract_json_block(raw_text or "")
    if json_block:
        try:
            data = json.loads(json_block)
            return normalize_findings(data, max_findings), True
        except Exception as exc:
            logging.warning("```json``` ブロックのパースに失敗しました: %s", exc)

    return [], False


def filter_files(files, include_globs, exclude_globs, max_files):
    result = []
    for f in files:
        path = f.filename
        if include_globs and not any(fnmatch.fnmatch(path, p) for p in include_globs):
            continue
        if exclude_globs and any(fnmatch.fnmatch(path, p) for p in exclude_globs):
            continue
        if f.patch is None:
            continue
        result.append(f)
        if len(result) >= max_files:
            break
    return result


def build_position_map(files) -> Dict[str, Dict[int, int]]:
    """
    各ファイルの unified diff を解析し、
    右側(新ファイル)の行番号 -> diff内position のマップを作る。
    position は GitHub API の review comment で使うインデックス。
    """
    maps: Dict[str, Dict[int, int]] = {}
    for f in files:
        patch = f.patch
        if not patch:
            continue
        right_line = 0
        # hunk 先頭の "+<start>,<len>" を解析
        position = 0  # diff内の位置は1始まりでカウント
        mapping: Dict[int, int] = {}

        for raw in patch.splitlines():
            position += 1
            if raw.startswith('@@'):
                # 例: @@ -12,7 +20,6 @@
                m = re.search(r"\+(\d+)(?:,(\d+))?", raw)
                if m:
                    right_line = int(m.group(1))
                else:
                    right_line = 0
                # ヘッダ行自体もpositionに含まれる（上で+1済み）
                continue
            if raw.startswith('+'):  # 追加行（右側のみ進む）
                mapping[right_line] = position
                right_line += 1
            elif raw.startswith('-'):  # 削除行（左側のみ進む）
                # 右側の行番号は進めない
                pass
            elif raw.startswith('\\'):  # "\ No newline at end of file" 等のマーカー行（行番号は進めない）
                pass
            else:
                # コンテキスト行：両側進む
                if right_line > 0:
                    right_line += 1

        if mapping:
            maps[f.filename] = mapping
    return maps


def find_position(pos_map: Dict[str, Dict[int, int]], path: str, line: Optional[int], snap_range: int = 3) -> Optional[int]:
    """
    指定の path/line(右側)に最も近い position を探す。
    その行が追加行でない場合もあるので、近傍の追加行にスナップする。
    """
    if line is None:
        return None
    m = pos_map.get(path)
    if not m:
        return None
    if line in m:
        return m[line]
    # 近傍探索
    for d in range(1, snap_range + 1):
        if (line - d) in m:
            return m[line - d]
        if (line + d) in m:
            return m[line + d]
    return None


def dedup_existing(pr, inline_candidates, fallback_texts):
    """既存コメント重複防止（position基準を優先）"""
    existing_inline = {}
    for c in pr.get_review_comments():
        key = (c.path, c.position or c.line, (c.body or "").strip())
        existing_inline[key] = True

    existing_reviews = {(r.body or "").strip() for r in pr.get_reviews() if (r.body or "").strip()}

    filtered_inline = []
    for c in inline_candidates:
        key = (c["path"], c.get("position") or c.get("line"), c["body"].strip())
        if key in existing_inline:
            continue
        filtered_inline.append(c)

    filtered_fallback = [b for b in fallback_texts if b.strip() not in existing_reviews]
    return filtered_inline, filtered_fallback


def post_inline_reviews(pr, findings, batch_size):
    # 変更ファイル取得（positionマップ作成用）
    changed_files = list(pr.get_files())
    changed_paths = {f.filename for f in changed_files}
    pos_map = build_position_map(changed_files)

    inline, fallback_lines = [], []

    for f in findings:
        path, line = f["file"], f["line"]
        if path in changed_paths:
            pos = find_position(pos_map, path, line)
        else:
            pos = None

        body = to_inline_body(f)

        if pos is not None:
            # ✅ position を使ってインラインコメント（422回避）
            inline.append({"path": path, "position": pos, "body": body})
        else:
            # フォールバック：まとめコメントに回す
            where = f'`{path}`' + (f' L{line}' if line else "")
            fallback_lines.append(
                f'- {SEVERITY_EMOJI[f["severity"]]} **{f["severity"]}** {where} — {f["title"]}\n'
                f'  {f["detail"]}' + (f'\n  **修正案:** {f["fix"]}' if f["fix"] else "")
            )

    fallback_body = None
    if fallback_lines:
        body_content = "\n".join(fallback_lines)
        fallback_body = "### 🤖 AIレビューBot（行特定不可の指摘）\n\n" + (body_content or "内容なし")

    inline, fallback_bodies = dedup_existing(pr, inline, [fallback_body] if fallback_body else [])

    # バッチでレビュー作成
    for i in range(0, len(inline), batch_size):
        batch = inline[i:i + batch_size]
        if not batch:
            continue
        retry(lambda: pr.create_review(body="", event="COMMENT", comments=batch))

    if fallback_bodies:
        retry(lambda: pr.create_review(body=fallback_bodies[0], event="COMMENT"))


def maybe_fail_job(findings, fail_level):
    if not fail_level:
        return
    level = fail_level.upper().strip()
    if level not in SEVERITY_ORDER:
        return
    worst = "SUGGESTION"
    for f in findings:
        if SEVERITY_ORDER.index(f["severity"]) > SEVERITY_ORDER.index(worst):
            worst = f["severity"]
    if SEVERITY_ORDER.index(worst) >= SEVERITY_ORDER.index(level):
        raise SystemExit(1)


def build_no_findings_body(raw_text: str, parsed_successfully: bool) -> str:
    header = "### 🤖 AIレビューBot"
    if parsed_successfully:
        return f"{header}\n\nLGTM! 🎉 特に指摘はありません。"
    message = (raw_text or "").strip()
    if not message:
        message = "レビュー内容を生成できませんでした。（モデルから有効な応答が得られませんでした）"
    return f"{header}\n\n{message}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True)
    parser.add_argument("--prompt", default="")
    args = parser.parse_args()

    cfg = load_config()
    log_level_name = str(cfg.get("log_level") or "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.info("AIレビューを開始します: repo=%s, pr=%s", args.repo, args.pr)
    openai_key = cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    gh_token = cfg.get("github_token") or os.getenv("GITHUB_TOKEN")
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY が見つかりません。")
    if not gh_token:
        raise RuntimeError("GITHUB_TOKEN が見つかりません。")

    model = cfg.get("model", DEFAULT_MODEL)
    system_prompt = (cfg.get("system_prompt") or "").strip()
    style = (cfg.get("style") or "").strip()
    enable_inline = bool(cfg.get("enable_inline", True))
    fail_level = cfg.get("fail_level")
    include_globs = cfg.get("include_globs", []) or []
    exclude_globs = cfg.get("exclude_globs", []) or []
    max_files = int(cfg.get("max_files", 200))
    max_diff_chars = int(cfg.get("max_diff_chars", DEFAULT_MAX_DIFF_CHARS))
    max_findings = int(cfg.get("max_findings", DEFAULT_MAX_FINDINGS))
    batch_size = int(cfg.get("batch_size", DEFAULT_BATCH_SIZE))
    max_output_tokens = cfg.get("max_tokens")
    if max_output_tokens:
        try:
            max_output_tokens = int(max_output_tokens)
        except (TypeError, ValueError):
            max_output_tokens = None

    gh = Github(auth=Auth.Token(gh_token))
    repo = gh.get_repo(args.repo)
    pr = repo.get_pull(int(args.pr))

    # ドラフトPRはスキップ
    if getattr(pr, "draft", False):
        logging.info("PR #%s はドラフトのためレビューをスキップします。", args.pr)
        return

    files_all = list(pr.get_files())
    files = filter_files(files_all, include_globs, exclude_globs, max_files)
    if not files:
        logging.info("対象ファイルが見つからなかったためレビューコメントを投稿します。")
        retry(lambda: pr.create_review(body="### 🤖 AIレビューBot\n\n対象ファイルがありません。", event="COMMENT"))
        return

    logging.info("レビュー対象ファイル数: %s (取得 %s, 上限 %s)", len(files), len(files_all), max_files)

    prompt_text = build_prompt(files, args.prompt, max_diff_chars, style=style or None)
    client = OpenAI(api_key=openai_key)

    def format_message(role: str, text: str) -> Dict[str, Any]:
        block_type = "input_text"
        if role == "assistant":
            block_type = "output_text"
        return {
            "role": role,
            "content": [
                {
                    "type": block_type,
                    "text": text,
                }
            ],
        }

    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append(format_message("system", system_prompt))
    messages.append(format_message("user", prompt_text))

    request_kwargs: Dict[str, Any] = {
        "model": model,
        "input": messages,
        "text": {"format": {"type": "json_object"}},
    }
    if max_output_tokens:
        request_kwargs["max_output_tokens"] = max_output_tokens
    raw_text = ""
    for attempt in range(1, 4):
        def _call_openai():
            try:
                return client.responses.create(**request_kwargs)
            except TypeError as exc:
                if "text" in str(exc):
                    logging.warning("text.format パラメータがサポートされていないため、通常のテキスト応答にフォールバックします。")
                    request_kwargs.pop("text", None)
                    return client.responses.create(**request_kwargs)
                raise

        resp = retry(_call_openai)
        raw_text = extract_output_text(resp)
        if raw_text.strip():
            break
        logging.warning("OpenAIレスポンスが空でした。（試行 %s/3）", attempt)
    else:
        logging.error("OpenAIレスポンスが3回連続で空でした。レビュー結果を投稿できません。")
        fallback_body = build_no_findings_body(
            "モデルから有効な応答が得られませんでした。（3回再試行しても空のレスポンス）",
            parsed_successfully=False,
        )
        retry(lambda: pr.create_review(body=fallback_body, event="COMMENT"))
        return
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug("OpenAI raw response: %r", resp)

    findings, parsed_successfully = parse_findings_from_text(raw_text, max_findings)
    if parsed_successfully:
        logging.info("モデル出力から %s 件の指摘を抽出しました。", len(findings))
    else:
        snippet = (raw_text[:300] + "…") if raw_text and len(raw_text) > 300 else (raw_text or "(空)")
        logging.warning("モデル出力から有効な指摘を抽出できませんでした。出力(先頭300文字): %s", snippet)

    if not findings:
        review_body = build_no_findings_body(raw_text, parsed_successfully)
        retry(lambda: pr.create_review(body=review_body, event="COMMENT"))
        logging.info("指摘なしコメントを投稿しました。（parsed=%s）", parsed_successfully)
        return

    if enable_inline:
        logging.info("インラインコメントモードで %s 件の指摘を投稿します。", len(findings))
        post_inline_reviews(pr, findings, batch_size)
    else:
        logging.info("まとめコメントモードで %s 件の指摘を投稿します。", len(findings))
        bullets = []
        for f in findings:
            where = f'`{f["file"]}`' + (f' L{f["line"]}' if f["line"] else "")
            bullets.append(f'- {SEVERITY_EMOJI[f["severity"]]} **{f["severity"]}** {where} — {f["title"]}\n  {f["detail"]}')
            if f["fix"]:
                bullets.append(f'  **修正案:** {f["fix"]}')
        retry(lambda: pr.create_review(body="### 🤖 AIレビューBot\n\n" + "\n".join(bullets), event="COMMENT"))

    maybe_fail_job(findings, fail_level)


if __name__ == "__main__":
    main()
