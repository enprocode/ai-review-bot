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

# レビュー済みコミットを記録する不可視マーカー（GitHub上では表示されない）
REVIEWED_MARKER_RE = re.compile(r"<!-- ai-review-bot:reviewed:([0-9a-f]{40}) -->")


def reviewed_marker(sha: str) -> str:
    return f"<!-- ai-review-bot:reviewed:{sha} -->"


def find_last_reviewed_sha(pr) -> Optional[str]:
    """過去のレビューコメントから最後にレビューしたコミットSHAを取得する"""
    sha = None
    for r in pr.get_reviews():
        m = REVIEWED_MARKER_RE.search(r.body or "")
        if m:
            sha = m.group(1)
    return sha


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def extract_output_text(resp: Any) -> str:
    """Chat Completions API の返却オブジェクトからテキストを抽出する。"""
    choices = _get(resp, "choices")
    if choices:
        message = _get(choices[0], "message")
        content = _get(message, "content") if message else None
        if content:
            return str(content)
    return ""


def load_config() -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base_dir, "config.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = f.read()
    expanded = os.path.expandvars(raw)
    cfg = yaml.safe_load(expanded)
    # 環境変数が未設定だと ${VAR} が文字列のまま残るため、未設定扱いにする
    for key in ("llm_api_key", "openai_api_key", "github_token"):
        val = cfg.get(key)
        if isinstance(val, str) and re.fullmatch(r"\$\{[^}]+\}", val.strip()):
            cfg[key] = None
    return cfg


def skip_reason(e: Exception) -> Optional[str]:
    """
    レビューをCI失敗にせずスキップすべきエラーなら理由を返す。
    環境側の問題（残高・認証設定）はコード側で解決できないため通知に留める。
    """
    status = getattr(e, "status_code", None) or getattr(e, "status", None)
    msg = str(e).lower()
    if status == 402 or "insufficient_quota" in msg or "insufficient credits" in msg:
        return "APIのクレジット/クォータ切れ"
    if status in (401, 403):
        return "APIキーの認証エラー（LLM_API_KEY と base_url の組み合わせを確認してください）"
    return None


def retry(fn, tries: int = 3, base_sleep: float = 1.0):
    """指数バックオフ付きリトライ（4xxなど再試行しても無駄なエラーは即時raise）"""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            status = getattr(e, "status_code", None) or getattr(e, "status", None)
            retryable = status is None or (
                isinstance(status, int) and (status in (408, 429) or status >= 500)
            )
            # クレジット/クォータ切れは再試行しても回復しない
            if skip_reason(e):
                retryable = False
            if not retryable or i == tries - 1:
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


def to_bullet(f: Dict[str, Any]) -> str:
    """まとめコメント用の箇条書き1件を整形（インライン化できない指摘にも使う）"""
    where = f'`{f["file"]}`' + (f' L{f["line"]}' if f["line"] else "")
    bullet = f'- {SEVERITY_EMOJI[f["severity"]]} **{f["severity"]}** {where} — {f["title"]}\n  {f["detail"]}'
    if f["fix"]:
        bullet += f'\n  **修正案:** {f["fix"]}'
    return bullet


def post_comment(pr, body: str):
    retry(lambda: pr.create_review(body=body, event="COMMENT"))


def post_comment_once(pr, body: str):
    """同一本文のコメントが既にあれば投稿しない（定型通知の重複防止）"""
    if not any((r.body or "").strip() == body.strip() for r in pr.get_reviews()):
        post_comment(pr, body)


