import os
import asyncio
import textwrap
import requests
import numpy as np
from io import BytesIO
from openai import OpenAI
from supabase import create_client
from moviepy.video.VideoClip import ImageClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.editor import concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# ---------------- 基本配置 ----------------
font_path = os.path.join(os.path.dirname(__file__), "NotoSansCJK-Regular.ttc")
AI_SEMAPHORE = asyncio.Semaphore(3)
DEFAULT_COVER = "default_cover.jpg"
LANGUAGES = ["en", "zh"]

# ---------------- OpenAI ----------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------- Supabase ----------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- Bark ----------------
BARK_KEY = os.getenv("BARK_KEY")
BARK_URL = f"https://api.day.app/{BARK_KEY}"

# ---------------- 工具函数 ----------------
def push_bark(title, body):
    try:
        data = {"title": title,"body": body,"isArchive":1}
        resp = requests.post(BARK_URL, json=data, timeout=10)
        if resp.status_code==200: print(f"[Succ] Bark 推送成功：{title}")
        else: print(f"[Fail] Bark 推送失败：{resp.text}")
    except Exception as e:
        print("Bark Error:", e)

def fetch_news(category=None, language="en"):
    params = {"apiKey": os.getenv("NEWS_API_KEY"), "pageSize":30, "language": language}
    if category:
        params["q"] = category
    try:
        res = requests.get("https://newsapi.org/v2/top-headlines", params=params, timeout=10)
        res.raise_for_status()
        articles = res.json().get("articles", [])
        print(f"[Succ] {language} 获取 {len(articles)} 条新闻")
        return articles
    except Exception as e:
        print(f"[Fail] 获取 {language} 新闻失败:", e)
        return []

def create_text_clip(text, duration, font_path=font_path, font_size=36, size=(1080,80)):
    img = Image.new("RGBA", size, (0,0,0,150))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    bbox = draw.textbbox((0, 0), wrapped, font=font)
    w, h = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.multiline_text(((size[0]-w)/2,(size[1]-h)/2), wrapped, font=font, fill=(255,255,255))
    return ImageClip(np.array(img)).set_duration(duration).set_position(("center","bottom"))

# ---------------- AI 功能 ----------------
async def generate_ai_summary_async(title, description):
    prompt = f"""
    请用简洁专业的语气对以下新闻内容进行智能解读，包括：
    1. 背景概述；
    2. 当前意义；
    3. 可能的未来发展趋势；
    输出一段 80~120 字的中文总结。

    新闻标题：{title}
    新闻摘要：{description or '无'}
    """
    async with AI_SEMAPHORE:
        await asyncio.sleep(1)  # 限流
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":prompt}],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Warn] AI 解读失败: {title} -> {e}")
            return None

async def classify_news_category_async(title: str, description: str = "") -> str:
    prompt = f"""
    请根据以下新闻标题和描述，为新闻选择最合适的分类标签：
    可选分类包括：科技、商业、体育、娱乐、国际、健康、政治、汽车、教育、其他。
    标题：{title}
    描述：{description}
    请只返回一个分类标签。
    """
    async with AI_SEMAPHORE:
        await asyncio.sleep(1)
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            category = response.choices[0].message.content.strip()
            print(f"[AI分类] {title[:30]}... → {category}")
            return category
        except Exception as e:
            print(f"[Warn] 分类失败: {title} -> {e}")
            return "其他"

# ---------------- AI TTS ----------------
async def generate_tts(text, output_path, voice="alloy"):
    try:
        import edge_tts
        tts_voice = "zh-CN-XiaoxiaoNeural"
        tts = edge_tts.Communicate(text, tts_voice)
        await tts.save(output_path)
        print(f"[Succ] Edge TTS 已生成: {output_path}")
    except Exception as e:
        print(f"[Fail] Edge TTS 失败: {e}")

