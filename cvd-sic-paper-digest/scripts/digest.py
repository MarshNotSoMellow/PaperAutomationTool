#!/usr/bin/env python3
"""Build and email a daily scientific-paper digest using free services."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "seen.json"
REPORT_DIR = ROOT / "reports"
OPENALEX_URL = "https://api.openalex.org/works"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("–", "-").replace("—", "-")).strip()


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted_index.items():
        positions.extend((index, word) for index in indexes)
    return " ".join(word for _, word in sorted(positions))


def matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def count_matches(text: str, patterns: list[str]) -> int:
    return sum(bool(re.search(pattern, text, flags=re.IGNORECASE)) for pattern in patterns)


def openalex_request(params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{OPENALEX_URL}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "cvd-sic-paper-digest/1.0 (GitHub Actions)",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == 2:
                raise
            print(f"OpenAlex request failed ({exc}); retrying...", file=sys.stderr)
            time.sleep(2 ** attempt)
    raise RuntimeError("OpenAlex request failed")


def paper_identity(work: dict[str, Any]) -> str:
    doi = normalize_text(work.get("doi") or "").lower()
    if doi:
        return f"doi:{doi.removeprefix('https://doi.org/')}"
    openalex_id = work.get("id")
    if openalex_id:
        return f"openalex:{openalex_id}"
    title = normalize_text(work.get("display_name") or "").lower()
    return f"title:{hashlib.sha256(title.encode()).hexdigest()}"


def title_identity(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return f"title:{hashlib.sha256(normalized.encode()).hexdigest()}"


def lexical_score(paper: dict[str, Any], config: dict[str, Any]) -> tuple[int, list[str]]:
    text = " ".join(
        part
        for part in (
            paper.get("title", ""),
            paper.get("abstract", ""),
            paper.get("journal", ""),
        )
        if part
    )
    groups = config["concept_groups"]
    if not all(matches_any(text, patterns) for patterns in groups.values()):
        return 0, []

    labels = config["preference_terms"]
    score = 55
    matched_labels: list[str] = []
    for label, patterns in labels.items():
        hits = count_matches(text, patterns)
        if hits:
            score += min(hits * 8, 15)
            matched_labels.append(label)

    lower = text.lower()
    if "lithium-ion" in lower or "lithium ion" in lower or "li-ion" in lower:
        score += 8
        matched_labels.append("锂离子电池")
    if "sodium-ion" in lower and not any(
        term in lower for term in ("lithium", "li-ion", "li ion")
    ):
        return 0, []
    if "review" in lower or "progress" in lower:
        score += 3
        matched_labels.append("综述")

    openalex_relevance = float(paper.get("openalex_relevance") or 0)
    score += min(round(openalex_relevance / 5), 20)
    return min(score, 100), list(dict.fromkeys(matched_labels))


def fetch_candidates(config: dict[str, Any]) -> list[dict[str, Any]]:
    today = date.today()
    start = today - timedelta(days=int(config["lookback_days"]))
    mailto = os.environ.get("OPENALEX_MAILTO") or "paper-digest@users.noreply.github.com"
    by_id: dict[str, dict[str, Any]] = {}

    for index, search_query in enumerate(config["queries"]):
        if index:
            time.sleep(1)
        payload = openalex_request(
            {
                "search": search_query,
                "filter": f"from_publication_date:{start.isoformat()},to_publication_date:{today.isoformat()}",
                "sort": "relevance_score:desc",
                "per-page": int(config["openalex_per_query"]),
                "mailto": mailto,
            }
        )
        for work in payload.get("results", []):
            publication_date = work.get("publication_date") or ""
            if not publication_date or not (start.isoformat() <= publication_date <= today.isoformat()):
                continue
            if work.get("is_retracted"):
                continue

            location = work.get("primary_location") or {}
            source = location.get("source") or {}
            oa_location = work.get("best_oa_location") or {}
            title = normalize_text(html.unescape(work.get("display_name") or "Untitled"))
            abstract = normalize_text(
                reconstruct_abstract(work.get("abstract_inverted_index"))
            )
            paper = {
                "id": paper_identity(work),
                "title": title,
                "abstract": abstract,
                "publication_date": publication_date,
                "journal": normalize_text(source.get("display_name") or "未注明来源"),
                "authors": [
                    authorship.get("author", {}).get("display_name", "")
                    for authorship in work.get("authorships", [])[:4]
                    if authorship.get("author", {}).get("display_name")
                ],
                "doi": (work.get("doi") or "").removeprefix("https://doi.org/"),
                "url": (
                    work.get("doi")
                    or location.get("landing_page_url")
                    or work.get("id")
                    or ""
                ),
                "pdf_url": oa_location.get("pdf_url") or "",
                "openalex_relevance": work.get("relevance_score") or 0,
            }
            score, matched = lexical_score(paper, config)
            if score < int(config["minimum_score"]):
                continue
            paper["score"] = score
            paper["matched"] = matched

            existing = by_id.get(paper["id"])
            if existing is None or score > existing["score"]:
                by_id[paper["id"]] = paper

    unique_by_title: dict[str, dict[str, Any]] = {}
    for paper in by_id.values():
        title_key = title_identity(paper["title"])
        existing = unique_by_title.get(title_key)
        if existing is None or paper["score"] > existing["score"]:
            unique_by_title[title_key] = paper

    return sorted(
        unique_by_title.values(),
        key=lambda paper: (
            paper["score"],
            paper["publication_date"],
            float(paper.get("openalex_relevance") or 0),
        ),
        reverse=True,
    )


def call_ollama(messages: list[dict[str, str]], config: dict[str, Any], max_tokens: int) -> str:
    payload = {
        "model": config["model"],
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 4096,
            "num_predict": max_tokens,
        },
    }
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.load(response)
    content = (result.get("message") or {}).get("content", "").strip()
    if not content:
        raise RuntimeError("The local model returned an empty response")
    return content


def summarize_paper(paper: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    prompt = f"""你是锂电池材料领域的科研简报编辑。请只根据下面的标题和摘要，用简体中文生成：
1. 第一行以“标题：”开头，给出准确、专业的中文标题翻译。
2. 第二行以“摘要：”开头，用不超过180字写3句话：
   - 研究对象、材料体系和制备/表征方法；
   - 微观结构、机理或关键结果；
   - 对“CVD Si/C 负极材料及微观结构”研究的相关性或局限。

