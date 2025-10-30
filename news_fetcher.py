import os
import re
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

font_path = os.path.join(os.path.dirname(__file__), "NotoSansCJK-Regular.ttc")

# ---------------- OpenAI ----------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------- Supabase ----------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- 新闻 & Bark ----------------
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
BARK_KEY = os.getenv("BARK_KEY")
BARK_URL = f"https://api.day.app/{BARK_KEY}"

CATEGORIES = ["ai", "technology", "business", "sports", "automobile", "car_maintenance"]
LANGUAGES = ["en", "zh"]

DEFAULT_COVER = "default_cover.jpg"

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
    params = {"apiKey": NEWS_API_KEY, "pageSize":30}
    if language == "zh":
        params["language"] = "zh"
        params["q"] = category
    else:
        params["language"] = "en"
        params["q"] = category

    try:
        res = requests.get("https://newsapi.org/v2/top-headlines", params=params, timeout=10)
        res.raise_for_status()
        articles = res.json().get("articles", [])
        print(f"[Succ] {language}-{category} 获取 {len(articles)} 条新闻")
        return articles
    except Exception as e:
        print(f"[Fail] 获取 {language}-{category} 新闻失败:", e)
        return []

def download_image(url, save_path, default_path=DEFAULT_COVER):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        if "image" not in r.headers.get("Content-Type", ""):
            raise ValueError("URL 不是图片")
        with open(save_path, "wb") as f:
            f.write(r.content)
        print(f"[Succ] 图片下载成功: {url} -> {save_path}")
        return save_path
    except Exception as e:
        print(f"[Warn] 图片下载失败 {url}, 使用默认封面: {e}")
        return default_path

def create_text_clip(text, duration, font_path=font_path, font_size=36, size=(1080,200)):
    img = Image.new("RGBA", size, (0,0,0,150))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    bbox = draw.textbbox((0, 0), wrapped, font=font)
    w, h = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.multiline_text(((size[0]-w)/2,(size[1]-h)/2), wrapped, font=font, fill=(255,255,255))
    return ImageClip(np.array(img)).set_duration(duration).set_position(("center","bottom"))

# ---------------- AI 功能 ----------------
def generate_video_script(title, description, max_chars=70):
    prompt = f"""
    请为下面新闻生成适合 30 秒的视频脚本，分成多段，每段包含文字和建议图片：
    标题：{title}
    内容：{description}
    字数控制在 {max_chars} 字左右
    输出格式示例：
    [
        {{"text": "...", "image_url": "...", "duration": 5}},
        {{"text": "...", "image_url": "...", "duration": 8}}
    ]
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}]
        )
        script_text = resp.choices[0].message.content.strip()
        import json
        script = json.loads(script_text.replace("\n",""))
        return script
    except Exception as e:
        print("[Warn] 视频脚本生成失败，使用单段文字:", e)
        return [{"text": f"{title}。{description[:max_chars]}...", "image_url": None, "duration": 30}]

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
    category = article.get("category") or "other"
    cat_dir = os.path.join(base_dir, category)
    os.makedirs(cat_dir, exist_ok=True)

    video_script = generate_video_script(title, desc, max_chars=70)
    clips = []

    for seg_idx, seg in enumerate(video_script):
        text = seg.get("text","")
        duration = seg.get("duration",5)
        image_url = seg.get("image_url") or article.get("image_url")

        if image_url:
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
                image_path = DEFAULT_COVER
        else:
            image_path = DEFAULT_COVER

        # TTS
        audio_path = os.path.join(cat_dir, f"voice_{idx}_{seg_idx}.mp3")
        await generate_tts(text, audio_path, voice="alloy")

        # 生成视频片段
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
    all_articles=[]
    for lang in LANGUAGES:
        for cat in CATEGORIES:
            articles = fetch_news(cat, lang)
            for a in articles:
                a["category"] = cat
                a["language"] = lang
            all_articles.extend(articles)

    if not all_articles:
        push_bark("新闻抓取", "未获取到新闻数据")
        return

    # 去重
    unique_articles = list({a['url']:a for a in all_articles if a.get('url')}.values())

    # 写入 Supabase
    table_fields = ["title","description","url","source_name","author","image_url","published_at","source","category","language"]
    cleaned_articles = []
    for a in unique_articles:
        record = {
            "title": a.get("title"),
            "description": a.get("description"),
            "url": a.get("url"),
            "source_name": (a.get("source") or {}).get("name") or a.get("source_name"),
            "author": a.get("author"),
            "image_url": a.get("image_url") or a.get("urlToImage"),
            "published_at": a.get("publishedAt") or a.get("published_at"),
            "source": a.get("source") or "",
            "category": a.get("category"),
            "language": a.get("language")
        }
        record = {k:v for k,v in record.items() if k in table_fields}
        cleaned_articles.append(record)
    try:
        supabase.table("news").upsert(cleaned_articles, on_conflict=["url"]).execute()
        print(f"[Succ] 已写入 {len(cleaned_articles)} 条新闻到数据库")
    except Exception as e:
        print("[Fail] 写入数据库失败:", e)

    # 并发生成视频（前5条）
    tasks = [tts_and_video(idx, article, base_dir) for idx, article in enumerate(unique_articles[:5])]
    await asyncio.gather(*tasks)
    push_bark("新闻视频生成", f"已生成 {len(tasks)} 条视频")

if __name__=="__main__":
    asyncio.run(main())
