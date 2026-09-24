"""
DuuRoon shop Ai — Telegram do'kon boti (BEPUL Gemini versiyasi, /katalog buyrug'i bilan, v3)

Nima qiladi:
  - Kanalingizdagi postlarni (rasm + narx matni) katalogga saqlaydi va har bir rasmni AI bilan tasvirlab qo'yadi
  - Mijoz kanaldan olgan kiyim rasmini botga tashasa, o'sha kiyimni topib narxi, razmeri, yetkazib berish haqida aytadi
  - Mijozning xato yozgan gaplarini ham tushunadi
  - Mijoz olmoqchi bo'lsa, ma'lumotlarini yig'ib sizga "Zakaz tushdi" deb yuboradi

O'rnatish:  pip3 install python-telegram-bot google-genai
Kerakli 3 ta narsa (terminalda export bilan kiritiladi):
  TELEGRAM_BOT_TOKEN   - @BotFather bergan token
  OWNER_CHAT_ID        - sizning Telegram ID raqamingiz (@userinfobot dan oling)
  GEMINI_API_KEY       - aistudio.google.com dan bepul olgan kalitingiz
Ishga tushirish:  python3 duuroon_shop_bot_gemini.py
"""

import asyncio import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

import json
import os
import re

from google import genai
from google.genai import types
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

# ====== SHU IKKI QATORNI O'ZINGIZNIKIGA ALMASHTIRING ======
CONTACT_PHONE = "+998 XX XXX XX XX"
DELIVERY_INFO = "Yetkazib berish shartlari aniqlanmagan"  # masalan: "Toshkent bo'ylab 1 kunda, 20 000 so'm"
# ==========================================================

# Model nomi: bepul ishlaydigan modelni aistudio.google.com dagi ro'yxatdan tekshiring
MODEL = "gemini-3.5-flash-lite"

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_CHAT_ID"])
CATALOG_FILE = "catalog.json"
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
history = {}  # har bir mijoz uchun oxirgi xabarlar: [{"role": "user"/"model", "text": ...}]


# ---------- Yordamchi ----------
async def image_part(photo):
    f = await photo.get_file()
    data = bytes(await f.download_as_bytearray())
    return types.Part.from_bytes(data=data, mime_type="image/jpeg")


# ---------- Katalog ----------
def load_catalog():
    try:
        with open(CATALOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


async def add_to_catalog(msg):
    text = msg.caption or msg.text or ""
    photo = msg.photo[-1] if msg.photo else None
    if not text and not photo:
        return False
    look = ""
    if photo:  # rasmni AI tasvirlab qo'yadi, keyin mijoz rasmi bilan solishtirish uchun
        try:
            r = await client.aio.models.generate_content(
                model=MODEL,
                contents=[await image_part(photo),
                          "Bu kiyimni qisqa tasvirla: turi, rangi, fasoni, o'ziga xos belgilari. Bir-ikki gap."])
            look = r.text or ""
        except Exception as e:
            print("Rasmni tasvirlashda xato:", e)
    catalog = load_catalog()
    catalog.append({"text": text, "look": look,
                    "photo_id": photo.file_id if photo else None,
                    "unique_id": photo.file_unique_id if photo else None})
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)
    return True


