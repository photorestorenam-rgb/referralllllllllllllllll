import asyncio
import os
import sqlite3
from contextlib import contextmanager
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv


# =========================================================
# SOZLAMALAR
# =========================================================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError(
        "BOT_TOKEN topilmadi! .env faylida BOT_TOKEN=... yozing."
    )

# Cashback foizi
CASHBACK_PERCENT = 5.0

# Database
DB_FILE = "referral.db"

bot = Bot(token=TOKEN)
dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

@contextmanager
def get_db():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")

        yield conn

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def create_database():
    with get_db() as conn:
        cursor = conn.cursor()

        # USERS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                referred_by INTEGER,
                referrals INTEGER DEFAULT 0,
                cashback REAL DEFAULT 0
            )
        """)

        # SALES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                cashback REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


# =========================================================
# USER QO‘SHISH
# =========================================================

def add_user(
    user_id: int,
    username: str,
    first_name: str,
    referred_by: int | None = None
):
    with get_db() as conn:
        cursor = conn.cursor()

        # User mavjudligini tekshirish
        cursor.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user_id,)
        )

        exists = cursor.fetchone()

        if exists:
            cursor.execute("""
                UPDATE users
                SET username = ?,
                    first_name = ?
                WHERE user_id = ?
            """, (
                username or "",
                first_name or "",
                user_id
            ))

            return False

        # Referral tekshirish
        valid_referrer = None

        if referred_by and referred_by != user_id:

            cursor.execute(
                "SELECT user_id FROM users WHERE user_id = ?",
                (referred_by,)
            )

            if cursor.fetchone():
                valid_referrer = referred_by

        # Yangi user
        cursor.execute("""
            INSERT INTO users (
                user_id,
                username,
                first_name,
                referred_by,
                referrals,
                cashback
            )
            VALUES (?, ?, ?, ?, 0, 0)
        """, (
            user_id,
            username or "",
            first_name or "",
            valid_referrer
        ))

        # Referral egasiga +1
        if valid_referrer:

            cursor.execute("""
                UPDATE users
                SET referrals = referrals + 1
                WHERE user_id = ?
            """, (valid_referrer,))

        return True


# =========================================================
# USER MA'LUMOTI
# =========================================================

def get_user(user_id: int):

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                user_id,
                username,
                first_name,
                referred_by,
                referrals,
                cashback
            FROM users
            WHERE user_id = ?
        """, (user_id,))

        return cursor.fetchone()


# =========================================================
# SAVDO QO‘SHISH
# =========================================================

def add_sale(user_id: int, amount: float):

    cashback = amount * CASHBACK_PERCENT / 100

    with get_db() as conn:
        cursor = conn.cursor()

        # Savdoni saqlash
        cursor.execute("""
            INSERT INTO sales (
                user_id,
                amount,
                cashback
            )
            VALUES (?, ?, ?)
        """, (
            user_id,
            amount,
            cashback
        ))

        # Cashbackni balansga qo‘shish
        cursor.execute("""
            UPDATE users
            SET cashback = cashback + ?
            WHERE user_id = ?
        """, (
            cashback,
            user_id
        ))

        # Yangi balans
        cursor.execute("""
            SELECT cashback
            FROM users
            WHERE user_id = ?
        """, (user_id,))

        result = cursor.fetchone()

        balance = result[0] if result else cashback

        return cashback, balance


# =========================================================
# CASHBACK TARIXI
# =========================================================

def get_sales(user_id: int, limit: int = 10):

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                amount,
                cashback,
                created_at
            FROM sales
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (
            user_id,
            limit
        ))

        return cursor.fetchall()


# =========================================================
# REYTING
# =========================================================