不得编造摘要中没有的数据。若原文未给出某项信息，请直接说明未提供。

英文标题：{paper['title']}
英文摘要：{paper['abstract'] or '摘要未提供'}
"""
    try:
        output = call_ollama(
            [
                {
                    "role": "system",
                    "content": "你是一名严谨的电池材料研究人员，只依据给定材料作答。",
                },
                {"role": "user", "content": prompt},
            ],
            config,
            300,
        )
        title_match = re.search(
            r"^\s*(?:[-#>*]\s*)*\*{0,2}标题\*{0,2}\s*[：:]\s*(.+)$",
            output,
            flags=re.MULTILINE,
        )
        abstract_match = re.search(
            r"^\s*(?:[-#>*]\s*)*\*{0,2}摘要\*{0,2}\s*[：:]\s*(.+)$",
            output,
            flags=re.MULTILINE | re.DOTALL,
        )
        title_zh = normalize_text(title_match.group(1)) if title_match else paper["title"]
        summary_zh = (
            normalize_text(abstract_match.group(1))
            if abstract_match
            else normalize_text(output)
        )
        return title_zh, summary_zh
    except Exception as exc:
        print(f"Warning: local summary generation failed for {paper['id']}: {exc}", file=sys.stderr)
        return (
            paper["title"],
            "本地模型暂时未能生成中文摘要。以下为论文原文摘要："
            + (paper["abstract"] or "摘要未提供"),
        )


def make_overview(papers: list[dict[str, Any]], config: dict[str, Any]) -> str:
    evidence = "\n".join(
        f"- {paper.get('title_zh') or paper['title']}：{paper['summary_zh']}"
        for paper in papers
    )
    prompt = f"""下面是一批关于“{config['topic_zh']}”的新论文简报。
