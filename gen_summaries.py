#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为缺少 AI 摘要的条目补生成摘要。

背景：站点早期几轮采集时，采集自动化里还没有生成 AI 摘要的步骤，
导致 204 条里有约 90 条只有原文、没有摘要。本脚本用 LLM 批量补齐。

产物：summaries.json（{原文URL: 摘要}），与采集侧写入 reports/*.md 的摘要
     在构建时合并 —— 独立存放的好处是重跑不会污染采集归档。

用法：
    export ARK_API_KEY=...          # 火山引擎豆包（默认，国内直连）
    python3 gen_summaries.py        # 只补缺失的
    python3 gen_summaries.py --limit 10
    python3 gen_summaries.py --redo # 忽略已有，全部重生成

    也可用 OpenRouter（需能访问境外）：
    SUMMARY_BACKEND=openrouter OPENROUTER_API_KEY=sk-or-... python3 gen_summaries.py

注：OpenRouter 上的 google/* 模型对中国区返回 403 "not available in your
region"，因此默认走火山引擎豆包（OpenAI 兼容接口）。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = "/Users/xiaodongzheng/WorkBuddy/电力资讯站"
SITE = os.path.join(ROOT, "site")
SUMMARIES_PATH = os.path.join(ROOT, "summaries.json")

# 后端：ark（火山引擎豆包，默认）/ openrouter
BACKEND = os.environ.get("SUMMARY_BACKEND", "ark").lower()
if BACKEND == "openrouter":
    API_URL = os.environ.get("OPENROUTER_API_BASE",
                             "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"
    API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
    MODEL = os.environ.get("SUMMARY_MODEL", "deepseek/deepseek-chat-v3.1")
else:
    API_URL = os.environ.get("ARK_API_BASE",
                             "https://ark.cn-beijing.volces.com/api/v3").rstrip("/") \
        + "/chat/completions"
    API_KEY = os.environ.get("ARK_API_KEY", "")
    MODEL = os.environ.get("SUMMARY_MODEL", "doubao-seed-2-0-mini-260215")

SYSTEM_PROMPT = (
    "你是电力行业资讯编辑，服务于电力交易与电网规划从业人员。"
    "用 2-3 句话概括这份资料，**总长控制在 120 字以内**："
    "先说核心结论或政策要点，再给关键数据（文号、比例、金额、时间节点），"
    "必要时点明影响范围或市场含义。"
    "要求：直接陈述，不要客套话，不要复述标题，不要写“本文/该文”这类主语，"
    "不要换行，不要在结尾追问或补充说明。"
)


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def read_body(item_id: str, limit: int = 2600) -> str:
    p = os.path.join(SITE, "data", "bodies", f"{item_id}.json")
    if not os.path.isfile(p):
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return "".join(d.get("paragraphs") or [])[:limit]
    except Exception:
        return ""


def call_llm(model_key: str, title: str, org: str, body: str, retries: int = 3) -> str:
    user = f"标题：{title}\n来源：{org}\n\n正文：\n{body}"
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "max_tokens": 220,
        "temperature": 0.3,
    }).encode("utf-8")

    last = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                API_URL, data=payload,
                headers={
                    "Authorization": f"Bearer {model_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://powhot-electric-news.app.workbuddy.host",
                    "X-Title": "POWHOT summary backfill",
                },
            )
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            txt = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
            txt = re.sub(r"\s+", " ", (txt or "")).strip()
            if txt:
                return txt
            last = "空响应"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:160].decode('utf-8', 'ignore')}"
        except Exception as e:
            last = str(e)
        time.sleep(2 + attempt * 2)
    raise RuntimeError(last or "调用失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少条（0=全部）")
    ap.add_argument("--redo", action="store_true", help="忽略已有摘要，全部重生成")
    ap.add_argument("--sleep", type=float, default=0.4, help="每条之间的间隔秒数")
    args = ap.parse_args()

    if not API_KEY:
        print(f"❌ 缺少 API key（后端 {BACKEND}，需要 "
              f"{'OPENROUTER_API_KEY' if BACKEND == 'openrouter' else 'ARK_API_KEY'}）",
              file=sys.stderr)
        sys.exit(1)

    news = load_json(os.path.join(SITE, "data", "news.json"), {})
    items = news.get("items") or []
    if not items:
        print("❌ 站点数据为空，请先运行 build_site.py", file=sys.stderr)
        sys.exit(1)

    existing = {} if args.redo else load_json(SUMMARIES_PATH, {})
    todo = [it for it in items if args.redo or not it.get("ai")]
    # 已有 results 的跳过（增量续跑）
    todo = [it for it in todo if it["url"] not in existing]
    if args.limit:
        todo = todo[: args.limit]

    print(f"📋 待补摘要：{len(todo)} 条（后端 {BACKEND} / 模型 {MODEL}）")
    if not todo:
        print("✅ 无需补全")
        return

    ok = fail = 0
    for idx, it in enumerate(todo, 1):
        body = read_body(it["id"])
        if len(body) < 60:
            print(f"  [{idx}/{len(todo)}] 跳过（正文过短）: {it['title'][:34]}")
            existing[it["url"]] = it.get("excerpt", "")[:180]
            fail += 1
            continue
        try:
            summary = call_llm(API_KEY, it["title"], it.get("org", ""), body)
            existing[it["url"]] = summary
            ok += 1
            print(f"  [{idx}/{len(todo)}] ✔ {it['title'][:34]}")
            print(f"        {summary[:88]}")
        except Exception as e:
            fail += 1
            print(f"  [{idx}/{len(todo)}] ✘ {it['title'][:30]} -> {str(e)[:90]}")
        if idx % 5 == 0 or idx == len(todo):
            with open(SUMMARIES_PATH, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=1)
        time.sleep(args.sleep)

    with open(SUMMARIES_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    print(f"\n✅ 完成：成功 {ok}，失败 {fail}；累计摘要 {len(existing)} 条")
    print(f"   已写入 {SUMMARIES_PATH}")


if __name__ == "__main__":
    main()