def system_prompt():
    items = "\n".join(
        f"[{i}] {p['text']}" + (f"\n    Ko'rinishi: {p['look']}" if p.get("look") else "")
        for i, p in enumerate(load_catalog()))
    return f"""Sen "DuuRoon shop" kiyim do'konining sotuvchi AI yordamchisisan (nomi: DuuRoon shop Ai).
Mijoz qaysi tilda yozsa (o'zbekcha lotin/kirill, ruscha), shu tilda do'stona va qisqa javob ber.
Mijoz xato yozsa, qisqartirib yozsa yoki so'zlarni buzib yozsa ham, nima demoqchi ekanini tushun va javob ber. Uning xatosini to'g'rilama.

QOIDALAR:
- Faqat quyidagi katalogdagi ma'lumotga tayan. Narx, razmer, rang yoki mavjudligini O'YLAB TOPMA.
- Mijoz kiyim so'rasa yoki rasm yuborsa: qaysi kiyim ekanini aniqla va narxi, razmerlari, rangi haqida katalogdagini ayt. Rasm yuborilsa, "Ko'rinishi" tavsiflari bilan solishtir. Aniq topa olmasang, eng yaqin 1-3 tasini taklif qil.
- Kiyim rasmini ko'rsatmoqchi bo'lsang, javob oxirida [PHOTO:raqam] deb yoz (katalogdagi raqam).
- Yetkazib berish haqida so'rasa: {DELIVERY_INFO}
- Katalogda yo'q narsa so'ralsa yoki aniq bilmasang: "Qo'shimcha ma'lumot uchun shu raqamga bog'laning: {CONTACT_PHONE}" de.
- Mijoz sotib olmoqchi yoki buyurtma bermoqchi bo'lsa, avval so'ra: qaysi kiyim, razmer, ism, telefon raqam, manzil.
  Hammasi yig'ilgandan keyin javobingning oxirida bitta qatorda yoz:
  [ORDER] kiyim | razmer | ism | telefon | manzil
  va mijozga "Buyurtmangiz qabul qilindi, tez orada siz bilan bog'lanamiz. Qo'shimcha ma'lumot uchun: {CONTACT_PHONE}" de.

KATALOG:
{items or "(katalog hozircha bo'sh)"}"""


# ---------- Rasm tavsiflari yo'q kiyimlarni to'ldirish ----------
LOOK_PROMPT = "Bu kiyimni qisqa tasvirla: turi, rangi, fasoni, o'ziga xos belgilari. Bir-ikki gap."


def save_catalog(catalog):
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)


async def fill_missing_looks(bot):
    """Bot yoqilganda, tavsifi yo'q rasmlarni birma-bir tavsiflab chiqadi (orqa fonda)."""
    for p in load_catalog():
        if not p.get("photo_id") or p.get("look"):
            continue
        try:
            f = await bot.get_file(p["photo_id"])
            data = bytes(await f.download_as_bytearray())
            r = await client.aio.models.generate_content(
                model=MODEL,
                contents=[types.Part.from_bytes(data=data, mime_type="image/jpeg"), LOOK_PROMPT])
            look = r.text or ""
            catalog = load_catalog()  # yangi postlar yo'qolmasligi uchun qayta o'qiymiz
            for q in catalog:
                if q.get("photo_id") == p["photo_id"]:
                    q["look"] = look
            save_catalog(catalog)
        except Exception as e:
            print("Tavsiflashda xato (keyingi safar davom etadi):", e)
            break
        await asyncio.sleep(4)  # bepul limitdan oshib ketmaslik uchun
    print("Rasm tavsiflari tekshirildi.")


async def on_start(app):
    asyncio.create_task(fill_missing_looks(app.bot))


# ---------- Kanal postlari ----------
async def channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_to_catalog(update.channel_post)


# ---------- Mijozlar bilan suhbat ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalomu alaykum! Men DuuRoon shop Ai.\n\n"
        "🛍 Barcha kiyimlarni ko'rish uchun /katalog bosing.\n"
        "📷 Kanaldagi kiyimning rasmini yuboring yoki savol yozing, narxi va razmerlarini aytaman.")


