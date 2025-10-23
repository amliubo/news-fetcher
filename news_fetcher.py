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
        params = {"title": title, "body": body, "isArchive": 1}
        resp = requests.get(BARK_URL, params=params)
        if resp.status_code == 200:
            print(f"✅ Bark 推送成功：{title}")
        else:
            print(f"❌ Bark 推送失败：{resp.text}")
    except Exception as e:
        print("Bark Error:", e)

# ------------------- 新闻抓取 -------------------
def fetch_news(category=None, language="en"):
    params = {"apiKey": NEWS_API_KEY, "pageSize": 50, "language": language}
    # NewsAPI 的 category 参数仅支持部分英文分类，针对自定义标签可以用 q 搜索
    if category not in ["general", "business", "entertainment", "health", "science", "sports", "technology"]:
        params["q"] = category  # 用关键字搜索
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
            supabase.table("news").upsert(all_articles, on_conflict=["url"]).execute()
            # 发送热点新闻折叠消息
            HOT_COUNT = 12
            hot_articles = all_articles[:HOT_COUNT]
            body_lines = []
            for a in hot_articles:
                title = a.get("title", "无标题")
                desc = a.get("description", "")
                snippet = desc[:50] + ("..." if len(desc) > 50 else "")
                body_lines.append(f"- {title}: {snippet}")
            body = "\n".join(body_lines)
            push_bark(f"新闻抓取完成 共{len(all_articles)}条", body)
        except Exception as e:
            print("Supabase 写入失败:", e)
            push_bark("新闻抓取失败", str(e))
    else:
        push_bark("新闻抓取", "未获取到新闻数据")

if __name__ == "__main__":
    main()