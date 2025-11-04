import os
import asyncio
import requests
from datetime import datetime
from openai import OpenAI
from supabase import create_client

# ---------------- 基本配置 ----------------
AI_SEMAPHORE = asyncio.Semaphore(3)
BATCH_SIZE = 3
SLEEP_BETWEEN_BATCHES = 25  # 秒，防止 429
LANGUAGES = ["en", "zh"]

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# ---------------- 工具函数 ----------------
def fetch_news(language="en"):
    params = {"apiKey": os.getenv("NEWS_API_KEY"), "pageSize": 10, "language": language}
    try:
        res = requests.get("https://newsapi.org/v2/top-headlines", params=params, timeout=10)
        res.raise_for_status()
        articles = res.json().get("articles", [])
        print(f"[Succ] {language} 获取 {len(articles)} 条新闻")
        return articles
    except Exception as e:
        print(f"[Fail] 获取 {language} 新闻失败:", e)
        return []

# ---------------- AI 分类 ----------------
async def classify_news(title: str, description: str = "") -> str:
    prompt = f"""
    请根据以下新闻标题和描述，为新闻选择最合适的分类标签：
    可选分类包括：科技、商业、体育、娱乐、国际、健康、政治、汽车、教育、其他。
    标题：{title}
    描述：{description}
    请只返回一个分类标签。
    """
    async with AI_SEMAPHORE:
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            category = response.choices[0].message.content.strip()
            print(f"[分类] {title[:25]} → {category}")
            return category
        except Exception as e:
            print(f"[Warn] 分类失败: {title} -> {e}")
            return "其他"

# ---------------- AI 总结 ----------------
async def summarize_news(title, description):
    prompt = f"""
    请用简洁专业的语气对以下新闻内容进行智能解读，包括：
    1. 背景概述；
    2. 当前意义；
    3. 未来发展趋势；
    输出一段约 100 字的中文总结。
    新闻标题：{title}
    新闻摘要：{description or '无'}
    """
    async with AI_SEMAPHORE:
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content.strip()
            print(f"[解读] {title[:25]} 成功")
            return text
        except Exception as e:
            print(f"[Warn] 解读失败: {title} -> {e}")
            return None

# ---------------- 限流执行 ----------------
async def run_in_batches(tasks, batch_size=BATCH_SIZE):
    results = []
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i+batch_size]
        batch_results = await asyncio.gather(*batch)
        results.extend(batch_results)
        print(f"[限流] 批次 {i//batch_size + 1} 完成，等待 {SLEEP_BETWEEN_BATCHES}s...")
        await asyncio.sleep(SLEEP_BETWEEN_BATCHES)
    return results

# ---------------- 主流程 ----------------
async def main():
    all_articles = []
    for lang in LANGUAGES:
        all_articles.extend(fetch_news(language=lang))

    # 去重
    unique_articles = list({a['url']: a for a in all_articles if a.get('url')}.values())

    # 任务并发
    categories = await run_in_batches([classify_news(a["title"], a.get("description","")) for a in unique_articles])
    summaries = await run_in_batches([summarize_news(a["title"], a.get("description","")) for a in unique_articles])

    # 写入数据库
    for article, cat, summ in zip(unique_articles, categories, summaries):
        data = {
            "title": article.get("title"),
            "description": article.get("description"),
            "url": article.get("url"),
            "image_url": article.get("urlToImage"),
            "source_name": article.get("source", {}).get("name"),
            "published_at": article.get("publishedAt"),
            "language": article.get("language"),
            "category": cat,
            "ai_summary": summ,
        }
        try:
            supabase.table("news").upsert(data, on_conflict="url").execute()
            print(f"[DB] 写入成功：{data['title'][:30]}")
        except Exception as e:
            print(f"[DB] 写入失败：{e}")

    print("\n✅ 全部新闻已写入 Supabase")

if __name__ == "__main__":
    asyncio.run(main())
