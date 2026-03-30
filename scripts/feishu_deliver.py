#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Builders Digest → 飞书推送
读取仓库中的 feed JSON，生成中文日报，推送到飞书群机器人
运行环境：GitHub Actions（每天 10:00 北京时间自动执行）
"""

import json
import os
import urllib.request
import datetime

# ── 配置 ──────────────────────────────────────────────────────────────────────

WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK", "")

# feed 文件路径（GitHub Actions checkout 后在仓库根目录）
FEED_X       = "feed-x.json"
FEED_PODCASTS = "feed-podcasts.json"
FEED_BLOGS   = "feed-blogs.json"

TOP_N        = 12   # 最多展示几位 builder（按热度排）
MIN_LIKES    = 30   # 过滤点赞数低于此值的推文

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def fmt(n):
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)

def clip(text, n=120):
    text = " ".join(text.split())
    return text[:n] + "…" if len(text) > n else text

def post_feishu(payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req  = urllib.request.Request(
        WEBHOOK_URL, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# ── 飞书内容构建 ───────────────────────────────────────────────────────────────

# 已知 builder 的中文职位/简介（按 handle 映射，方便快速查找）
ROLES = {
    "karpathy":    "前 Tesla AI 总监 · OpenAI 创始成员",
    "sama":        "OpenAI CEO",
    "trq212":      "Claude Code 团队 · Anthropic",
    "AmandaAskell":"对齐研究员 · Anthropic",
    "steipete":    "OpenClaw 创始人",
    "rauchg":      "Vercel CEO",
    "amasad":      "Replit CEO",
    "levie":       "Box CEO",
    "garrytan":    "Y Combinator CEO",
    "swyx":        "AI Engineer · Latent Space",
    "joshwoodward":"VP · Google Labs",
    "kevinweil":   "VP Science · OpenAI",
    "danshipper":  "Every CEO",
    "zarazhangrui":"Builder",
    "nikunj":      "Partner · FPV Ventures",
    "petergyang":  "AI 产品博主",
    "thenanyu":    "Linear 产品负责人",
    "adityaag":    "South Park Commons 合伙人",
    "steipete":    "OpenClaw 创始人",
}

def role_of(b):
    handle = b.get("handle", "")
    if handle in ROLES:
        return ROLES[handle]
    bio = b.get("bio", "")
    # 从 bio 提取关键词
    for kw in ["CEO", "CTO", "Founder", "Partner", "VP", "Head of", "Director"]:
        if kw.lower() in bio.lower():
            idx = bio.lower().find(kw.lower())
            return bio[idx:idx+40].split("\n")[0].strip()
    return ""

def build_blocks(feed_x, feed_pods, feed_blogs):
    today = datetime.datetime.now()
    date_str = f"{today.month}月{today.day}日"

    builders = [b for b in feed_x.get("x", []) if b.get("tweets")]

    def best_likes(b):
        return max((t.get("likes", 0) for t in b["tweets"]), default=0)

    featured = [
        b for b in sorted(builders, key=best_likes, reverse=True)
        if best_likes(b) >= MIN_LIKES
    ][:TOP_N]

    blocks = []

    # 头部
    blocks += [
        [{"tag": "text", "text": f"今日追踪 {len(builders)} 位 Builder，精选 {len(featured)} 条热门动态 👇"}],
        [{"tag": "text", "text": " "}],
    ]

    # X / Twitter
    if featured:
        blocks += [
            [{"tag": "text", "text": "━━━━  𝕏 Builder 动态  ━━━━"}],
            [{"tag": "text", "text": " "}],
        ]
        for b in featured:
            name   = b["name"]
            role   = role_of(b)
            top    = max(b["tweets"], key=lambda t: t.get("likes", 0))
            likes  = top.get("likes", 0)
            rts    = top.get("retweets", 0)
            text   = clip(top.get("text", ""))
            url    = top.get("url", "")

            header = f"• {name}"
            if role:
                header += f"（{role}）"
            if likes >= 1000:
                header += f"  🔥 {fmt(likes)} 赞"
            elif likes > 0:
                header += f"  ❤️ {fmt(likes)}"

            blocks.append([{"tag": "text", "text": header}])
            blocks.append([{"tag": "text", "text": f"  {text}"}])
            if url:
                blocks.append([{"tag": "a", "text": "  → 查看原推", "href": url}])
            blocks.append([{"tag": "text", "text": " "}])

    # 播客
    episodes = [e for e in feed_pods.get("podcasts", []) if e.get("url")]
    if episodes:
        blocks += [[{"tag": "text", "text": "━━━━  🎙 播客  ━━━━"}], [{"tag": "text", "text": " "}]]
        for ep in episodes[:2]:
            pod  = ep.get("podcastName", ep.get("name", ""))
            ttl  = ep.get("title", "")
            url  = ep.get("url", "")
            blocks.append([{"tag": "text", "text": f"• {pod}"}])
            if ttl:
                blocks.append([{"tag": "text", "text": f"  《{ttl}》"}])
            if url:
                blocks.append([{"tag": "a", "text": "  → 收听节目", "href": url}])
            blocks.append([{"tag": "text", "text": " "}])

    # 博客
    articles = [a for a in feed_blogs.get("blogs", []) if a.get("url")]
    if articles:
        blocks += [[{"tag": "text", "text": "━━━━  📝 官方博客  ━━━━"}], [{"tag": "text", "text": " "}]]
        for art in articles[:3]:
            src = art.get("source", "")
            ttl = clip(art.get("title", ""), 60)
            url = art.get("url", "")
            label = f"• [{src}] {ttl}" if src else f"• {ttl}"
            blocks.append([{"tag": "text", "text": label}])
            if url:
                blocks.append([{"tag": "a", "text": "  → 阅读原文", "href": url}])
            blocks.append([{"tag": "text", "text": " "}])

    # 脚注
    blocks += [
        [{"tag": "text", "text": "─────────────────────────────"}],
        [{"tag": "a", "text": "由 Follow Builders Skill 生成", "href": "https://github.com/zarazhangrui/follow-builders"}],
    ]

    title = f"⚡ AI Builders Digest · {date_str}"
    return title, blocks

# ── 主程序 ────────────────────────────────────────────────────────────────────

def main():
    if not WEBHOOK_URL:
        raise SystemExit("❌  未设置 FEISHU_WEBHOOK 环境变量（GitHub Secret）")

    print("📖  读取 feed 文件...")
    feed_x     = load(FEED_X)
    feed_pods  = load(FEED_PODCASTS)
    feed_blogs = load(FEED_BLOGS)

    print("✍️   生成日报内容...")
    title, blocks = build_blocks(feed_x, feed_pods, feed_blogs)

    payload = {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": title, "content": blocks}}}
    }

    print("🚀  推送到飞书...")
    result = post_feishu(payload)
    code = result.get("code", result.get("StatusCode", -1))
    if code == 0:
        print(f"✅  推送成功！标题：{title}")
    else:
        raise SystemExit(f"❌  推送失败：{result}")

if __name__ == "__main__":
    main()