def get_rating():

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                first_name,
                username,
                referrals
            FROM users
            ORDER BY referrals DESC
            LIMIT 10
        """)

        return cursor.fetchall()


# =========================================================
# MENYU
# =========================================================

def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="💰 Cashback",
                    callback_data="cashback"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📜 Cashback tarixi",
                    callback_data="history"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🛒 Savdo",
                    callback_data="sale"
                )
            ],

            [
                InlineKeyboardButton(
                    text="👥 Referral",
                    callback_data="referral"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🔗 Referral link",
                    callback_data="link"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🏆 Reyting",
                    callback_data="rating"
                )
            ]
        ]
    )


# =========================================================
# /START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):

    referral_id = None

    parts = message.text.split()

    if len(parts) > 1 and parts[1].isdigit():
        referral_id = int(parts[1])

    new_user = add_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "User",
        referred_by=referral_id
    )

    user = get_user(message.from_user.id)

    referrals = user[4]
    cashback = user[5]

    text = f"""
👋 <b>Salom, {message.from_user.first_name}!</b>

🎁 <b>Referral + Cashback bot</b>

👥 Referral: <b>{referrals} ta</b>
💰 Cashback: <b>{cashback:,.0f} so‘m</b>
📈 Cashback foizi: <b>{CASHBACK_PERCENT:g}%</b>

👇 Menyudan foydalaning.
"""

    if new_user and referral_id:
        text += "\n🎉 Siz referral orqali qo‘shildingiz!"

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =========================================================
# CASHBACK
# =========================================================

@dp.callback_query(F.data == "cashback")
async def cashback_button(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    if not user:
        await callback.answer(
            "Avval /start bosing.",
            show_alert=True
        )
        return

    balance = user[5]

    await callback.message.answer(
        f"""
💰 <b>CASНBACK BALANSI</b>

💵 Sizning balansingiz:

<b>{balance:,.0f} so‘m</b>

📈 Cashback:
<b>{CASHBACK_PERCENT:g}%</b>

🛒 Har bir savdodan cashback yig‘iladi.
""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🛒 Savdo qilish",
                        callback_data="sale"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📜 Tarix",
                        callback_data="history"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 Menyu",
                        callback_data="menu"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# SAVDO BOSHLASH
# =========================================================

sale_waiting = set()