请用简体中文写3—4条本批次研究趋势，总字数不超过260字。
重点归纳材料设计、CVD/硅碳复合工艺、微观结构与电化学性能之间的关系。
只能依据提供的简报，不要逐篇复述，不要添加未出现的数据或结论。

{evidence}
"""
    try:
        return call_ollama(
            [
                {
                    "role": "system",
                    "content": "你是一名严谨的学术综述编辑，仅依据给定内容归纳。",
                },
                {"role": "user", "content": prompt},
            ],
            config,
            420,
        )
    except Exception as exc:
        print(f"Warning: overview generation failed: {exc}", file=sys.stderr)
        journals = sorted({paper["journal"] for paper in papers})
        return (
            f"今日共筛选出 {len(papers)} 篇与 Si/C 负极或硅碳微观结构相关的新论文，"
            f"来源包括 {'、'.join(journals)}。请结合各篇摘要判断其与 CVD 工艺的直接相关性。"
        )


def render_plain_text(
    papers: list[dict[str, Any]], overview: str, config: dict[str, Any]
) -> str:
    lines = [
        f"{config['topic_zh']}｜每日文献简报",
        date.today().isoformat(),
        "",
        "编辑导语",
        overview,
        "",
    ]
    for index, paper in enumerate(papers, start=1):
        lines.extend(
            [
                f"{index}. {paper.get('title_zh') or paper['title']}",
                f"原题：{paper['title']}",
                f"来源：{paper['journal']}｜{paper['publication_date']}",
                f"相关性：{paper['score']}/100"
                + (f"（{', '.join(paper['matched'])}）" if paper["matched"] else ""),
                paper["summary_zh"],
                f"链接：{paper['url']}",
                "",
            ]
        )
    lines.append("由 OpenAlex + 本地 Qwen 模型自动生成；请以论文原文为准。")
    return "\n".join(lines)


def render_html(papers: list[dict[str, Any]], overview: str, config: dict[str, Any]) -> str:
    cards: list[str] = []
    for index, paper in enumerate(papers, start=1):
        authors = "、".join(paper["authors"]) or "作者未提供"
        pdf_link = (
            f'<a href="{html.escape(paper["pdf_url"])}" '
            'style="color:#0f766e;text-decoration:none;margin-left:14px;">PDF</a>'
            if paper["pdf_url"]
            else ""
        )
        matched = "、".join(html.escape(label) for label in paper["matched"]) or "主题相关"
        cards.append(
            f"""
            <article style="background:#ffffff;border:1px solid #dce7e4;border-radius:14px;
                padding:20px 22px;margin:0 0 16px;">
              <div style="font-size:12px;color:#64748b;margin-bottom:8px;">
                {index:02d} · {html.escape(paper['publication_date'])} ·
                {html.escape(paper['journal'])}
              </div>
              <h2 style="font-size:19px;line-height:1.45;color:#16332d;margin:0 0 7px;">
                {html.escape(paper.get('title_zh') or paper['title'])}
              </h2>
              <div style="font-size:13px;line-height:1.5;color:#64748b;margin-bottom:12px;">
                {html.escape(paper['title'])}
              </div>
              <div style="font-size:13px;line-height:1.5;color:#64748b;margin-bottom:12px;">
                {html.escape(authors)}
              </div>
              <p style="font-size:15px;line-height:1.8;color:#243b36;margin:0 0 16px;">
                {html.escape(paper['summary_zh'])}
              </p>
              <div style="border-top:1px solid #edf2f1;padding-top:12px;font-size:13px;">
                <span style="color:#0f766e;font-weight:600;">相关性 {paper['score']}/100</span>
                <span style="color:#64748b;margin-left:10px;">{matched}</span>
                <span style="float:right;">
                  <a href="{html.escape(paper['url'])}"
                     style="color:#0f766e;text-decoration:none;">论文页面</a>{pdf_link}
                </span>
              </div>
            </article>
            """
        )

    overview_html = "".join(
        f"<li style='margin:0 0 8px;'>{html.escape(line.lstrip('•- ').strip())}</li>"
        for line in overview.splitlines()
        if line.strip()
    )
    generated_at = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="zh-CN">
  <body style="margin:0;padding:0;background:#f2f7f5;">
    <main style="max-width:720px;margin:0 auto;padding:28px 16px;
      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',
      'Microsoft YaHei',sans-serif;">
      <header style="background:#153c34;color:#ffffff;border-radius:16px;
        padding:26px 26px 22px;margin-bottom:18px;">
        <div style="font-size:12px;letter-spacing:2px;opacity:.72;">
          DAILY RESEARCH BRIEF
        </div>
        <h1 style="font-size:25px;line-height:1.4;margin:8px 0 7px;">
          {html.escape(config['topic_zh'])}
        </h1>
        <div style="font-size:13px;opacity:.78;">
          {date.today().isoformat()} · 共 {len(papers)} 篇新论文
        </div>
      </header>
      <section style="background:#e8f1ee;border-radius:14px;padding:20px 24px;
        margin-bottom:18px;color:#28433d;">
        <h2 style="font-size:15px;margin:0 0 12px;">编辑导语</h2>
        <ul style="font-size:14px;line-height:1.75;margin:0;padding-left:20px;">
          {overview_html}
        </ul>
      </section>
      {''.join(cards)}
      <footer style="font-size:12px;line-height:1.7;color:#73857f;padding:8px 4px 24px;">
        自动生成于 {generated_at}（Asia/Shanghai）。来源：OpenAlex；摘要由本地
        Qwen 模型生成。内容仅供筛选参考，请以论文原文为准。
      </footer>
    </main>
  </body>
</html>"""


