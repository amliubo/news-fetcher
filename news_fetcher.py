import os
import edge_tts
import asyncio
import textwrap
import requests
import numpy as np
from openai import OpenAI
from supabase import create_client
from moviepy.video.VideoClip import ImageClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

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

CATEGORIES = ["ai","technology","business","sports","automobile","car_maintenance"]
LANGUAGES = ["en","zh"]

# ---------------- Bark ----------------
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
    params = {"apiKey": NEWS_API_KEY,"pageSize":50}
    if language=="zh": params["q"]=category
    else:
        params["language"]=language
        if category not in ["general","business","entertainment","health","science","sports","technology"]:
            params["q"]=category
        else: params["category"]=category
    try:
        res = requests.get("https://newsapi.org/v2/top-headlines", params=params, timeout=10)
        res.raise_for_status()
        return res.json().get("articles",[])
    except Exception as e:
        print(f"[Fail] 获取 {language}-{category} 新闻失败:", e)
        return []

# ---------------- AI解读 ----------------

def generate_short_script(title, description, max_chars=70):
    """
    将新闻标题 + 描述生成适合 30 秒视频的简短解说稿
    """
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
        # 如果失败则退化为截取标题+前 max_chars 字
        return f"{title}。{description[:max_chars]}..."

# ---------------- TTS ----------------
async def generate_tts(text, output):
    voice = "zh-CN-YunjianNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output)

# ---------------- 视频生成 ----------------
def create_text_clip(text, duration, font_path=r"C:\Windows\Fonts\msyh.ttc", font_size=36, size=(1080,200)):
    img = Image.new("RGBA", size, (0,0,0,150))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    w, h = draw.textsize(wrapped, font=font)
    draw.multiline_text(((size[0]-w)/2,(size[1]-h)/2), wrapped, font=font, fill=(255,255,255))
    return ImageClip(np.array(img)).set_duration(duration).set_position(("center","bottom"))

def generate_video(image_path, audio_path, text, output_path):
    audio = AudioFileClip(audio_path)
    image_clip = ImageClip(image_path).set_duration(audio.duration)
    txt_clip = create_text_clip(text, duration=audio.duration)
    video = CompositeVideoClip([image_clip, txt_clip]).set_audio(audio)
    video.write_videofile(output_path, fps=24)
    print(f"[Succ] 视频生成完成: {output_path}")

# ---------------- 主流程 ----------------
def main():
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

    # 去重 & 写入数据库
    unique_articles = list({a['url']:a for a in all_articles if a.get('url')}.values())
    supabase.table("news").upsert(unique_articles, on_conflict=["url"]).execute()

    # 循环生成视频
    for idx, article in enumerate(unique_articles[:5]):
        title = article.get("title") or "无标题"
        desc = article.get("description") or ""

        # 🔹 生成简短解说稿（30 秒左右）
        short_text = generate_short_script(title, desc, max_chars=70)

        category = article.get("category")
        cat_dir = os.path.join(base_dir, category)
        os.makedirs(cat_dir, exist_ok=True)

        # 下载封面
        image_url = article.get("image_url") or "https://fuss10.elemecdn.com/a/3f/3302e58f9a181d2509f3dc0fa68b0jpeg.jpeg"
        image_path = os.path.join(cat_dir, f"cover_{idx}.jpg")
        try:
            r = requests.get(image_url, timeout=10)
            with open(image_path, "wb") as f: f.write(r.content)
        except:
            image_path = None

        # 生成语音
        audio_path = os.path.join(cat_dir, f"voice_{idx}.mp3")
        asyncio.run(generate_tts(short_text, audio_path))

        # 生成视频
        output_path = os.path.join(cat_dir, f"news_video_{idx}.mp4")
        generate_video(image_path, audio_path, short_text, output_path)

    push_bark("新闻视频生成", f"已生成 {len(unique_articles[:5])} 条视频")

if __name__=="__main__":
    main()