@dp.callback_query(F.data == "sale")
async def sale_button(callback: CallbackQuery):

    sale_waiting.add(callback.from_user.id)

    await callback.message.answer(
        f"""
🛒 <b>SAVDO</b>

Savdo summasini yuboring.

Masalan:

<code>100000</code>

100 000 so‘m savdoga:

💰 Cashback: <b>5 000 so‘m</b>

📈 Cashback foizi:
<b>{CASHBACK_PERCENT:g}%</b>

❌ Bekor qilish uchun:
<code>/start</code>
""",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# SAVDO SUMMASI
# =========================================================

@dp.message()
async def sale_amount(message: Message):

    user_id = message.from_user.id

    # Faqat savdo kutayotgan userga ishlaydi
    if user_id not in sale_waiting:
        return

    if not message.text:
        return

    value = message.text.strip()

    # So‘m formatlarini tozalash
    value = value.replace(" ", "")
    value = value.replace(",", "")
    value = value.replace("_", "")

    try:
        amount = float(value)

    except ValueError:

        await message.answer(
            """
❌ <b>Noto‘g‘ri summa.</b>

Faqat raqam yuboring.

Masalan:

<code>100000</code>
""",
            parse_mode="HTML"
        )

        return

    if amount <= 0:

        await message.answer(
            "❌ Savdo summasi 0 dan katta bo‘lishi kerak."
        )

        return

    # Juda katta qiymatlardan himoya
    if amount > 1_000_000_000_000:

        await message.answer(
            "❌ Kiritilgan summa juda katta."
        )

        return

    sale_waiting.discard(user_id)

    cashback, balance = add_sale(
        user_id,
        amount
    )

    await message.answer(
        f"""
✅ <b>SAVDO QABUL QILINDI</b>

🛒 Savdo:
<b>{amount:,.0f} so‘m</b>

📈 Cashback:
<b>{CASHBACK_PERCENT:g}%</b>

💰 Sizga qo‘shildi:
<b>+{cashback:,.0f} so‘m</b>

━━━━━━━━━━━━━━━━

💵 Jami cashback:
<b>{balance:,.0f} so‘m</b>
""",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =========================================================
# CASHBACK TARIXI
# =========================================================

@dp.callback_query(F.data == "history")
async def history_button(callback: CallbackQuery):

    sales = get_sales(
        callback.from_user.id,
        10
    )

    if not sales:

        text = """
📜 <b>CASHBACK TARIXI</b>

Hali savdolar mavjud emas.

🛒 Birinchi savdongizni kiriting.
"""

    else:

        text = "📜 <b>CASHBACK TARIXI</b>\n\n"

        for i, sale in enumerate(sales, 1):

            amount = sale[0]
            cashback = sale[1]
            date = sale[2]

            text += (
                f"<b>{i}.</b> "
                f"🛒 {amount:,.0f} so‘m\n"
                f"   💰 +{cashback:,.0f} so‘m\n"
                f"   🕒 {date}\n\n"
            )

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 Menyu",
                        callback_data="menu"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# REFERRAL
# =========================================================

@dp.callback_query(F.data == "referral")
async def referral_button(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    if not user:

        await callback.answer(
            "Avval /start bosing.",
            show_alert=True
        )

        return

    referrals = user[4]

    await callback.message.answer(
        f"""
👥 <b>REFERRAL</b>

Siz taklif qilganlar:

<b>{referrals} ta</b>

Do‘stlaringizni referral
linkingiz orqali taklif qiling.
""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔗 Referral link",
                        callback_data="link"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🏆 Reyting",
                        callback_data="rating"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 Menyu",
                        callback_data="menu"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# REFERRAL LINK
# =========================================================

@dp.callback_query(F.data == "link")
async def referral_link(callback: CallbackQuery):

    bot_info = await bot.get_me()

    link = (
        f"https://t.me/"
        f"{bot_info.username}"
        f"?start="
        f"{callback.from_user.id}"
    )

    share_text = (
        "🎁 Botga qo‘shiling!\n\n"
        "Mening referral linkim orqali kiring 👇"
    )

    share_url = (
        "https://t.me/share/url"
        f"?url={quote(link)}"
        f"&text={quote(share_text)}"
    )

    user = get_user(
        callback.from_user.id
    )

    referrals = user[4] if user else 0

    await callback.message.answer(
        f"""
🔗 <b>REFERRAL LINK</b>

<code>{link}</code>

👥 Sizning referral:
<b>{referrals} ta</b>

📤 Linkni do‘stlaringizga yuboring.
""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📤 Ulashish",
                        url=share_url
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 Menyu",
                        callback_data="menu"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# REYTING
# =========================================================

@dp.callback_query(F.data == "rating")
async def rating_button(callback: CallbackQuery):

    users = get_rating()

    text = "🏆 <b>TOP 10 REFERRAL</b>\n\n"

    if not users:

        text += "Hali foydalanuvchilar yo‘q."

    else:

        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉"
        }

        for i, user in enumerate(users, 1):

            first_name = user[0] or "User"
            username = user[1]
            referrals = user[2]

            if username:
                name = f"@{username}"
            else:
                name = first_name

            medal = medals.get(
                i,
                f"{i}."
            )

            text += (
                f"{medal} {name} — "
                f"👥 <b>{referrals}</b>\n"
            )

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 Menyu",
                        callback_data="menu"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# MENYU
# =========================================================

@dp.callback_query(F.data == "menu")
async def menu_button(callback: CallbackQuery):

    # Savdo kutish holatini bekor qilish
    sale_waiting.discard(
        callback.from_user.id
    )

    await callback.message.answer(
        "🏠 <b>ASOSIY MENYU</b>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================

async def main():

    create_database()

    print("==============================")
    print("🤖 BOT ISHLAYAPTI!")
    print("==============================")
    print(
        f"💰 Cashback: "
        f"{CASHBACK_PERCENT:g}%"
    )

    try:

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        await dp.start_polling(bot)

    finally:

        await bot.session.close()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("🛑 Bot to‘xtatildi.")
