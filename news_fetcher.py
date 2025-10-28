import os
import re
import asyncio
import textwrap
import requests
import numpy as np
from gtts import gTTS
from openai import OpenAI
from supabase import create_client
from moviepy.video.VideoClip import ImageClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

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

def push_bark(title, body):
    try:
        data = {"title": title,"body": body,"isArchive":1}
        resp = requests.post(BARK_URL, json=data, timeout=10)
        if resp.status_code==200: print(f"[Succ] Bark 推送成功：{title}")
        else: print(f"[Fail] Bark 推送失败：{resp.text}")
    except Exception as e:
        print("Bark Error:", e)

# ---------------- 新闻抓取 ----------------
def fetch_news(category=None, language="en"):
    params = {
        "apiKey": NEWS_API_KEY,
        "pageSize": 30,
    }
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

# ---------------- AI解读 ----------------
def generate_short_script(title, description, max_chars=70):
    prompt = f"""
    请将以下新闻内容改写为适合 30 秒视频的中文解说稿，尽量简短精炼，字数控制在 {max_chars} 字左右：
    标题: {title}
    内容: {description}
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}]
        )
        short_text = resp.choices[0].message.content.strip()
        return short_text
    except Exception as e:
        print("[Fail] 自动生成简短文案失败:", e)
        return f"{title}。{description[:max_chars]}..."

# ---------------- 本地 TTS（gTTS） ----------------
executor = ThreadPoolExecutor(max_workers=2)

def tts_sync_gtts(text, output_path, lang="zh"):
    tts = gTTS(text=text, lang=lang, slow=False)
    tts.save(output_path)

async def generate_tts(text, output_path, lang="zh"):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, tts_sync_gtts, text, output_path, lang)

# ---------------- 视频生成 ----------------
def create_text_clip(text, duration, font_path=r"/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", font_size=36, size=(1080,200)):
    img = Image.new("RGBA", size, (0,0,0,150))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    bbox = draw.textbbox((0, 0), wrapped, font=font)
    w, h = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.multiline_text(((size[0]-w)/2,(size[1]-h)/2), wrapped, font=font, fill=(255,255,255))
    return ImageClip(np.array(img)).set_duration(duration).set_position(("center","bottom"))

def create_subtitle_clips(sentences, audio_duration, font_path, font_size, size=(1080,200)):
    n = len(sentences)
    duration_per_sentence = audio_duration / n
    clips = []
    for idx, s in enumerate(sentences):
        clip = create_text_clip(s, duration=duration_per_sentence, font_path=font_path, font_size=font_size, size=size)
        clip = clip.set_start(idx*duration_per_sentence)
        clips.append(clip)
    return clips

def generate_video(image_path, audio_path, text, output_path,
                   font_path="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   font_size=28):

    audio = AudioFileClip(audio_path)
    image_clip = ImageClip(image_path).set_duration(audio.duration)
    
    sentences = re.split(r'(。|！|\!|\.|？|\?)', text)
    full_sentences = []
    i = 0
    while i < len(sentences)-1:
        full_sentences.append(sentences[i] + sentences[i+1])
        i += 2
    if i == len(sentences)-1:
        full_sentences.append(sentences[-1])
    
    subtitle_clips = create_subtitle_clips(full_sentences, audio.duration, font_path, font_size)
    
    video = CompositeVideoClip([image_clip, *subtitle_clips]).set_audio(audio)
    video.write_videofile(output_path, fps=24)
    print(f"[Succ] 视频生成完成: {output_path}")

# ---------------- 图片下载 ----------------

def download_image(url, save_path, default_path="default_cover.jpg"):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        if "image" not in r.headers.get("Content-Type", ""):
            raise ValueError("URL 不是图片")
        with open(save_path, "wb") as f:
            f.write(r.content)
        return save_path
    except Exception as e:
        print(f"[Warn] 图片下载失败 {url}, 使用默认封面: {e}")
        return default_path

# ---------------- 异步主流程 ----------------
async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    base_dir = os.path.join("videos", today)
    os.makedirs(base_dir, exist_ok=True)

    all_articles=[]
    for lang in LANGUAGES:
        for cat in CATEGORIES:
            articles = fetch_news(cat, lang)
            for a in articles:
                a["category"]=cat
                a["language"]=lang
            all_articles.extend(articles)
            print(f"[Succ] {lang}-{cat} 获取 {len(articles)} 条新闻")

    if not all_articles:
        push_bark("新闻抓取","未获取到新闻数据")
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

    tasks = []
    for idx, article in enumerate(unique_articles[:5]):
        title = article.get("title") or "无标题"
        desc = article.get("description") or ""
        short_text = generate_short_script(title, desc, max_chars=70)

        category = article.get("category")
        cat_dir = os.path.join(base_dir, category)
        os.makedirs(cat_dir, exist_ok=True)

        image_url = (
            article.get("image_url")
        )
        audio_path = os.path.join(cat_dir, f"voice_{idx}.mp3")

        DEFAULT_COVER = "default_cover.jpg"
        image_path = download_image(image_url, os.path.join(cat_dir, f"cover_{idx}.jpg"), default_path=DEFAULT_COVER)

        async def tts_and_video(image_path=image_path, audio_path=audio_path, short_text=short_text,
                                output_path=os.path.join(cat_dir, f"news_video_{idx}.mp4")):
            await generate_tts(short_text, audio_path, lang="zh")
            if not image_path or not os.path.exists(image_path):
                image_path = DEFAULT_COVER
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(executor, generate_video, image_path, audio_path, short_text, output_path)


        tasks.append(tts_and_video())

    await asyncio.gather(*tasks)
    push_bark("新闻视频生成", f"已生成 {len(unique_articles[:5])} 条视频")

if __name__=="__main__":
    asyncio.run(main())
