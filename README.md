# Fast IG Bot Light (yt-dlp + Aiogram v3)

Yengil, tez va barqaror Instagram video yuklovchi Telegram bot.
- `yt-dlp` orqali yuklaydi (Reels/Posts, ba’zi Stories linklari).
- Global qayta so‘rov (retry) oralig‘i: **5 soniya** (antispam, Instagram rate limit).
- Statistika: foydalanuvchi / guruh kesimida hisoblaydi (SQLite).
- Guruhlarda ham ishlaydi (link yuborilsa yoki bot mention qilinsa).
- Fayl hajmi 2GB dan katta bo‘lsa ogohlantiradi.

## Tez start
1. Python 3.11+ o‘rnatilgan bo‘lsin.
2. Reponi oching (zip’ni yozib oling) va quyidagilarni bajaring:
   ```bash
   cd fast_ig_bot_light
   python -m venv .venv
   .venv/Scripts/activate  # Windows
   # yoki
   source .venv/bin/activate  # Linux
   pip install -r requirements.txt
   cp .env.example .env
   ```
3. `.env` faylida `BOT_TOKEN=` qiymatini to‘ldiring.
4. Ishga tushirish:
   ```bash
   python -m fast_ig_bot_light.bot
   ```

> **Eslatma (guruhlar):** BotFather’da **Privacy mode** ni o‘chirib qo‘ying yoki botni @mention qilib yuboring — shunda linklarni ko‘ra oladi.

## Buyruqlar
- `/start` — qisqacha ma’lumot
- `/help` — foydalanish yo‘riqnomasi
- `/stats` — shaxsiy statistika (DM) yoki guruhda yozsangiz guruh statistikasi
- Guruhda: IG link yuboring (yoki botni @mention qiling) — bot yuklab, javob qaytaradi.

## Muhim parametrlari
- Qayta so‘rov (retry) oralig‘i: 5s (global). Ketma-ket yuklashlar orasida kamida 5s kutadi.
- Fayl limiti: 2GB (Telegram limiti). Katta bo‘lsa fayl sifatida yubora olmaydi.

## Docker (ixtiyoriy)
```bash
docker build -t ig-light .
docker run --rm -it --name igbot --env-file .env ig-light
```