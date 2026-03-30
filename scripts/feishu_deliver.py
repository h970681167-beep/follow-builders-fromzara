#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Builders Digest → 飞书推送（Claude API 中文摘要版）
每天从仓库读取 feed JSON，调用 Claude 生成中文日报，推送飞书群机器人

GitHub Secrets 需要：
  FEISHU_WEBHOOK   飞书群机器人 Webhook 地址
  ANTHROPIC_API_KEY  Anthropic API Key（用于生成中文摘要）
"""

import json, os, urllib.request, urllib.error, datetime, sys, textwrap

FEISHU_WEBHOOK   = os.environ["FEISHU_WEBHOOK"]
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "").strip()

FEED_X        = "feed-x.json"
FEED_PODCASTS = "feed-podcasts.json"
FEED_BLOGS    = "feed-blogs.json"

TOP_N      = 10   # 最多展示几位 builder
MIN_LIKES  = 50   # 低于此点赞数不展示

# ── 工具 ───────────────────────────────────────────────────────────────────────

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def fmt(n):
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)

def http_post(url, payload, headers=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req  = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise Exception(f"HTTP {e.code} from {url}:\n{body}") from e

# ── Claude API：生成中文摘要 ────────────────────────────────────────────────────

def generate_chinese_summaries(builders):
    """
    把 builder 的推文列表发给 Claude，让它返回 JSON 格式的中文摘要。
    每位 builder 返回：name / role / summary / url（最热那条推文的 URL）
    """
    items = []
    for b in builders:
        top = max(b["tweets"], key=lambda t: t.get("likes", 0))
        all_tweets = "\n".join(
            f'[{t.get("likes",0)} 赞] {t.get("text","")[:300]}'
            for t in sorted(b["tweets"], key=lambda t: t.get("likes",0), reverse=True)[:3]
        )
        items.append({
            "name":   b["name"],
            "handle": b.get("handle", ""),
            "bio":    b.get("bio", "")[:100],
            "tweets": all_tweets,
            "top_url": top.get("url", ""),
            "top_likes": top.get("likes", 0),
        })

    prompt = textwrap.dedent(f"""
        你是一位 AI 行业分析师，为中文读者撰写每日 AI builder 动态摘要。

        以下是今天各位 builder 在 X（Twitter）上的最新推文，请为每位写一段 2-3 句的中文摘要。

        要求：
        - 提炼核心观点、产品发布、数据洞察或行业判断，不要逐字翻译
        - 语言简洁有力，适合快速阅读
        - 如推文包含具体数字、产品名称、公司名，要保留
        - 如推文只是闲聊或无实质内容，summary 填 null
        - role 字段：根据 bio 提炼 1-6 个字的中文职位/身份（如"OpenAI CEO"、"Anthropic 对齐研究员"、"Vercel CEO"）

        以下是 builder 数据（JSON 列表）：
        {json.dumps(items, ensure_ascii=False, indent=2)}

        请严格返回如下 JSON 格式，不要有任何额外说明：
        [
          {{
            "name": "...",
            "role": "...",
            "summary": "...",
            "url": "...",
            "likes": 0
          }},
          ...
        ]
    """).strip()

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}]
    }
    result = http_post(
        "https://api.anthropic.com/v1/messages",
        payload,
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        }
    )
    raw = result["content"][0]["text"].strip()
    # 提取 JSON（有时 Claude 会加 ```json 代码块）
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)

# ── 飞书消息构建 ───────────────────────────────────────────────────────────────

def build_feishu_payload(summaries, feed_pods, feed_blogs):
    today    = datetime.datetime.now()
    date_str = f"{today.month}月{today.day}日"
    title    = f"⚡ AI Builders Digest · {date_str}"

    blocks = [
        [{"tag": "text", "text": f"今日精选 {len(summaries)} 位 AI Builder 热门动态 👇"}],
        [{"tag": "text", "text": " "}],
        [{"tag": "text", "text": "━━━━  𝕏 Builder 动态  ━━━━"}],
        [{"tag": "text", "text": " "}],
    ]

    for s in summaries:
        if not s.get("summary"):
            continue
        name  = s["name"]
        role  = s.get("role", "")
        summ  = s["summary"]
        url   = s.get("url", "")
        likes = s.get("likes", 0)

        header = f"• {name}"
        if role:
            header += f"（{role}）"
        if likes >= 1000:
            header += f"  🔥 {fmt(likes)} 赞"
        elif likes >= 100:
            header += f"  ❤️ {fmt(likes)}"

        blocks.append([{"tag": "text", "text": header}])
        blocks.append([{"tag": "text", "text": f"  {summ}"}])
        if url:
            blocks.append([{"tag": "a", "text": "  → 查看原推", "href": url}])
        blocks.append([{"tag": "text", "text": " "}])

    # 播客
    episodes = [e for e in feed_pods.get("podcasts", []) if e.get("url")]
    if episodes:
        blocks += [[{"tag": "text", "text": "━━━━  🎙 播客  ━━━━"}], [{"tag": "text", "text": " "}]]
        for ep in episodes[:2]:
            blocks.append([{"tag": "text", "text": f"• {ep.get('podcastName', '')}  《{ep.get('title', '')}》"}])
            blocks.append([{"tag": "a", "text": "  → 收听节目", "href": ep["url"]}])
            blocks.append([{"tag": "text", "text": " "}])

    # 博客
    articles = [a for a in feed_blogs.get("blogs", []) if a.get("url")]
    if articles:
        blocks += [[{"tag": "text", "text": "━━━━  📝 官方博客  ━━━━"}], [{"tag": "text", "text": " "}]]
        for art in articles[:3]:
            src = art.get("source", "")
            ttl = art.get("title", "")[:60]
            blocks.append([{"tag": "text", "text": f"• [{src}] {ttl}" if src else f"• {ttl}"}])
            blocks.append([{"tag": "a", "text": "  → 阅读原文", "href": art["url"]}])
            blocks.append([{"tag": "text", "text": " "}])

    blocks += [
        [{"tag": "text", "text": "─────────────────────────────"}],
        [{"tag": "a", "text": "由 Follow Builders Skill 生成", "href": "https://github.com/zarazhangrui/follow-builders"}],
    ]

    return {"msg_type": "post", "content": {"post": {"zh_cn": {"title": title, "content": blocks}}}}

# ── 主程序 ─────────────────────────────────────────────────────────────────────

def main():
    print("📖  读取 feed...")
    fx    = load(FEED_X)
    fpods = load(FEED_PODCASTS)
    fblogs= load(FEED_BLOGS)

    builders = [b for b in fx.get("x", []) if b.get("tweets")]
    builders_sorted = sorted(
        builders,
        key=lambda b: max(t.get("likes", 0) for t in b["tweets"]),
        reverse=True
    )
    featured = [
        b for b in builders_sorted
        if max(t.get("likes", 0) for t in b["tweets"]) >= MIN_LIKES
    ][:TOP_N]

    print(f"✍️   用 Claude 生成 {len(featured)} 位 builder 的中文摘要...")
    if not ANTHROPIC_KEY:
        sys.exit("❌  未设置 ANTHROPIC_API_KEY，无法生成中文摘要")

    summaries = generate_chinese_summaries(featured)
    print(f"     ✓ 获得 {len(summaries)} 条摘要")

    payload = build_feishu_payload(summaries, fpods, fblogs)

    print("🚀  推送到飞书...")
    result = http_post(FEISHU_WEBHOOK, payload)
    if result.get("code", -1) == 0:
        print(f"✅  推送成功！{payload['content']['post']['zh_cn']['title']}")
    else:
        sys.exit(f"❌  推送失败：{result}")

if __name__ == "__main__":
    main()
