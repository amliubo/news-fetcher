import os
import requests
from supabase import create_client, Client

# ------------------- Supabase 配置 -------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------- 新闻 API 配置 -------------------
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
BARK_KEY = os.getenv("BARK_KEY")
BARK_URL = f"https://api.day.app/{BARK_KEY}"

# ------------------- 标签与语言配置 -------------------
CATEGORIES = [
    "ai", 
    "technology", 
    "business", 
    "sports", 
    "automobile", 
    "car_maintenance"
]
LANGUAGES = ["en", "zh"]  # 英文和中文

# ------------------- Bark 推送 -------------------
def push_bark(title, body):
    try:
        data = {
            "title": title,
            "body": body,
            "isArchive": 1,
        }
        resp = requests.post(BARK_URL, json=data, timeout=10)
        if resp.status_code == 200:
            print(f"✅ Bark 推送成功：{title}")
        else:
            print(f"❌ Bark 推送失败：{resp.text}")
    except Exception as e:
        print("Bark Error:", e)


# ------------------- 新闻抓取 -------------------
def fetch_news(category=None, language="en"):
    params = {"apiKey": NEWS_API_KEY, "pageSize": 50, "language": language}
    if category not in ["general", "business", "entertainment", "health", "science", "sports", "technology"]:
        params["q"] = category
    else:
        params["category"] = category
    try:
        res = requests.get("https://newsapi.org/v2/top-headlines", params=params, timeout=10)
        res.raise_for_status()
        return res.json().get("articles", [])
    except Exception as e:
        print(f"❌ 获取 {language}-{category} 新闻失败:", e)
        return []

# ------------------- 主程序 -------------------
def main():
    all_articles = []
    for lang in LANGUAGES:
        for cat in CATEGORIES:
            articles = fetch_news(category=cat, language=lang)
            for a in articles:
                record = {
                    "title": a.get("title"),
                    "description": a.get("description"),
                    "url": a.get("url"),
                    "source": a.get("source", {}).get("name"),
                    "author": a.get("author"),
                    "published_at": a.get("publishedAt"),
                    "image_url": a.get("urlToImage"),
                    "category": cat,
                    "language": lang
                }
                all_articles.append(record)
            print(f"✅ {lang}-{cat} 获取 {len(articles)} 条新闻")

    if all_articles:
        try:
            # 去重同一 URL
            unique_articles = list({a['url']: a for a in all_articles if a.get('url')}.values())
            supabase.table("news").upsert(unique_articles, on_conflict=["url"]).execute()

            # 获取数据库总量
            db_count_res = supabase.table("news").select("id").execute()
            total_count = len(db_count_res.data) if db_count_res.data else 0

            # 发送热点新闻图文消息
            HOT_COUNT = 12
            hot_articles = unique_articles[:HOT_COUNT]
            header = f"抓取完成：本次获取 {len(all_articles)} 条 | 数据库总量 {total_count} 条\n"
            body_lines = []
            for a in hot_articles:
                img = a.get("image_url") or ""
                title = a.get("title", "无标题")
                source = a.get("source", "未知来源")
                published = a.get("published_at", "")[:10]
                desc = (a.get("description") or "")[:100] + ("..." if len(a.get("description") or "") > 100 else "")
                body_lines.append(f"![thumb]({img})\n**{title}**\n来源: {source} · {published}\n{desc}\n")
            body = header + "\n".join(body_lines)
            push_bark(f"新闻抓取完成 共{len(unique_articles)}条", body)
        except Exception as e:
            print("Supabase 写入失败:", e)
            push_bark("新闻抓取失败", str(e))
    else:
        push_bark("新闻抓取", "未获取到新闻数据")

if __name__ == "__main__":
    main()
