import os
import asyncio
import requests
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
from supabase import create_client
import numpy as np
import edge_tts
import textwrap

font_path = os.path.join(os.path.dirname(__file__), "NotoSansCJK-Regular.ttc")
DEFAULT_COVER = "default_cover.jpg"
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# ---------- 工具函数 ----------
def create_text_clip(text, duration, font_size=40, size=(1080, 120)):
    img = Image.new("RGBA", size, (0,0,0,150))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    wrapped = "\n".join(textwrap.wrap(text, width=22))
    w, h = draw.textbbox((0, 0), wrapped, font=font)[2:]
    draw.multiline_text(((size[0]-w)/2,(size[1]-h)/2), wrapped, font=font, fill=(255,255,255))
    return ImageClip(np.array(img)).set_duration(duration).set_position(("center","bottom"))

async def generate_tts(text, path):
    tts = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
    await tts.save(path)
    print(f"[TTS] 已生成 {path}")

# ---------- 主视频逻辑 ----------
async def generate_video(article, base_dir):
    title = article["title"]
    summary = article["ai_summary"]
    category = article["category"] or "其他"
    image_url = article.get("image_url")

    cat_dir = os.path.join(base_dir, category)
    os.makedirs(cat_dir, exist_ok=True)

    # 下载封面
    image_path = DEFAULT_COVER
    if image_url:
        try:
            res = requests.get(image_url, timeout=10)
            res.raise_for_status()
            img = Image.open(BytesIO(res.content))
            image_path = os.path.join(cat_dir, "cover.jpg")
            img.save(image_path)
            print(f"[Img] {title[:20]} 封面加载成功")
        except Exception:
            print(f"[Img] 封面加载失败，使用默认封面")

    # 生成语音
    audio_path = os.path.join(cat_dir, "voice.mp3")
    await generate_tts(summary or title, audio_path)

    # 合成视频
    audio = AudioFileClip(audio_path)
    img_clip = ImageClip(image_path).set_duration(audio.duration)
    subtitle = create_text_clip(summary or title, audio.duration)
    final_clip = CompositeVideoClip([img_clip, subtitle]).set_audio(audio)

    out_path = os.path.join(cat_dir, f"video_{int(datetime.now().timestamp())}.mp4")
    final_clip.write_videofile(out_path, fps=24)
    print(f"[Video] 生成成功：{out_path}")

async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    base_dir = os.path.join("videos", today)
    os.makedirs(base_dir, exist_ok=True)

    # 从数据库读取新闻（例如当天的）
    res = supabase.table("news").select("*").order("published_at", desc=True).limit(5).execute()
    articles = res.data or []

    print(f"[Info] 将生成 {len(articles)} 条新闻视频")
    for article in articles:
        await generate_video(article, base_dir)

if __name__ == "__main__":
    asyncio.run(main())
