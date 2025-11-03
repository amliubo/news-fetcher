import os
import asyncio
from openai import AsyncOpenAI
from supabase import create_client

# 初始化
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PROMPT_TEMPLATE = """
请为以下新闻生成一个简短的中文摘要，要求口语化、适合配音朗读，限制在60字以内。

标题：{title}
内容：{description}

输出格式：直接输出摘要文本，不要前缀或说明。
"""

async def generate_summary(title, description):
    prompt = PROMPT_TEMPLATE.format(title=title or "无标题", description=description or "无内容")
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=120,
        )
        summary = response.choices[0].message.content.strip()
        print(f"[AI摘要] {title[:20]} → {summary}")
        return summary
    except Exception as e:
        print(f"[Error] 生成摘要失败：{e}")
        return None

async def main():
    # 读取最近的新闻（没有摘要的）
    res = supabase.table("news").select("*").is_("ai_summary", None).order("published_at", desc=True).limit(10).execute()
    articles = res.data or []

    if not articles:
        print("[Info] 没有需要生成摘要的新闻")
        return

    print(f"[Info] 待生成摘要新闻数量：{len(articles)}")

    for article in articles:
        summary = await generate_summary(article.get("title"), article.get("description"))
        if summary:
            # 更新数据库
            supabase.table("news").update({"ai_summary": summary}).eq("id", article["id"]).execute()
            print(f"[DB] 已更新摘要 → {article['id']}")

if __name__ == "__main__":
    asyncio.run(main())
