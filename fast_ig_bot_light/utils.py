# fast_ig_bot_light/fast_ig_bot_light/utils.py
import re
import os
import asyncio
import subprocess, json, tempfile
from time import monotonic
from typing import Optional, Tuple, Callable, Dict, Any
from yt_dlp import YoutubeDL

IG_URL_RE = re.compile(r"(https?://(www\.)?instagram\.com/[^\s]+)")

# (Agar eski RAM-lock throttle bor bo'lsa, undan endi foydalanmasak ham bo'ladi)
_NEXT_ALLOWED_AT = 0.0
_LOCK = asyncio.Lock()

async def throttle_global(gap_seconds: float = 5.0):
    # DB-based throttlega o'tganmiz; bu fallback sifatida qolsin
    global _NEXT_ALLOWED_AT
    async with _LOCK:
        now = monotonic()
        if now < _NEXT_ALLOWED_AT:
            await asyncio.sleep(_NEXT_ALLOWED_AT - now)
        _NEXT_ALLOWED_AT = monotonic() + gap_seconds


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8", "ignore")


def probe_video(path: str) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    """
    width, height, duration(s), rotate(0/90/180/270 or None)
    """
    try:
        out = _run([
            "ffprobe","-v","error",
            "-select_streams","v:0",
            "-show_entries","stream=width,height:stream_tags=rotate",
            "-show_entries","format=duration",
            "-of","json", path
        ])
        data = json.loads(out)
        w = h = dur = rot = None
        if data.get("streams"):
            s = data["streams"][0]
            w = int(s.get("width") or 0) or None
            h = int(s.get("height") or 0) or None
            rot_tag = None
            tags = s.get("tags") or {}
            if "rotate" in tags:
                try:
                    rot_tag = int(str(tags["rotate"]).strip())
                except:
                    rot_tag = None
            # normalize rotation
            if rot_tag in (0, 90, 180, 270):
                rot = rot_tag
        if data.get("format") and data["format"].get("duration") is not None:
            try:
                dur = int(float(data["format"]["duration"]))
            except:
                dur = None
        return w, h, dur, rot
    except Exception:
        return None, None, None, None


def ensure_faststart(in_path: str) -> str:
    """
    moov atomni boshiga ko'chirish (streaming uchun).
    Re-encode qilmaydi, tez (copy).
    """
    out_path = in_path
    # vaqtinchalik faylga yozamiz, keyin almashtiramiz
    tmp_path = in_path + ".faststart.mp4"
    try:
        _run([
            "ffmpeg","-y","-i", in_path,
            "-c","copy","-movflags","+faststart",
            tmp_path
        ])
        # agar muvaffaqiyatli bo'lsa, outputdan foydalanamiz
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            out_path = tmp_path
    except Exception:
        pass
    return out_path


def make_thumbnail(in_path: str) -> Optional[str]:
    """
    1-2 soniya atrofidagi kadrdan preview jpg chiqarish
    """
    thumb = in_path + ".jpg"
    try:
        _run([
            "ffmpeg","-y","-ss","00:00:01.0","-i", in_path,
            "-frames:v","1","-q:v","2", thumb
        ])
        return thumb if os.path.exists(thumb) else None
    except Exception:
        return None


def is_ig_url(text: str) -> Optional[str]:
    m = IG_URL_RE.search(text or "")
    return m.group(1) if m else None


async def ytdlp_download(url: str, workdir: str, on_progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> Tuple[str, int]:
    os.makedirs(workdir, exist_ok=True)
    opts = {
        "paths": {"home": workdir, "temp": workdir},
        "outtmpl": {"default": "%(id)s.%(ext)s"},
        "quiet": True,
        "noprogress": True,
        # IG uchun yaxshi fallback zanjiri (mp4 + audio, keyin best)
        "format": "bv*[height>=1080][ext=mp4]+ba[ext=m4a]/bv*[ext=mp4]+ba/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "retries": 2,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; OnePlus 6T) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
        },
    }
    if on_progress:
        def hook(d):
            try:
                on_progress(d)
            except Exception:
                pass
        opts["progress_hooks"] = [hook]
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
    size = os.path.getsize(file_path)
    return file_path, size