async def customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user

    # Egasi eski kanal postlarini botga forward qilsa, katalogga qo'shiladi
    if user.id == OWNER_ID and msg.forward_origin:
        if await add_to_catalog(msg):
            await msg.reply_text("Katalogga qo'shildi ✅")
        return

    catalog = load_catalog()
    parts = []
    text = msg.text or msg.caption or "Shu kiyimning narxi va razmerlari qanday?"
    if msg.photo:
        parts.append(await image_part(msg.photo[-1]))
        for i, p in enumerate(catalog):  # kanaldan aynan o'sha rasm forward qilingan bo'lsa
            if p.get("unique_id") == msg.photo[-1].file_unique_id:
                text += f"\n(Tizim eslatmasi: bu katalogdagi [{i}] raqamli kiyimning aynan o'zi.)"
                break
    parts.append(types.Part.from_text(text=text))

    past = history.setdefault(user.id, [])
    contents = [types.Content(role=h["role"], parts=[types.Part.from_text(text=h["text"])]) for h in past]
    contents.append(types.Content(role="user", parts=parts))
    try:
        resp = await client.aio.models.generate_content(
            model=MODEL, contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_prompt(), max_output_tokens=800))
    except Exception as e:
        print("Xato:", e)
        await msg.reply_text(f"Uzr, hozir javob bera olmayapman. Iltimos, shu raqamga bog'laning: {CONTACT_PHONE}")
        return
    answer = resp.text or ""

    photos = re.findall(r"\[PHOTO:(\d+)\]", answer)
    order = re.search(r"\[ORDER\](.*)", answer, re.S)
    clean = re.sub(r"\[PHOTO:\d+\]|\[ORDER\].*", "", answer, flags=re.S).strip()

    past += [{"role": "user", "text": text}, {"role": "model", "text": clean}]
    del past[:-12]  # faqat oxirgi 12 xabar

    if clean:
        await msg.reply_text(clean)
    for n in photos[:3]:
        i = int(n)
        if i < len(catalog) and catalog[i]["photo_id"]:
            await msg.reply_photo(catalog[i]["photo_id"])

    if order:
        who = f"{user.full_name} (@{user.username})" if user.username else user.full_name
        await context.bot.send_message(
            OWNER_ID,
            f"🛒 Zakaz tushdi!\n\nMijoz: {who}\nTelegram ID: {user.id}\n\n{order.group(1).strip()}")


# ---------- Katalog (Uzum Market kabi) ----------
PAGE = 5  # bir sahifada nechta kiyim ko'rsatiladi


async def send_page(chat_id, page, bot):
    catalog = load_catalog()
    if not catalog:
        await bot.send_message(chat_id, "Katalog hozircha bo'sh.")
        return
    start_i = page * PAGE
    end_i = min(start_i + PAGE, len(catalog))
    for i in range(start_i, end_i):
        p = catalog[i]
        caption = f"№{i}\n{p['text']}"[:1000]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Buyurtma berish", callback_data=f"order:{i}")]])
        if p.get("photo_id"):
            await bot.send_photo(chat_id, p["photo_id"], caption=caption, reply_markup=kb)
        else:
            await bot.send_message(chat_id, caption, reply_markup=kb)
    if end_i < len(catalog):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Keyingilari ▶", callback_data=f"page:{page + 1}")]])
        await bot.send_message(chat_id, f"Ko'rsatildi: {end_i} / {len(catalog)}", reply_markup=kb)


async def katalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_page(update.message.chat_id, 0, context.bot)


async def aloqa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📞 Aloqa: {CONTACT_PHONE}\n🚚 Yetkazib berish: {DELIVERY_INFO}")


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kind, _, val = q.data.partition(":")
    chat_id = q.message.chat_id
    if kind == "page":
        await send_page(chat_id, int(val), context.bot)
    elif kind == "order":
        i = int(val)
        past = history.setdefault(q.from_user.id, [])
        reply = "Zo'r tanlov! Iltimos, razmeringizni, ismingizni, telefon raqamingizni va manzilingizni yozing."
        past += [{"role": "user", "text": f"Men katalogdagi [{i}] raqamli kiyimni olmoqchiman."},
                 {"role": "model", "text": reply}]
        del past[:-12]
        await context.bot.send_message(chat_id, reply)


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(on_start).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("katalog", katalog))
    app.add_handler(CommandHandler("aloqa", aloqa))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, channel_post))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.TEXT | filters.PHOTO) & ~filters.COMMAND, customer))
    print("DuuRoon shop Ai ishga tushdi. To'xtatish: Control + C")
    app.run_polling()


if __name__ == "__main__":
    main()
