#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""电力资讯站 —— 构建/采集结果通知。

用于每日自动化在**失败时**主动告警（成功时也发一条简报，便于确认链路通）。

webhook 从环境变量读取，不硬编码：
    POWHOT_DINGTALK_WEBHOOK  —— 钉钉群机器人 webhook（含 access_token）
    POWHOT_DINGTALK_SECRET   —— 若机器人开启了「加签」，填密钥

未配置 webhook 时脚本静默跳过（不报错），保证自动化不会因缺配置而中断。

用法：
    python3 notify.py --status ok   --text "今日 28 条新增，已发布"
    python3 notify.py --status fail --text "build_site.py 退出码 1：<错误原文>"
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request

WEBHOOK = os.environ.get("POWHOT_DINGTALK_WEBHOOK", "").strip()
SECRET = os.environ.get("POWHOT_DINGTALK_SECRET", "").strip()

TITLE = {"ok": "✅ 电力资讯站·正常", "fail": "🔴 电力资讯站·异常", "warn": "⚠️ 电力资讯站·注意"}
EMOJI = {"ok": "🟢", "fail": "🔴", "warn": "🟠"}


def _signed_url() -> str:
    if not SECRET:
        return WEBHOOK
    ts = str(round(time.time() * 1000))
    raw = f"{ts}\n{SECRET}".encode("utf-8")
    sign = base64.b64encode(hmac.new(SECRET.encode("utf-8"), raw, hashlib.sha256).digest())
    sep = "&" if "?" in WEBHOOK else "?"
    return f"{WEBHOOK}{sep}timestamp={ts}&sign={urllib.parse.quote_plus(sign)}"


def send(status: str, text: str, extra: str = "") -> bool:
    if not WEBHOOK:
        print("[notify] 未配置 POWHOT_DINGTALK_WEBHOOK，跳过通知")
        return False

    lines = [
        f"### {TITLE.get(status, TITLE['warn'])}",
        "",
        f"{EMOJI.get(status, '')} {text}",
    ]
    if extra:
        lines += ["", f"> {extra}"]
    lines += ["", f"时间：{time.strftime('%Y-%m-%d %H:%M')}"]
    body = {
        "msgtype": "markdown",
        "markdown": {"title": TITLE.get(status, "电力资讯站"), "text": "\n".join(lines)},
    }
    url = _signed_url()
    try:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.load(r)
        if resp.get("errcode") == 0:
            print("[notify] 已发送")
            return True
        print(f"[notify] 发送失败: {resp}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[notify] 发送异常: {e}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", choices=["ok", "fail", "warn"], default="ok")
    ap.add_argument("--text", required=True, help="一句话结论")
    ap.add_argument("--extra", default="", help="补充说明（错误原文、链接等）")
    args = ap.parse_args()
    ok = send(args.status, args.text, args.extra)
    sys.exit(0 if ok or not WEBHOOK else 1)


if __name__ == "__main__":
    main()