def build_prompt(files, user_prompt: str, max_diff_chars: int, style: Optional[str] = None,
                 max_findings: Optional[int] = None, language: str = "日本語") -> str:
    filenames = [f.filename for f in files]
    file_list = "\n".join(f"- {name}" for name in filenames)

    patches, used, truncated = [], 0, False
    for f in files:
        patch = f.patch or ""
        block = f"\n\n=== {f.filename} ===\n{patch}"
        block_len = len(block)
        if used + block_len > max_diff_chars:
            remaining = max_diff_chars - used
            if remaining > 0:
                patches.append(block[:remaining])
                used += remaining
            truncated = True
            break
        patches.append(block)
        used += block_len
    diff_snippet = "".join(patches) if patches else "(変更差分は取得できませんでした)"
    if truncated:
        diff_snippet += "\n\n(注意: 差分は文字数上限で途中まで切り詰められています)"
    style_directive = f"\nレビューは「{style}」なトーンでお願いします。" if style else ""
    findings_limit = f"\n指摘は重大度の高い順に最大{max_findings}件までとし、detail/fixは簡潔にしてください。" if max_findings else ""
    language_directive = f"\nすべての指摘（title / detail / fix）は必ず{language}で記述してください。"

    return textwrap.dedent(f"""
    あなたは熟練したエンジニアとして、以下のPR差分をレビューしてください。{style_directive}{findings_limit}{language_directive}
    出力は必ず次のJSONスキーマに従うJSONオブジェクトのみで返してください。

    JSONスキーマ:
    {{"findings": [
      {{
        "severity": "CRITICAL" | "MAJOR" | "MINOR" | "SUGGESTION",
        "file": "相対パス（例: src/main.py）",
        "line": 123,  // 右側(HEAD)の行番号を返すこと
        "title": "短い見出し",
        "detail": "背景/根拠を簡潔に記載",
        "fix": "具体的な修正案（任意）"
      }}
    ]}}

    【誤検知防止の注意（重要）】
    - 差分には変更行と前後数行しか含まれません。インポート文・関数定義・設定キー・フォールバック処理などが
      差分に「見えない」ことを「存在しない」と断定しないでください。
    - 削除行と同内容の追加行が別の位置にある場合は「移動」であり「削除」ではありません。
    - 差分内の証拠だけで確実に問題と断定できるもののみ指摘してください。推測に基づく指摘は出力しないでください。

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
        # json_object形式で {"findings": [...]} のようにラップされた場合は中の配列を使う
        inner = next((v for v in data.values() if isinstance(v, list)), None)
        data = inner if inner is not None else [data]
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


def salvage_findings(text: str) -> Optional[List[Any]]:
    """
    トークン上限などで途中で切れたJSONから、完全な指摘オブジェクトだけを回収する。
    最初の '[' 以降を走査し、パースできたオブジェクトを順に集める。
    """
    start = text.find("[")
    if start == -1:
        return None
    decoder = json.JSONDecoder()
    items: List[Any] = []
    i = start + 1
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text) or text[i] != "{":
            break
        try:
            obj, i = decoder.raw_decode(text, i)
        except ValueError:
            break
        items.append(obj)
    return items or None


def parse_findings_from_text(raw_text: str, max_findings: int) -> Tuple[List[Dict[str, Any]], bool]:
    """
    モデル出力テキストから指摘リストを抽出する。
    テキスト全体のJSONパース → ```json ``` ブロック → 途切れJSONのサルベージの順に試す。
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

    salvaged = salvage_findings(stripped)
    if salvaged:
        logging.warning("JSONが途中で切れていたため、完全な指摘 %s 件のみ回収しました。", len(salvaged))
        return normalize_findings(salvaged, max_findings), True

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
            logging.info("パッチが取得できないためスキップします（バイナリ/大容量ファイルの可能性）: %s", path)
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


def post_inline_reviews(pr, findings, batch_size, changed_files, marker: str = ""):
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
            fallback_lines.append(to_bullet(f))

    fallback_body = None
    if fallback_lines:
        body_content = "\n".join(fallback_lines)
        fallback_body = "### 🤖 AIレビューBot（行特定不可の指摘）\n\n" + (body_content or "内容なし")

    inline, fallback_bodies = dedup_existing(pr, inline, [fallback_body] if fallback_body else [])

    # バッチでレビュー作成（マーカーは最初の投稿にのみ埋め込む）
    for i in range(0, len(inline), batch_size):
        batch = inline[i:i + batch_size]
        if not batch:
            continue
        body = marker if i == 0 else ""
        retry(lambda b=batch, bd=body: pr.create_review(body=bd, event="COMMENT", comments=b))

    if fallback_bodies:
        suffix = f"\n\n{marker}" if marker and not inline else ""
        post_comment(pr, fallback_bodies[0] + suffix)


def call_llm_review(client, model: str, system_prompt: str, prompt_text: str,
                    max_output_tokens: Optional[int],
                    fallback_models: Optional[List[str]] = None,
                    reasoning_effort: Optional[str] = None) -> str:
    """
    Chat Completions API（OpenAI互換）を呼び、モデル出力テキストを返す。
    空レスポンスは最大3回まで再取得し、それでも空なら "" を返す。
    """
    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt_text})

    request_kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if max_output_tokens:
        request_kwargs["max_completion_tokens"] = max_output_tokens
    if fallback_models:
        # OpenRouterのモデルフォールバック（指定モデルが落ちている場合に自動切替）
        request_kwargs["extra_body"] = {"models": fallback_models}
    if reasoning_effort:
        # 推論モデルの思考トークン量を制御（max_tokensが小さい環境では low 推奨）
        request_kwargs["reasoning_effort"] = reasoning_effort

    def _call():
        try:
            return client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            msg = str(exc)
            # OpenAI互換プロバイダごとの差異を吸収するフォールバック
            if "response_format" in msg and "response_format" in request_kwargs:
                logging.warning("response_format 未対応のため、通常のテキスト応答にフォールバックします。")
                request_kwargs.pop("response_format")
                return _call()
            if "max_completion_tokens" in msg and "max_completion_tokens" in request_kwargs:
                logging.warning("max_completion_tokens 未対応のため、max_tokens で再試行します。")
                request_kwargs["max_tokens"] = request_kwargs.pop("max_completion_tokens")
                return _call()
            if "reasoning_effort" in msg and "reasoning_effort" in request_kwargs:
                logging.warning("reasoning_effort 未対応のため、外して再試行します。")
                request_kwargs.pop("reasoning_effort")
                return _call()
            raise

    for attempt in range(1, 4):
        resp = retry(_call)
        raw_text = extract_output_text(resp)
        if raw_text.strip():
            logging.debug("LLM raw response: %r", resp)
            return raw_text
        choices = _get(resp, "choices") or []
        finish_reason = _get(choices[0], "finish_reason") if choices else None
        logging.warning("LLMレスポンスが空でした。（試行 %s/3, finish_reason=%s）", attempt, finish_reason)
        if finish_reason == "length":
            logging.warning("トークン上限で打ち切られています。config.yaml の max_tokens を増やしてください。")
    return ""


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
        message = "レビュー内容を生成できませんでした。（モデルから有効な応答が得られませんでした。詳細はワークフローのログを参照）"
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
    api_key = (cfg.get("llm_api_key") or cfg.get("openai_api_key")
               or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
    gh_token = cfg.get("github_token") or os.getenv("GITHUB_TOKEN")
    if not api_key:
        raise RuntimeError("LLM_API_KEY（旧名: OPENAI_API_KEY）が見つかりません。")
    if not gh_token:
        raise RuntimeError("GITHUB_TOKEN が見つかりません。")

    model = cfg.get("model", DEFAULT_MODEL)
    base_url = (cfg.get("base_url") or "").strip() or None
    fallback_models = cfg.get("fallback_models") or []
    reasoning_effort = (str(cfg.get("reasoning_effort") or "")).strip() or None
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

    # トークン節約: レビュー済みコミットはスキップし、push時は前回以降の変更ファイルのみレビュー
    head_sha = pr.head.sha
    last_sha = find_last_reviewed_sha(pr)
    if last_sha == head_sha:
        logging.info("HEAD %s は前回レビュー済みのためスキップします。", head_sha[:7])
        return

    files_all = list(pr.get_files())
    files = filter_files(files_all, include_globs, exclude_globs, max_files)

    if last_sha:
        try:
            delta_paths = {f.filename for f in repo.compare(last_sha, head_sha).files}
            files = [f for f in files if f.filename in delta_paths]
            logging.info("前回レビュー(%s)以降に変更されたファイルのみレビューします: %s件",
                         last_sha[:7], len(files))
            if not files:
                logging.info("前回レビュー以降の変更にレビュー対象ファイルがないためスキップします。")
                return
        except Exception as e:
            logging.warning("前回レビューとの差分取得に失敗したため全ファイルをレビューします: %s", e)

    if not files:
        logging.info("対象ファイルが見つからなかったためレビューコメントを投稿します。")
        post_comment(pr, "### 🤖 AIレビューBot\n\n対象ファイルがありません。")
        return

    logging.info("レビュー対象ファイル数: %s (取得 %s, 上限 %s)", len(files), len(files_all), max_files)

    language = (str(cfg.get("language") or "")).strip() or "日本語"
    prompt_text = build_prompt(files, args.prompt, max_diff_chars, style=style or None,
                               max_findings=max_findings, language=language)
    # SDK内部リトライは1回に制限（Retry-Afterの長い待ちが多重リトライで膨らむのを防ぐ）
    client_kwargs: Dict[str, Any] = {"api_key": api_key, "base_url": base_url, "max_retries": 1}
    if base_url and "openrouter" in base_url:
        # OpenRouterのアプリ帰属ヘッダ（ダッシュボードでの利用元識別用）
        client_kwargs["default_headers"] = {
            "HTTP-Referer": "https://github.com/enprocode/ai-review-bot",
            "X-Title": "ai-review-bot",
        }
    client = OpenAI(**client_kwargs)

    # パース不能な出力（JSON不遵守）にも代替モデルで再試行する
    candidate_models = [model] + [m for m in fallback_models if m != model]
    raw_text, findings, parsed_successfully = "", [], False
    try:
        for candidate in candidate_models:
            raw_text = call_llm_review(client, candidate, system_prompt, prompt_text,
                                       max_output_tokens, fallback_models=fallback_models,
                                       reasoning_effort=reasoning_effort)
            if not raw_text.strip():
                logging.warning("モデル %s のレスポンスが空でした。次の候補を試します。", candidate)
                continue
            findings, parsed_successfully = parse_findings_from_text(raw_text, max_findings)
            if parsed_successfully:
                logging.info("モデル %s の出力から %s 件の指摘を抽出しました。", candidate, len(findings))
                break
            snippet = (raw_text[:300] + "…") if len(raw_text) > 300 else raw_text
            logging.warning("モデル %s の出力を解析できませんでした。次の候補を試します。出力(先頭300文字): %s",
                            candidate, snippet)
    except Exception as e:
        # 残高切れ・認証設定ミス・レートリミットは環境側の問題なのでCIを失敗させず、通知して正常終了する
        reason = skip_reason(e)
        if reason is None:
            status = getattr(e, "status_code", None) or getattr(e, "status", None)
            if status == 429:
                reason = "APIのレートリミット（時間をおいて再実行してください）"
        if reason:
            logging.warning("%s のためレビューをスキップします: %s", reason, e)
            post_comment_once(pr, f"### 🤖 AIレビューBot\n\n⚠️ {reason} のためレビューをスキップしました。")
            return
        raise

    if not raw_text.strip():
        logging.error("全候補モデルのレスポンスが空でした。レビュー結果を投稿できません。")
        post_comment_once(pr, build_no_findings_body(
            "モデルから有効な応答が得られませんでした。（全候補モデルで空のレスポンス）",
            parsed_successfully=False,
        ))
        return

    marker = reviewed_marker(head_sha)

    if not findings:
        # パース失敗時はモデルの生テキストをPRに投稿しない（先頭300文字はログ出力済み）
        body_text = raw_text if parsed_successfully else ""
        post_comment_once(pr, build_no_findings_body(body_text, parsed_successfully) + f"\n\n{marker}")
        logging.info("指摘なしコメントを投稿しました。（parsed=%s）", parsed_successfully)
        return

    if enable_inline:
        logging.info("インラインコメントモードで %s 件の指摘を投稿します。", len(findings))
        post_inline_reviews(pr, findings, batch_size, files_all, marker=marker)
    else:
        logging.info("まとめコメントモードで %s 件の指摘を投稿します。", len(findings))
        bullets = [to_bullet(f) for f in findings]
        post_comment(pr, "### 🤖 AIレビューBot\n\n" + "\n".join(bullets) + f"\n\n{marker}")

    maybe_fail_job(findings, fail_level)


if __name__ == "__main__":
    main()
