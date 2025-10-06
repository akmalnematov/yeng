import asyncio
import contextlib
import math

from aiogram import Dispatcher, Router, F
from aiogram.client.bot import Bot
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from aiogram.enums import ChatType, ChatAction

from .config import settings
from .utils import is_ig_url, ytdlp_download, ensure_faststart, probe_video  # (thumbnail ixtiyoriy)
from . import db as dbm

dp = Dispatcher()
router = Router()
dp.include_router(router)

# Global bosh bog'lanish stats/oddiy o'qishlar uchun
conn = dbm.get_conn(settings.DB_PATH)
dbm.init_db(conn)

WORKER_CONCURRENCY = 5  # <<< 5 ta parallel yuklash


def fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    val = float(n)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024.0
        i += 1
    return f"{val:.2f} {units[i]}"


@router.message(Command("start"))
async def cmd_start(m: Message, bot: Bot):
    dbm.add_user(conn, m.from_user.id, m.from_user.username, m.from_user.first_name, m.from_user.last_name)
    text = (
        "Salom! Men Instagram videolarini yuklab beruvchi botman.\n\n"
        "🔗 IG link yuboring (Reels/Post).\n"
        f"🚀 Bir vaqtning o'zida {WORKER_CONCURRENCY} ta yuklash parallel ketadi, qolganlari navbatda turadi.\n"
        "📊 /stats — shaxsiy yoki guruh statistikasi."
    )
    await m.answer(text, parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(
        f"IG link yuboring — {WORKER_CONCURRENCY} ta parallel yuklanadi, qolganlari navbatda.\n"
        "Katta fayllar (2GB+) yuborilmaydi."
    )


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if m.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        c, s = dbm.chat_stats(conn, m.chat.id)
        active = dbm.group_active_users(conn, m.chat.id)
        lines = [
            f"📊 *Guruh statistikasi* — {c} ta, {fmt_bytes(s)}",
            f"👥 Aktiv foydalanuvchilar: {active}",
            f"⏳ Navbat: {dbm.queued_count(conn)} | 🔄 Running: {dbm.running_count(conn)}"
        ]
        await m.answer("\n".join(lines), parse_mode="Markdown")
    else:
        c, s = dbm.user_stats(conn, m.from_user.id)
        total = dbm.total_users(conn)
        await m.answer(
            f"📊 *Sizning statistika*: {c} ta, {fmt_bytes(s)}\n"
            f"👥 *Jami bot foydalanuvchilari*: {total}\n"
            f"⏳ Navbat: {dbm.queued_count(conn)} | 🔄 Running: {dbm.running_count(conn)}",
            parse_mode="Markdown"
        )


async def _action_pumper(bot: Bot, chat_id: int, stop_event: asyncio.Event):
    """
    Video yuborilayotganda indikator ko'rinib turishi uchun UPLOAD_VIDEO chat action yuborib turamiz.
    """
    try:
        while not stop_event.is_set():
            await bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=4)
            except asyncio.TimeoutError:
                pass
    except Exception:
        pass


async def _worker_loop(worker_id: int, bot: Bot, db_path: str):
    """
    Worker: navbatdan ish oladi va bajaradi. 5 ta worker parallel ishlaydi.
    """
    local = dbm.get_conn(db_path)
    while True:
        job = dbm.claim_next_job(local)
        if not job:
            await asyncio.sleep(0.5)
            continue

        job_id, user_id, chat_id, reply_to, url = job
        ok = False
        sent_bytes = 0
        try:
            # Yuklab olish
            src_path, size = await ytdlp_download(url, "downloads")
            if size >= settings.TELEGRAM_LIMIT:
                await bot.send_message(chat_id, f"⚠️ Fayl juda katta: {fmt_bytes(size)} (limit {fmt_bytes(settings.TELEGRAM_LIMIT)}).",
                                       reply_to_message_id=reply_to)
                dbm.finish_job(local, job_id, ok=False, bytes_sent=0, error="file_too_large")
                continue

            out_path = ensure_faststart(src_path)
            w, h, dur, rot = probe_video(out_path)
            if rot in (90, 270) and w and h:
                w, h = h, w

            # Indikator
            stop = asyncio.Event()
            task = asyncio.create_task(_action_pumper(bot, chat_id, stop))
            try:
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(out_path),
                    supports_streaming=True,
                    width=w, height=h, duration=dur,
                    caption="📤 @FastInstaXBot",
                    reply_to_message_id=reply_to
                )
            finally:
                stop.set()
                with contextlib.suppress(Exception):
                    await task

            ok = True
            sent_bytes = size
            # Stat yozib qo'yamiz
            dbm.add_download(local, user_id, chat_id, url, sent_bytes, ok=True)
            dbm.finish_job(local, job_id, ok=True, bytes_sent=sent_bytes)

        except Exception as e:
            with contextlib.suppress(Exception):
                await bot.send_message(chat_id, f"❌ Xatolik: {e}", reply_to_message_id=reply_to)
            dbm.finish_job(local, job_id, ok=False, error=str(e))
            # xatolarda ham keyingisiga o'tamiz


@router.message(F.text)
async def text_catcher(m: Message, bot: Bot):
    url = is_ig_url(m.text or "")
    if not url:
        return

    # Foydalanuvchini ro'yxatga olish
    dbm.add_user(conn, m.from_user.id, m.from_user.username, m.from_user.first_name, m.from_user.last_name)

    # Navbatga qo'shamiz — hech qanday xabar YUBORMAYMIZ
    dbm.enqueue_job(conn, m.from_user.id, m.chat.id, m.message_id, url)
    # Worker navbati kelganda videoni o‘zi yuboradi (reply_to = m.message_id)


async def main():
    bot = Bot(token=settings.BOT_TOKEN)
    # 5 worker'ni ishga tushiramiz
    for i in range(WORKER_CONCURRENCY):
        asyncio.create_task(_worker_loop(i, bot, settings.DB_PATH))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
