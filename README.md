# Nakladnoy Bot

Telegram bot: agent nakladnoy rasmini yuboradi → Gemini o'qiydi → agent tasdiqlaydi → PostgreSQL'ga yoziladi.
Chek rasmlari **Telegram serverlarida** saqlanadi (bazada faqat `file_id`).

## Ishga tushirish
```
pip install -r requirements.txt
python -m bot.main
```
`.env`: `BOT_TOKEN`, `DATABASE_URL` (Supabase Session pooler), `GEMINI_API_KEY`, `ADMIN_IDS`, ixtiyoriy `STORAGE_CHAT_ID`.
Yangi ustunlar (rol, file_id) bot ishga tushganda mavjud bazaga avtomatik qo'shiladi.

## Rollar
- `ADMIN_IDS` dagi odam ro'yxatdan o'tmasdan avtomatik admin.
- `ADMIN_IDS` bo'sh bo'lsa, `/admin` yuborgan birinchi odam admin bo'ladi.
- Admin boshqalarni admin qiladi: foydalanuvchi kartasidan yoki `/addadmin <telegram_id>`.

## Foydalanuvchi
Rasm yuborish, `/stats` (o'z statistikasi), `/cancel`, `/help`.

## Admin (`/admin`)
- **Statistika** (bugun/7/30/hammasi).
- **Foydalanuvchilar** (tasdiqlash, bloklash, admin qilish).
- **Ma'lumotlar bazasi**: xaridorlar, postavshiklar, agentlar, ekspeditorlar, tovarlar, dublikat so'rovlari. Har birining kartasi (statistika, top ro'yxatlar) va "Nakladnoylari" tugmasi bor.
- **Nakladnoylar**: davr va obyekt bo'yicha filtr; har birini **rasm**, **jadval** yoki **PDF** ko'rinishida olish. PDF bazadagi ma'lumotlardan elektron hujjat sifatida yasaladi (`bot/services/pdf.py`, shriftlar `bot/assets/fonts/`).
- **Excel**: nakladnoylar (davr bo'yicha) yoki **butun baza** (9 varaq).

## Railway
Dockerfile avtomatik aniqlanadi. Variables: yuqoridagi `.env` qiymatlari. Volume kerak emas.
