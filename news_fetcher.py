from supabase import create_client, Client
import requests
import os

# ------------------- Supabase 配置 -------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------- 新闻 API 配置 -------------------
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_URL = f"https://newsapi.org/v2/top-headlines?language=en&pageSize=50&apiKey={NEWS_API_KEY}"

# ------------------- Bark 配置 -------------------
BARK_KEY = os.getenv("BARK_KEY")
BARK_URL = f"https://api.day.app/{BARK_KEY}"

def push_bark(title, body):
    """发送 Bark 通知"""
    try:
        params = {"title": title, "body": body, "isArchive": 1}
        resp = requests.get(BARK_URL, params=params)
        if resp.status_code == 200:
            print(f"✅ Bark 推送成功：{title}")
        else:
            print(f"❌ Bark 推送失败：{resp.text}")
    except Exception as e:
        print("Bark Error:", e)

def main():
    res = requests.get(NEWS_URL)
    data = res.json()
    articles = data.get("articles", [])

    if not articles:
        print("⚠️ 未获取到新闻")
        push_bark("新闻抓取", "未获取到新闻数据")
        return

    count_inserted = 0
    for article in articles:
        record = {
            "title": article.get("title"),
            "description": article.get("description"),
            "url": article.get("url"),
            "source": article["source"]["name"] if article.get("source") else None,
            "author": article.get("author"),
            "published_at": article.get("publishedAt"),
            "image_url": article.get("urlToImage"),
        }
        try:
            supabase.table("news").upsert(record, on_conflict=["url"]).execute()
            count_inserted += 1
        except Exception as e:
            print("Supabase 写入失败:", e)

    db_count_res = supabase.table("news").select("id").execute()
    total_count = len(db_count_res.data) if db_count_res.data else 0

    msg = f"抓取: {count_inserted} 条新闻 | 数据库总量: {total_count}"
    print("✅ " + msg)
    push_bark("新闻抓取完成", msg)


if __name__ == "__main__":
    main()