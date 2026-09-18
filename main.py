import asyncio
import logging
import os
import random
import string
import sqlite3
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ================== SOZLAMALAR ==================
TOKEN = os.getenv("BOT_TOKEN", "8929740278:AAEKrylhzDQ__qQLaqLFyHadEytfMu8ADwM")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "7393342078"))
DB_PATH = os.getenv("DB_PATH", "/data/tests_simple.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

router = Router()

# ================== BAZA ==================
def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            code TEXT PRIMARY KEY,
            teacher_id INTEGER,
            name TEXT DEFAULT '',
            file_id TEXT,
            file_type TEXT,
            answers TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    try:
        cursor.execute("ALTER TABLE tests ADD COLUMN name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_code TEXT,
            student_id INTEGER,
            student_name TEXT,
            student_answers TEXT,
            score INTEGER,
            total INTEGER,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(test_code, student_id),
            FOREIGN KEY(test_code) REFERENCES tests(code)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            channel_name TEXT,
            channel_link TEXT
        )
    """)

    # Foydalanuvchilar ism-familiyasi uchun
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    logger.info(f"Database initialized at: {DB_PATH}")

init_db()

# ================== FSM HOLATLARI ==================
class TeacherStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_file = State()
    waiting_for_answers = State()

class StudentStates(StatesGroup):
    waiting_for_test_code = State()
    waiting_for_student_answers = State()

class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_name = State()
    waiting_for_channel_link = State()

class RegisterStates(StatesGroup):
    waiting_for_fullname = State()


# ================== YORDAMCHI FUNKSIYALAR ==================
def get_user_fullname(user_id: int) -> Optional[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def save_user_fullname(user_id: int, full_name: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, full_name) VALUES (?, ?)",
        (user_id, full_name)
    )
    conn.commit()
    conn.close()


# ================== MAJBURIY OBUNA ==================
async def check_subscription(bot: Bot, user_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_link, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()

    if not channels:
        return True

    for ch_id, ch_link, ch_name in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status not in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
                ChatMemberStatus.RESTRICTED,
            ):
                return False
        except Exception as e:
            logger.warning(f"Subscription check error for channel {ch_id}: {e}")
            return False
    return True


async def get_subscription_markup() -> InlineKeyboardMarkup:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_link, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()

    keyboard = []
    for link, name in channels:
        keyboard.append([InlineKeyboardButton(text=f"📢 {name}", url=link)])
    keyboard.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ================== KEYBOARDLAR ==================
def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="👨‍🏫 O'qituvchi", callback_data="role_teacher"),
            InlineKeyboardButton(text="👨‍🎓 O'quvchi", callback_data="role_student"),
        ]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Super Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def teacher_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangi test yaratish", callback_data="create_test")],
            [InlineKeyboardButton(text="📋 Mening testlarim", callback_data="my_tests")],
            [InlineKeyboardButton(text="🏁 Testni yakunlash", callback_data="finish_test_menu")],
            [InlineKeyboardButton(text="📊 Natijalarni ko'rish", callback_data="view_results_menu")],
            [InlineKeyboardButton(text="◀️ Bosh sahifa", callback_data="back_home")],
        ]
    )


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel")],
            [InlineKeyboardButton(text="➖ Kanalni o'chirish", callback_data="del_channel")],
            [InlineKeyboardButton(text="📋 Kanallar ro'yxati", callback_data="list_channels")],
            [InlineKeyboardButton(text="◀️ Bosh sahifa", callback_data="back_home")],
        ]
    )


# ================== YORDAMCHI ==================
def parse_answers(raw: str) -> list[str]:
    raw = raw.strip().lower()
    if "," in raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        parts = [p.strip() for p in raw.split() if p.strip()]
        if len(parts) == 1 and parts[0].isalpha() and len(parts[0]) > 1:
            parts = list(parts[0])
    return parts


def calculate_score(correct_raw: str, student_raw: str) -> tuple[int, int, list[str], list[str]]:
    corr_list = parse_answers(correct_raw)
    st_list = parse_answers(student_raw)
    total = len(corr_list)
    score = 0
    for i in range(min(len(st_list), total)):
        if st_list[i] == corr_list[i]:
            score += 1
    return score, total, st_list, corr_list


def format_detailed_result(st_list: list[str], corr_list: list[str], score: int, total: int) -> str:
    text = (
        f"📊 <b>Natijangiz: {score}/{total}</b> "
        f"({(score / total * 100) if total else 0:.1f}%)\n\n"
        f"<b>Savollar tahlili:</b>\n"
    )
    max_len = max(len(st_list), len(corr_list))
    for i in range(max_len):
        s_val = st_list[i] if i < len(st_list) else "—"
        c_val = corr_list[i] if i < len(corr_list) else "—"
        status = "✅" if s_val == c_val else "❌"
        text += f"{i+1}. {status} Sizniki: <code>{s_val}</code> | To'g'ri: <code>{c_val}</code>\n"
    return text


def format_ranking(results: list, test_name: str, test_code: str) -> str:
    if not results:
        return f"🏁 <b>{test_name}</b> ({test_code}) yakunlandi.\n\nHali hech kim ishlamagan."

    sorted_results = sorted(results, key=lambda x: (x[2], x[3]), reverse=True)

    text = f"🏆 <b>REYTING</b>\n"
    text += f"📌 Test: <b>{test_name}</b>\n"
    text += f"🔑 Kod: <code>{test_code}</code>\n"
    text += f"👥 Ishtirokchilar: {len(results)} ta\n\n"

    medals = ["🥇", "🥈", "🥉"]
    for i, (st_id, st_name, score, total) in enumerate(sorted_results):
        percent = (score / total * 100) if total else 0
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} <b>{st_name}</b> — {score}/{total} ({percent:.1f}%)\n"

    return text


# ================== START VA RO'YXATDAN O'TISH ==================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()

    if not await check_subscription(bot, message.from_user.id):
        markup = await get_subscription_markup()
        await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart!</b>\n\n"
            "Obuna bo'lgach «✅ Obunani tekshirish» tugmasini bosing.",
            reply_markup=markup,
            parse_mode=ParseMode.HTML
        )
        return

    # Ism-familiya tekshirish
    full_name = get_user_fullname(message.from_user.id)
    if not full_name:
        await message.answer(
            "👋 Assalomu alaykum!\n\n"
            "Botdan foydalanish uchun <b>ism va familiyangizni</b> yozing:\n"
            "Masalan: <code>Ali Valiyev</code>\n\n"
            "Bekor qilish: /cancel",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(RegisterStates.waiting_for_fullname)
        return

    is_admin = message.from_user.id == SUPER_ADMIN_ID
    await message.answer(
        f"Assalomu alaykum, <b>{full_name}</b>! 👋\n"
        "Test botiga xush kelibsiz.\n\n"
        "Iltimos, o'z rolingizni tanlang:",
        reply_markup=main_menu(is_admin),
        parse_mode=ParseMode.HTML
    )


@router.message(RegisterStates.waiting_for_fullname)
async def process_fullname(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) < 3:
        await message.answer("Ism-familiya juda qisqa. To'liq yozing (masalan: Ali Valiyev) yoki /cancel")
        return

    save_user_fullname(message.from_user.id, name)
    await state.clear()

    is_admin = message.from_user.id == SUPER_ADMIN_ID
    await message.answer(
        f"✅ Rahmat, <b>{name}</b>!\n\n"
        "Endi o'z rolingizni tanlang:",
        reply_markup=main_menu(is_admin),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery, bot: Bot, state: FSMContext):
    if await check_subscription(bot, callback.from_user.id):
        full_name = get_user_fullname(callback.from_user.id)
        if not full_name:
            await callback.message.edit_text(
                "✅ Rahmat! Obuna tasdiqlandi.\n\n"
                "Endi <b>ism va familiyangizni</b> yozing:\n"
                "Masalan: <code>Ali Valiyev</code>",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(RegisterStates.waiting_for_fullname)
            await callback.answer("Obuna tasdiqlandi!")
            return

        is_admin = callback.from_user.id == SUPER_ADMIN_ID
        await callback.message.edit_text(
            f"✅ Rahmat! Obuna tasdiqlandi.\n\n"
            f"Assalomu alaykum, <b>{full_name}</b>!\n"
            "Rolingizni tanlang:",
            reply_markup=main_menu(is_admin),
            parse_mode=ParseMode.HTML
        )
        await callback.answer("Obuna tasdiqlandi!")
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)


@router.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id == SUPER_ADMIN_ID
    full_name = get_user_fullname(callback.from_user.id) or "Foydalanuvchi"
    await callback.message.edit_text(
        f"Assalomu alaykum, <b>{full_name}</b>!\n"
        "Iltimos, o'z rolingizni tanlang:",
        reply_markup=main_menu(is_admin),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is None:
        await message.answer("Hech qanday jarayon yo'q.")
        return
    await state.clear()
    is_admin = message.from_user.id == SUPER_ADMIN_ID
    full_name = get_user_fullname(message.from_user.id)
    if not full_name:
        await message.answer(
            "❌ Jarayon bekor qilindi.\n\n"
            "Botdan foydalanish uchun <b>ism va familiyangizni</b> yozing:",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(RegisterStates.waiting_for_fullname)
        return

    await message.answer(
        "❌ Jarayon bekor qilindi.\n\nRolingizni tanlang:",
        reply_markup=main_menu(is_admin)
    )


# ================== SUPER ADMIN ==================
@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("Sizda bu huquq yo'q!", show_alert=True)
        return
    await callback.message.edit_text(
        "⚙️ <b>Super Admin Paneli</b>\n\n"
        "Bu yerda majburiy obuna kanallarini boshqarasiz.\n"
        "⚠️ Botni har bir kanalga <b>admin</b> qilib qo'ying!",
        reply_markup=admin_panel_kb(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data == "add_channel")
async def add_channel_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("Huquq yo'q!", show_alert=True)
        return
    await callback.message.answer(
        "Kanal ID sini kiriting:\n"
        "• Username bo'lsa: <code>@kanal_username</code>\n"
        "• Yoki raqamli ID: <code>-1001234567890</code>\n\n"
        "Bekor qilish uchun /cancel"
    )
    await state.set_state(AdminStates.waiting_for_channel_id)
    await callback.answer()


@router.message(AdminStates.waiting_for_channel_id)
async def get_ch_id(message: Message, state: FSMContext):
    ch_id = message.text.strip()
    if not (ch_id.startswith("@") or ch_id.startswith("-") or ch_id.lstrip("-").isdigit()):
        await message.answer("Noto'g'ri format. Qaytadan kiriting yoki /cancel")
        return
    await state.update_data(ch_id=ch_id)
    await message.answer("Kanal nomini kiriting (masalan: Mening Kanalim):")
    await state.set_state(AdminStates.waiting_for_channel_name)


@router.message(AdminStates.waiting_for_channel_name)
async def get_ch_name(message: Message, state: FSMContext):
    await state.update_data(ch_name=message.text.strip())
    await message.answer(
        "Kanal havolasini kiriting:\n"
        "Masalan: <code>https://t.me/kanal_link</code>"
    )
    await state.set_state(AdminStates.waiting_for_channel_link)


@router.message(AdminStates.waiting_for_channel_link)
async def get_ch_link(message: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = data.get("ch_id")
    ch_name = data.get("ch_name")
    ch_link = message.text.strip()

    if not ch_link.startswith("http"):
        await message.answer("Havola http/https bilan boshlanishi kerak. Qaytadan yuboring yoki /cancel")
        return

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO channels (channel_id, channel_name, channel_link) VALUES (?, ?, ?)",
        (ch_id, ch_name, ch_link)
    )
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(
        f"✅ Kanal muvaffaqiyatli qo'shildi!\n\n"
        f"• ID: <code>{ch_id}</code>\n"
        f"• Nom: {ch_name}\n"
        f"• Link: {ch_link}\n\n"
        "⚠️ Botni shu kanalga <b>admin</b> qilib qo'ying!",
        reply_markup=admin_panel_kb(),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "list_channels")
async def list_channels(callback: CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_name, channel_link FROM channels")
    channels = cursor.fetchall()
    conn.close()

    if not channels:
        await callback.answer("Hozircha kanallar yo'q.", show_alert=True)
        return

    text = "📋 <b>Majburiy kanallar ro'yxati:</b>\n\n"
    for ch_id, name, link in channels:
        text += f"• <b>{name}</b>\n  ID: <code>{ch_id}</code>\n  Link: {link}\n\n"

    await callback.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "del_channel")
async def del_channel_menu(callback: CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()

    if not channels:
        await callback.answer("Hozircha majburiy kanallar yo'q.", show_alert=True)
        return

    keyboard = []
    for ch_id, name in channels:
        keyboard.append([InlineKeyboardButton(text=f"❌ {name}", callback_data=f"remove_ch_{ch_id}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin_panel")])

    await callback.message.edit_text(
        "O'chirmoqchi bo'lgan kanalni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("remove_ch_"))
async def remove_channel_action(callback: CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    ch_id = callback.data.replace("remove_ch_", "")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (ch_id,))
    conn.commit()
    conn.close()
    await callback.answer("Kanal o'chirildi!", show_alert=True)
    await callback.message.edit_text(
        "⚙️ <b>Super Admin Paneli</b>",
        reply_markup=admin_panel_kb(),
        parse_mode=ParseMode.HTML
    )


# ================== O'QITUVCHI ==================
@router.callback_query(F.data == "role_teacher")
async def role_teacher(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👨‍🏫 <b>O'qituvchi bo'limi</b>\n\nKerakli amalni tanlang:",
        reply_markup=teacher_panel(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data == "create_test")
async def create_test(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📝 Avval <b>test nomini</b> yozing:\n"
        "Masalan: <code>Matematika 5-sinf</code> yoki <code>Ingliz tili test №3</code>\n\n"
        "Bekor qilish: /cancel",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(TeacherStates.waiting_for_name)
    await callback.answer()


@router.message(TeacherStates.waiting_for_name)
async def process_test_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) < 2:
        await message.answer("Nom juda qisqa. Qaytadan yozing yoki /cancel")
        return
    await state.update_data(test_name=name)
    await message.answer(
        f"✅ Test nomi: <b>{name}</b>\n\n"
        "Endi test faylini yuboring (PDF, Word yoki rasm):\n\n"
        "Bekor qilish: /cancel",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(TeacherStates.waiting_for_file)


@router.message(TeacherStates.waiting_for_file, F.document | F.photo)
async def process_test_file(message: Message, state: FSMContext):
    if message.document:
        file_id = message.document.file_id
        file_type = "document"
    else:
        file_id = message.photo[-1].file_id
        file_type = "photo"

    await state.update_data(file_id=file_id, file_type=file_type)
    await message.answer(
        "✅ Fayl qabul qilindi.\n\n"
        "Endi test kalitlarini (to'g'ri javoblarni) yuboring.\n\n"
        "Misollar:\n"
        "• <code>a, b, c, 22, 45</code>\n"
        "• <code>a b c 22 45</code>\n"
        "• <code>abcd2245</code>\n\n"
        "Bekor qilish: /cancel",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(TeacherStates.waiting_for_answers)


@router.message(TeacherStates.waiting_for_file)
async def process_test_file_invalid(message: Message):
    await message.answer("❌ Faqat hujjat (PDF/Word) yoki rasm yuboring. Qaytadan urinib ko'ring yoki /cancel")


@router.message(TeacherStates.waiting_for_answers)
async def process_test_answers(message: Message, state: FSMContext):
    answers = message.text.strip()
    if not answers:
        await message.answer("Javoblar bo'sh bo'lishi mumkin emas. Qaytadan yuboring.")
        return

    data = await state.get_data()
    test_name = data.get("test_name", "Nomsiz test")
    file_id = data.get("file_id")
    file_type = data.get("file_type")

    test_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tests (code, teacher_id, name, file_id, file_type, answers, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)",
        (test_code, message.from_user.id, test_name, file_id, file_type, answers)
    )
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(
        f"✅ <b>Test muvaffaqiyatli yaratildi!</b>\n\n"
        f"📌 Nom: <b>{test_name}</b>\n"
        f"🔑 Kod: <code>{test_code}</code>\n\n"
        f"O'quvchilarga shu kodni yuboring.",
        reply_markup=teacher_panel(),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "my_tests")
async def my_tests(callback: CallbackQuery):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, name, is_active FROM tests WHERE teacher_id = ? ORDER BY created_at DESC LIMIT 30",
        (callback.from_user.id,)
    )
    tests = cursor.fetchall()
    conn.close()

    if not tests:
        await callback.answer("Hozircha testlaringiz yo'q.", show_alert=True)
        return

    keyboard = []
    for code, name, is_active in tests:
        status = "🟢" if is_active else "🔴"
        display_name = name if name else "Nomsiz"
        short_name = display_name[:25] + "..." if len(display_name) > 25 else display_name
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status} {short_name} ({code})",
                callback_data=f"test_info_{code}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="role_teacher")])

    await callback.message.edit_text(
        "📋 <b>Sizning testlaringiz</b> (oxirgi 30 ta):\n"
        "🟢 — faol, 🔴 — yakunlangan\n\n"
        "Batafsil ko'rish uchun testni bosing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("test_info_"))
async def test_info(callback: CallbackQuery):
    test_code = callback.data.replace("test_info_", "")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT is_active, answers, teacher_id, name FROM tests WHERE code = ?",
        (test_code,)
    )
    row = cursor.fetchone()
    if not row or row[2] != callback.from_user.id:
        await callback.answer("Test topilmadi yoki sizniki emas.", show_alert=True)
        conn.close()
        return

    is_active, answers, _, test_name = row
    test_name = test_name or "Nomsiz test"

    cursor.execute(
        "SELECT COUNT(*), AVG(score * 1.0 / total * 100) FROM student_results WHERE test_code = ?",
        (test_code,)
    )
    count_row = cursor.fetchone()
    students_count = count_row[0] or 0
    avg_percent = count_row[1] or 0
    conn.close()

    status = "🟢 Faol" if is_active else "🔴 Yakunlangan"
    text = (
        f"📌 <b>{test_name}</b>\n"
        f"🔑 Kod: <code>{test_code}</code>\n"
        f"Holat: {status}\n"
        f"Kalitlar: <code>{answers}</code>\n"
        f"Ishtirokchilar: {students_count} ta\n"
        f"O'rtacha ball: {avg_percent:.1f}%\n"
    )

    keyboard = [
        [InlineKeyboardButton(text="📊 Natijalarni ko'rish", callback_data=f"results_{test_code}")],
    ]
    if is_active:
        keyboard.append([InlineKeyboardButton(text="🏁 Testni yakunlash", callback_data=f"close_test_{test_code}")])
    else:
        keyboard.append([InlineKeyboardButton(text="🔄 Testni qayta ochish", callback_data=f"reopen_test_{test_code}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="my_tests")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data.startswith("reopen_test_"))
async def reopen_test(callback: CallbackQuery):
    test_code = callback.data.replace("reopen_test_", "")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT teacher_id, name FROM tests WHERE code = ?", (test_code,))
    row = cursor.fetchone()
    if not row or row[0] != callback.from_user.id:
        await callback.answer("Bu test sizniki emas.", show_alert=True)
        conn.close()
        return

    cursor.execute("UPDATE tests SET is_active = 1 WHERE code = ?", (test_code,))
    conn.commit()
    conn.close()

    test_name = row[1] or test_code
    await callback.answer("Test qayta ochildi!", show_alert=True)
    await callback.message.edit_text(
        f"🔄 <b>{test_name}</b> ({test_code}) qayta faollashtirildi!\n\n"
        "Endi o'quvchilar yana javob yuborishi mumkin.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Mening testlarim", callback_data="my_tests")],
            [InlineKeyboardButton(text="◀️ O'qituvchi paneli", callback_data="role_teacher")],
        ]),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "finish_test_menu")
async def finish_test_menu(callback: CallbackQuery):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, name FROM tests WHERE teacher_id = ? AND is_active = 1 ORDER BY created_at DESC",
        (callback.from_user.id,)
    )
    tests = cursor.fetchall()
    conn.close()

    if not tests:
        await callback.answer("Hozircha faol testlar yo'q.", show_alert=True)
        return

    keyboard = []
    for code, name in tests:
        display = f"{name} ({code})" if name else code
        keyboard.append([InlineKeyboardButton(text=f"🏁 {display}", callback_data=f"close_test_{code}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="role_teacher")])

    await callback.message.edit_text(
        "Qaysi testni yakunlamoqchisiz?\n"
        "Yakunlangandan so'ng reyting chiqadi va o'quvchilarga batafsil natija yuboriladi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("close_test_"))
async def close_test_action(callback: CallbackQuery, bot: Bot):
    test_code = callback.data.replace("close_test_", "")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT teacher_id, is_active, name, answers FROM tests WHERE code = ?", (test_code,))
    row = cursor.fetchone()
    if not row or row[0] != callback.from_user.id:
        await callback.answer("Bu test sizniki emas yoki topilmadi.", show_alert=True)
        conn.close()
        return
    if row[1] == 0:
        await callback.answer("Bu test allaqachon yakunlangan.", show_alert=True)
        conn.close()
        return

    test_name = row[2] or "Nomsiz test"
    correct_raw = row[3]

    cursor.execute("UPDATE tests SET is_active = 0 WHERE code = ?", (test_code,))
    cursor.execute(
        "SELECT student_id, student_name, student_answers, score, total FROM student_results WHERE test_code = ?",
        (test_code,)
    )
    results = cursor.fetchall()
    conn.commit()
    conn.close()

    # O'quvchilarga batafsil natija yuborish (endi shu yerda yuboriladi)
    sent = 0
    for st_id, st_name, st_answers, score, total in results:
        try:
            st_list = parse_answers(st_answers)
            corr_list = parse_answers(correct_raw)
            detailed = format_detailed_result(st_list, corr_list, score, total)

            await bot.send_message(
                st_id,
                f"🏁 <b>{test_name}</b> ({test_code}) test yakunlandi!\n\n"
                f"{detailed}",
                parse_mode=ParseMode.HTML
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Could not send result to {st_id}: {e}")

    # O'qituvchiga reyting
    ranking_results = [(r[0], r[1], r[3], r[4]) for r in results]  # id, name, score, total
    ranking_text = format_ranking(ranking_results, test_name, test_code)
    await callback.message.answer(ranking_text, parse_mode=ParseMode.HTML)

    # Natijalar ro'yxati tugmalari
    keyboard = []
    for st_id, st_name, _, score, total in results:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{st_name} ({score}/{total})",
                callback_data=f"view_st_{test_code}_{st_id}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="🔄 Testni qayta ochish", callback_data=f"reopen_test_{test_code}")])
    keyboard.append([InlineKeyboardButton(text="◀️ O'qituvchi paneli", callback_data="role_teacher")])

    await callback.message.edit_text(
        f"🏁 <b>{test_name}</b> ({test_code}) yakunlandi!\n"
        f"Batafsil natijalar {sent} ta o'quvchiga yuborildi.\n\n"
        f"Batafsil ko'rish uchun ismini bosing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )
    await callback.answer("Test yakunlandi + reyting chiqarildi!")


@router.callback_query(F.data == "view_results_menu")
async def view_results_menu(callback: CallbackQuery):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, name, is_active FROM tests WHERE teacher_id = ? ORDER BY created_at DESC LIMIT 20",
        (callback.from_user.id,)
    )
    tests = cursor.fetchall()
    conn.close()

    if not tests:
        await callback.answer("Testlar yo'q.", show_alert=True)
        return

    keyboard = []
    for code, name, is_active in tests:
        status = "🟢" if is_active else "🔴"
        display = f"{name} ({code})" if name else code
        keyboard.append([
            InlineKeyboardButton(text=f"{status} {display}", callback_data=f"results_{code}")
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="role_teacher")])

    await callback.message.edit_text(
        "📊 Qaysi test natijalarini ko'rmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("results_"))
async def show_results(callback: CallbackQuery):
    test_code = callback.data.replace("results_", "")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT teacher_id, name FROM tests WHERE code = ?", (test_code,))
    row = cursor.fetchone()
    if not row or row[0] != callback.from_user.id:
        await callback.answer("Test topilmadi.", show_alert=True)
        conn.close()
        return

    test_name = row[1] or test_code

    cursor.execute(
        "SELECT student_id, student_name, score, total FROM student_results WHERE test_code = ? ORDER BY score DESC, total DESC",
        (test_code,)
    )
    results = cursor.fetchall()
    conn.close()

    if not results:
        await callback.answer("Hali hech kim ishlamagan.", show_alert=True)
        return

    ranking = format_ranking(results, test_name, test_code)

    keyboard = []
    for st_id, st_name, score, total in results:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{st_name} — {score}/{total}",
                callback_data=f"view_st_{test_code}_{st_id}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="view_results_menu")])

    await callback.message.edit_text(
        ranking + "\n\nBatafsil tahlil uchun ismini bosing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_st_"))
async def view_student_details(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer("Xato format", show_alert=True)
        return
    test_code = parts[2]
    student_id = int(parts[3])

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT student_name, student_answers, score, total FROM student_results WHERE test_code = ? AND student_id = ?",
        (test_code, student_id)
    )
    res = cursor.fetchone()
    cursor.execute("SELECT answers, teacher_id FROM tests WHERE code = ?", (test_code,))
    t_data = cursor.fetchone()
    conn.close()

    if not res or not t_data or t_data[1] != callback.from_user.id:
        await callback.answer("Ma'lumot topilmadi", show_alert=True)
        return

    st_name, st_ans, score, total = res
    correct_ans = t_data[0]

    st_list = parse_answers(st_ans)
    corr_list = parse_answers(correct_ans)

    details = (
        f"👤 <b>{st_name}</b>\n"
        f"📊 Ball: <b>{score}/{total}</b> ({(score/total*100) if total else 0:.1f}%)\n\n"
        f"<b>Savollar tahlili:</b>\n"
    )
    max_len = max(len(st_list), len(corr_list))
    for i in range(max_len):
        s_val = st_list[i] if i < len(st_list) else "—"
        c_val = corr_list[i] if i < len(corr_list) else "—"
        status = "✅" if s_val == c_val else "❌"
        details += f"{i+1}. {status} Sizniki: <code>{s_val}</code> | To'g'ri: <code>{c_val}</code>\n"

    await callback.message.edit_text(
        details,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data=f"results_{test_code}")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ================== O'QUVCHI ==================
@router.callback_query(F.data == "role_student")
async def role_student(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👨‍🎓 <b>O'quvchi bo'limi</b>\n\n"
        "O'qituvchi bergan <b>test kodini</b> kiriting:\n"
        "(masalan: A1B2C3)\n\n"
        "Bekor qilish: /cancel",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(StudentStates.waiting_for_test_code)
    await callback.answer()


@router.message(StudentStates.waiting_for_test_code)
async def process_student_code(message: Message, state: FSMContext, bot: Bot):
    if not await check_subscription(bot, message.from_user.id):
        markup = await get_subscription_markup()
        await message.answer("⚠️ Avval kanallarga obuna bo'ling!", reply_markup=markup)
        await state.clear()
        return

    test_code = message.text.strip().upper()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT file_id, file_type, is_active, name FROM tests WHERE code = ?",
        (test_code,)
    )
    test = cursor.fetchone()

    if not test:
        await message.answer("❌ Bunday kodli test topilmadi. Qaytadan kiriting yoki /cancel")
        conn.close()
        return

    file_id, file_type, is_active, test_name = test
    test_name = test_name or "Test"

    if is_active == 0:
        await message.answer("❌ Bu test o'qituvchi tomonidan yakunlangan. Yangi javob qabul qilinmaydi.")
        await state.clear()
        conn.close()
        return

    cursor.execute(
        "SELECT score, total FROM student_results WHERE test_code = ? AND student_id = ?",
        (test_code, message.from_user.id)
    )
    existing = cursor.fetchone()
    if existing:
        await message.answer(
            f"ℹ️ Siz bu testni allaqachon ishlagansiz.\n"
            f"Natijangiz: <b>{existing[0]}/{existing[1]}</b>\n\n"
            "Yana ishlash mumkin emas (bitta urinish).\n"
            "Batafsil tahlil o'qituvchi testni yakunlagach keladi.",
            parse_mode=ParseMode.HTML
        )
        await state.clear()
        conn.close()
        return

    conn.close()

    await state.update_data(test_code=test_code)

    caption = f"📌 <b>{test_name}</b>\n🔑 Kod: {test_code}\n\nIshlab bo'lgach javoblaringizni yuboring."

    if file_type == "document":
        await message.answer_document(file_id, caption=caption, parse_mode=ParseMode.HTML)
    else:
        await message.answer_photo(file_id, caption=caption, parse_mode=ParseMode.HTML)

    await message.answer(
        "✏️ Javoblaringizni yuboring.\n\n"
        "Misollar:\n"
        "• <code>a, b, c, 22, 45</code>\n"
        "• <code>a b c 22 45</code>\n"
        "• <code>abcd2245</code>\n\n"
        "Bekor qilish: /cancel",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(StudentStates.waiting_for_student_answers)


@router.message(StudentStates.waiting_for_student_answers)
async def process_student_answers(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    test_code = data.get("test_code")

    if not test_code:
        await message.answer("Xatolik yuz berdi. /start dan boshlang.")
        await state.clear()
        return

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT answers, is_active, name FROM tests WHERE code = ?", (test_code,))
    test_data = cursor.fetchone()

    if not test_data or test_data[1] == 0:
        await message.answer("❌ Test yakunlangan yoki topilmadi.")
        conn.close()
        await state.clear()
        return

    correct_raw = test_data[0]
    test_name = test_data[2] or test_code
    student_raw = message.text.strip()

    if not student_raw:
        await message.answer("Javoblar bo'sh. Qaytadan yuboring.")
        return

    score, total, st_list, corr_list = calculate_score(correct_raw, student_raw)

    # Saqlangan ism-familiyani olish
    student_name = get_user_fullname(message.from_user.id)
    if not student_name:
        student_name = message.from_user.full_name or f"User {message.from_user.id}"

    student_id = message.from_user.id

    try:
        cursor.execute(
            "INSERT INTO student_results (test_code, student_id, student_name, student_answers, score, total) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (test_code, student_id, student_name, student_raw, score, total)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        await message.answer("Siz bu testni allaqachon ishlagansiz.")
        conn.close()
        await state.clear()
        return

    conn.close()
    await state.clear()

    # ★★★ MUHIM: Batafsil javoblar KO'RSATILMAYDI ★★★
    # Faqat qabul qilinganligi haqida xabar
    is_admin = message.from_user.id == SUPER_ADMIN_ID
    await message.answer(
        f"✅ <b>Javoblaringiz qabul qilindi!</b>\n\n"
        f"📌 Test: <b>{test_name}</b>\n"
        f"🔑 Kod: <code>{test_code}</code>\n\n"
        f"📊 Ballingiz o'qituvchi testni yakunlagandan keyin batafsil tahlil bilan birga yuboriladi.\n\n"
        f"Kuting...",
        reply_markup=main_menu(is_admin),
        parse_mode=ParseMode.HTML
    )


# ================== ASOSIY ==================
async def main():
    if TOKEN == "YOUR_BOT_TOKEN_HERE" or not TOKEN:
        print("⚠️  BOT_TOKEN ni sozlang!")
        return

    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info(f"Bot ishga tushdi. Database: {DB_PATH}")
    print(f"✅ Bot muvaffaqiyatli ishga tushdi! DB: {DB_PATH}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