# ---------------- 视频生成 ----------------
async def tts_and_video(idx, article, base_dir):
    title = article.get("title") or "无标题"
    desc = article.get("description") or ""
    ai_text = article.get("ai_summary")
    category = article.get("category") or "other"

    cat_dir = os.path.join(base_dir, category)
    os.makedirs(cat_dir, exist_ok=True)

    if ai_text:
        video_script = [{"text": ai_text, "image_url": article.get("image_url"), "duration": 30}]
    else:
        video_script = [{"text": f"{title}。{desc[:70]}...", "image_url": article.get("image_url"), "duration": 30}]

    clips = []
    for seg_idx, seg in enumerate(video_script):
        text = seg.get("text", "")
        duration = seg.get("duration", 5)
        image_url = seg.get("image_url") or DEFAULT_COVER

        # 图片处理
        image_path = DEFAULT_COVER
        if image_url and image_url != DEFAULT_COVER:
            try:
                response = requests.get(image_url, timeout=10)
                response.raise_for_status()
                if "image" not in response.headers.get("Content-Type", ""):
                    raise ValueError("URL 不是图片")
                img = Image.open(BytesIO(response.content))
                image_path = os.path.join(cat_dir, f"temp_cover_{idx}_{seg_idx}_{int(datetime.now().timestamp())}.jpg")
                img.save(image_path)
                print(f"[Succ] 图片加载成功: {image_url}")
            except Exception as e:
                print(f"[Warn] 图片加载失败 {image_url}, 使用默认封面: {e}")

        # TTS
        audio_path = os.path.join(cat_dir, f"voice_{idx}_{seg_idx}.mp3")
        await generate_tts(text, audio_path, voice="alloy")

        # 视频片段
        audio = AudioFileClip(audio_path)
        img_clip = ImageClip(image_path).set_duration(audio.duration)
        img_clip = img_clip.resize(lambda t: 1 + 0.05*t/audio.duration)
        subtitle = create_text_clip(text, audio.duration)
        clip = CompositeVideoClip([img_clip, subtitle]).set_audio(audio)
        clips.append(clip)

    # 合并视频片段
    output_path = os.path.join(cat_dir, f"news_video_{idx}.mp4")
    final_video = concatenate_videoclips(clips)
    final_video.write_videofile(output_path, fps=24)
    print(f"[Succ] 视频生成完成: {output_path}")

# ---------------- 主流程 ----------------
async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    base_dir = os.path.join("videos", today)
    os.makedirs(base_dir, exist_ok=True)

    # --- 新闻抓取 ---
    all_articles = []
    for lang in LANGUAGES:
        articles = fetch_news(language=lang)
        for a in articles:
            a["language"] = lang
        all_articles.extend(articles)

    if not all_articles:
        push_bark("新闻抓取", "未获取到新闻数据")
        return

    # 去重
    unique_articles = list({a['url']:a for a in all_articles if a.get('url')}.values())

    # --- 异步分类 & AI 解读 ---
    category_tasks = [classify_news_category_async(a.get("title",""), a.get("description","")) for a in unique_articles]
    categories = await asyncio.gather(*category_tasks)

    summary_tasks = [generate_ai_summary_async(a.get("title",""), a.get("description","")) for a in unique_articles]
    summaries = await asyncio.gather(*summary_tasks)

    table_fields = ["title","description","url","source_name","author","image_url","published_at","source","category","language","ai_summary"]
    cleaned_articles = []
    for article, cat, summ in zip(unique_articles, categories, summaries):
        record = {
            "title": article.get("title"),
            "description": article.get("description"),
            "url": article.get("url"),
            "source_name": (article.get("source") or {}).get("name") or article.get("source_name"),
            "author": article.get("author"),
            "image_url": article.get("image_url") or article.get("urlToImage"),
            "published_at": article.get("publishedAt") or article.get("published_at"),
            "source": article.get("source") or "",
            "category": cat,
            "language": article.get("language"),
            "ai_summary": summ
        }
        record = {k:v for k,v in record.items() if k in table_fields}
        cleaned_articles.append(record)

    # 写入 Supabase
    try:
        supabase.table("news_articles").upsert(cleaned_articles, on_conflict=["url"]).execute()
        print(f"[Succ] 已写入 {len(cleaned_articles)} 条新闻到数据库")
    except Exception as e:
        print("[Fail] 写入数据库失败:", e)

    # --- 并发生成视频（示例前5条） ---
    tasks = [tts_and_video(idx, article, base_dir) for idx, article in enumerate(cleaned_articles[:5])]
    await asyncio.gather(*tasks)
    push_bark("新闻视频生成", f"已生成 {len(tasks)} 条视频")

if __name__=="__main__":
    asyncio.run(main())
