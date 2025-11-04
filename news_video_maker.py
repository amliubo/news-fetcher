import os
import asyncio
import requests
import uuid
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    CompositeVideoClip,
)
from supabase import create_client
import numpy as np
import edge_tts
import textwrap

# ---------- 全局配置 ----------
font_path = os.path.join(os.path.dirname(__file__), "NotoSansCJK-Regular.ttc")
DEFAULT_COVER = "default_cover.jpg"
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# ---------- 工具函数 ----------
def create_dynamic_subtitles(text, total_duration, font_size=42, size=(1080, 180)):
    img_clips = []
    parts = [p.strip() for p in text.replace("，", "。").split("。") if p.strip()]
    if not parts:
        parts = [text]

    total_chars = sum(len(p) for p in parts)
    start_time = 0.0

    for sentence in parts:
        ratio = len(sentence) / total_chars
        seg_dur = total_duration * ratio

        img = Image.new("RGBA", size, (0, 0, 0, 150))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(font_path, font_size)
        wrapped = "\n".join(textwrap.wrap(sentence, width=22))
        w, h = draw.textbbox((0, 0), wrapped, font=font)[2:]
        draw.multiline_text(((size[0]-w)/2, (size[1]-h)/2), wrapped, font=font, fill=(255,255,255))

        txt_clip = (
            ImageClip(np.array(img))
            .set_position(("center", "bottom"))
            .set_start(start_time)
            .set_duration(seg_dur)
        )
        img_clips.append(txt_clip)
        start_time += seg_dur

    return img_clips

async def generate_tts(text, path):
    """异步生成语音文件"""
    communicator = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
    await communicator.save(path)
    print(f"[TTS] 已生成 {path}")


# ---------- 主视频逻辑 ----------
async def generate_video(article, base_dir):
    title = article["title"]
    summary = article.get("ai_summary") or title
    category = article.get("category") or "其他"
    image_url = article.get("image_url")

    # 独立子目录，避免文件冲突
    video_id = uuid.uuid4().hex
    video_dir = os.path.join(base_dir, category, video_id)
    os.makedirs(video_dir, exist_ok=True)

    # ---------- 下载封面 ----------
    image_path = os.path.join(video_dir, "cover.jpg")
    try:
        if image_url:
            res = requests.get(image_url, timeout=10)
            res.raise_for_status()
            with open(image_path, "wb") as f:
                f.write(res.content)
        else:
            image_path = DEFAULT_COVER
    except Exception:
        image_path = DEFAULT_COVER
    print(f"[Img] {title[:20]} 封面加载完成")

    # ---------- 生成语音 ----------
    audio_path = os.path.join(video_dir, "voice.mp3")
    await generate_tts(summary, audio_path)

    # ---------- 读取音频 ----------
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    # ---------- 图像 + 字幕 ----------
    img_clip = ImageClip(image_path).set_duration(duration)
    subtitle_clips = create_dynamic_subtitles(summary, duration)

    # ---------- 合成 ----------
    final_clip = CompositeVideoClip([img_clip] + subtitle_clips).set_audio(audio)

    out_path = os.path.join(video_dir, f"{category}_{video_id}.mp4")
    final_clip.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", threads=4, logger=None)

    # 清理资源
    audio.close()
    final_clip.close()

    print(f"[Video] 生成成功：{out_path}")

# ---------- 主入口 ----------
async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    base_dir = os.path.join("videos", today)
    os.makedirs(base_dir, exist_ok=True)

    # 从数据库读取新闻
    res = supabase.table("news").select("*").order("published_at", desc=True).limit(5).execute()
    articles = res.data or []

    print(f"[Info] 将生成 {len(articles)} 条新闻视频")
    for article in articles:
        try:
            await generate_video(article, base_dir)
        except Exception as e:
            print(f"[Error] {article.get('title', '')[:20]} 生成失败：{e}")


if __name__ == "__main__":
    asyncio.run(main())