def send_email(
    subject: str,
    plain_text: str,
    html_body: str,
) -> None:
    recipient = os.environ.get("MAIL_TO", "").strip()
    username = os.environ.get("SMTP_USER", "").strip() or recipient
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    sender = os.environ.get("MAIL_FROM", "").strip() or username
    host = os.environ.get("SMTP_HOST", "smtp.qq.com").strip()
    port = int(os.environ.get("SMTP_PORT", "465"))

    if not recipient or not username or not password:
        raise RuntimeError(
            "Email is not configured. Add MAIL_TO, SMTP_USER, and SMTP_PASSWORD "
            "as GitHub Actions secrets, or run with dry_run=true."
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"CVD Si/C 文献雷达 <{sender}>"
    message["To"] = recipient
    message.set_content(plain_text)
    message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=45) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)


def main() -> int:
    config = load_json(CONFIG_PATH, {})
    if not config:
        raise RuntimeError(f"Missing config: {CONFIG_PATH}")
    dry_run = os.environ.get("DRY_RUN", "false").lower() in {"1", "true", "yes"}

    seen_state = load_json(STATE_PATH, {"seen": []})
    seen = set(seen_state.get("seen", []))
    candidates = fetch_candidates(config)
    fresh = [
        paper
        for paper in candidates
        if paper["id"] not in seen and title_identity(paper["title"]) not in seen
    ][: int(config["max_papers"])]

    print(f"Fetched {len(candidates)} relevant candidates; {len(fresh)} are new.")
    if not fresh:
        print("No new papers today.")
        return 0

    for index, paper in enumerate(fresh, start=1):
        print(f"Summarizing {index}/{len(fresh)}: {paper['title']}")
        paper["title_zh"], paper["summary_zh"] = summarize_paper(paper, config)

    overview = make_overview(fresh, config)
    plain_text = render_plain_text(fresh, overview, config)
    html_body = render_html(fresh, overview, config)
    REPORT_DIR.mkdir(exist_ok=True)
    report_base = REPORT_DIR / f"daily-{date.today().isoformat()}"
    report_base.with_suffix(".txt").write_text(plain_text, encoding="utf-8")
    report_base.with_suffix(".html").write_text(html_body, encoding="utf-8")

    if dry_run:
        print("Dry run complete; email was not sent.")
        return 0

    subject = f"【每日文献简报】CVD Si/C 负极与微观结构｜{date.today().isoformat()}"
    send_email(subject, plain_text, html_body)
    print("Email sent.")

    updated_seen = list(seen | {paper["id"] for paper in fresh} | {
        title_identity(paper["title"]) for paper in fresh
    })
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"seen": updated_seen[-5000:]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
