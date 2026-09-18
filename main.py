import asyncio
import logging
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
TOKEN = "8929740278:AAEKrylhzDQ__qQLaqLFyHadEytfMu8ADwM"  # BotFather dan olingan tokenni yozing
SUPER_ADMIN_ID = 7393342078   # O'zingizning Telegram ID raqamingiz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

router = Router()

# ================== BAZA ==================
def get_connection():
    return sqlite3.connect("tests_simple.db", check_same_thread=False)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            code TEXT PRIMARY KEY,
            teacher_id INTEGER,
            file_id TEXT,
            file_type TEXT,
            answers TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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

    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

# ================== FSM HOLATLARI ==================
class TeacherStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_answers = State()

class StudentStates(StatesGroup):
    waiting_for_test_code = State()
    waiting_for_student_answers = State()

class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_name = State()
    waiting_for_channel_link = State()


# ================== MAJBURIY OBUNA ==================
async def check_subscription(bot: Bot, user_id: int) -> bool:
    """Barcha majburiy kanallarga obuna bo'lganligini tekshiradi.
    Bot har bir kanalda admin bo'lishi shart!
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_link, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()

    if not channels:
        return True  # Hech qanday majburiy kanal yo'q

    for ch_id, ch_link, ch_name in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status not in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
                ChatMemberStatus.RESTRICTED,
            ):
                logger.info(f"User {user_id} not subscribed to {ch_id} (status={member.status})")
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


# ================== YORDAMCHI FUNKSIYALAR ==================
def parse_answers(raw: str) -> list[str]:
    """Javoblarni normalizatsiya qiladi."""
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


# ================== START VA OBUNA ==================
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

    is_admin = message.from_user.id == SUPER_ADMIN_ID
    await message.answer(
        "Assalomu alaykum! 👋\n"
        "Test botiga xush kelibsiz.\n\n"
        "Iltimos, o'z rolingizni tanlang:",
        reply_markup=main_menu(is_admin)
    )


@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery, bot: Bot):
    if await check_subscription(bot, callback.from_user.id):
        is_admin = callback.from_user.id == SUPER_ADMIN_ID
        await callback.message.edit_text(
            "✅ Rahmat! Obuna tasdiqlandi.\n\nRolingizni tanlang:",
            reply_markup=main_menu(is_admin)
        )
        await callback.answer("Obuna tasdiqlandi!")
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)


@router.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id == SUPER_ADMIN_ID
    await callback.message.edit_text(
        "Iltimos, o'z rolingizni tanlang:",
        reply_markup=main_menu(is_admin)
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
        "⚠️ Botni shu kanalga <b>admin</b> qilib qo'ying, aks holda obuna tekshiruvi ishlamaydi!",
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
        "📄 Iltimos, test faylini yuboring:\n"
        "• PDF, Word (document)\n"
        "• yoki Rasm (photo)\n\n"
        "Bekor qilish: /cancel"
    )
    await state.set_state(TeacherStates.waiting_for_file)
    await callback.answer()


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
        "• <code>abcd2245</code> (harflar birga)\n\n"
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
    file_id = data.get("file_id")
    file_type = data.get("file_type")

    test_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tests (code, teacher_id, file_id, file_type, answers, is_active) VALUES (?, ?, ?, ?, ?, 1)",
        (test_code, message.from_user.id, file_id, file_type, answers)
    )
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(
        f"✅ <b>Test muvaffaqiyatli yaratildi!</b>\n\n"
        f"🔑 Test kodi: <code>{test_code}</code>\n\n"
        f"O'quvchilarga shu kodni yuboring.\n"
        f"Ular kodni kiritib, faylni olishadi va javob yuborishadi.",
        reply_markup=teacher_panel(),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "my_tests")
async def my_tests(callback: CallbackQuery):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, is_active, answers FROM tests WHERE teacher_id = ? ORDER BY created_at DESC LIMIT 30",
        (callback.from_user.id,)
    )
    tests = cursor.fetchall()
    conn.close()

    if not tests:
        await callback.answer("Hozircha testlaringiz yo'q.", show_alert=True)
        return

    keyboard = []
    for code, is_active, answers in tests:
        status = "🟢" if is_active else "🔴"
        ans_preview = answers[:20] + "..." if len(answers) > 20 else answers
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status} {code} | {ans_preview}",
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
        "SELECT is_active, answers, teacher_id FROM tests WHERE code = ?",
        (test_code,)
    )
    row = cursor.fetchone()
    if not row or row[2] != callback.from_user.id:
        await callback.answer("Test topilmadi yoki sizniki emas.", show_alert=True)
        conn.close()
        return

    is_active, answers, _ = row
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
        f"📌 <b>Test: {test_code}</b>\n"
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
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="my_tests")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "finish_test_menu")
async def finish_test_menu(callback: CallbackQuery):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code FROM tests WHERE teacher_id = ? AND is_active = 1 ORDER BY created_at DESC",
        (callback.from_user.id,)
    )
    tests = cursor.fetchall()
    conn.close()

    if not tests:
        await callback.answer("Hozircha faol testlar yo'q.", show_alert=True)
        return

    keyboard = []
    for (code,) in tests:
        keyboard.append([InlineKeyboardButton(text=f"🏁 {code} ni yakunlash", callback_data=f"close_test_{code}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="role_teacher")])

    await callback.message.edit_text(
        "Qaysi testni yakunlamoqchisiz?\n"
        "Yakunlangandan so'ng o'quvchilarga natija yuboriladi va yangi javob qabul qilinmaydi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("close_test_"))
async def close_test_action(callback: CallbackQuery, bot: Bot):
    test_code = callback.data.replace("close_test_", "")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT teacher_id, is_active FROM tests WHERE code = ?", (test_code,))
    row = cursor.fetchone()
    if not row or row[0] != callback.from_user.id:
        await callback.answer("Bu test sizniki emas yoki topilmadi.", show_alert=True)
        conn.close()
        return
    if row[1] == 0:
        await callback.answer("Bu test allaqachon yakunlangan.", show_alert=True)
        conn.close()
        return

    cursor.execute("UPDATE tests SET is_active = 0 WHERE code = ?", (test_code,))
    cursor.execute(
        "SELECT student_id, student_name, score, total FROM student_results WHERE test_code = ?",
        (test_code,)
    )
    results = cursor.fetchall()
    conn.commit()
    conn.close()

    sent = 0
    for st_id, st_name, score, total in results:
        try:
            await bot.send_message(
                st_id,
                f"🏁 <b>{test_code}</b>-kodli test yakunlandi!\n\n"
                f"📊 Natijangiz: <b>{score} / {total}</b>\n"
                f"Foiz: {(score / total * 100) if total else 0:.1f}%",
                parse_mode=ParseMode.HTML
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Could not send result to {st_id}: {e}")

    keyboard = []
    for st_id, st_name, score, total in results:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{st_name} ({score}/{total})",
                callback_data=f"view_st_{test_code}_{st_id}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ O'qituvchi paneli", callback_data="role_teacher")])

    await callback.message.edit_text(
        f"🏁 <b>{test_code}</b> test muvaffaqiyatli yakunlandi!\n"
        f"Natijalar {sent} ta o'quvchiga yuborildi.\n\n"
        f"Batafsil ko'rish uchun ismini bosing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )
    await callback.answer("Test yakunlandi!")


@router.callback_query(F.data == "view_results_menu")
async def view_results_menu(callback: CallbackQuery):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, is_active FROM tests WHERE teacher_id = ? ORDER BY created_at DESC LIMIT 20",
        (callback.from_user.id,)
    )
    tests = cursor.fetchall()
    conn.close()

    if not tests:
        await callback.answer("Testlar yo'q.", show_alert=True)
        return

    keyboard = []
    for code, is_active in tests:
        status = "🟢" if is_active else "🔴"
        keyboard.append([
            InlineKeyboardButton(text=f"{status} {code}", callback_data=f"results_{code}")
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
    cursor.execute("SELECT teacher_id FROM tests WHERE code = ?", (test_code,))
    row = cursor.fetchone()
    if not row or row[0] != callback.from_user.id:
        await callback.answer("Test topilmadi.", show_alert=True)
        conn.close()
        return

    cursor.execute(
        "SELECT student_id, student_name, score, total FROM student_results WHERE test_code = ? ORDER BY score DESC",
        (test_code,)
    )
    results = cursor.fetchall()
    conn.close()

    if not results:
        await callback.answer("Hali hech kim ishlamagan.", show_alert=True)
        return

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
        f"📊 <b>{test_code}</b> natijalari ({len(results)} ta):\n\n"
        "Batafsil tahlil uchun ismini bosing:",
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
        await message.answer(
            "⚠️ Avval kanallarga obuna bo'ling!",
            reply_markup=markup
        )
        await state.clear()
        return

    test_code = message.text.strip().upper()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT file_id, file_type, is_active FROM tests WHERE code = ?",
        (test_code,)
    )
    test = cursor.fetchone()

    if not test:
        await message.answer("❌ Bunday kodli test topilmadi. Qaytadan kiriting yoki /cancel")
        conn.close()
        return

    file_id, file_type, is_active = test

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
            "Yana ishlash mumkin emas (bitta urinish).",
            parse_mode=ParseMode.HTML
        )
        await state.clear()
        conn.close()
        return

    conn.close()

    await state.update_data(test_code=test_code)

    if file_type == "document":
        await message.answer_document(
            file_id,
            caption="📄 Test fayli. Ishlab bo'lgach javoblaringizni yuboring."
        )
    else:
        await message.answer_photo(
            file_id,
            caption="📸 Test rasmi. Ishlab bo'lgach javoblaringizni yuboring."
        )

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
    cursor.execute("SELECT answers, is_active FROM tests WHERE code = ?", (test_code,))
    test_data = cursor.fetchone()

    if not test_data or test_data[1] == 0:
        await message.answer("❌ Test yakunlangan yoki topilmadi.")
        conn.close()
        await state.clear()
        return

    correct_raw = test_data[0]
    student_raw = message.text.strip()

    if not student_raw:
        await message.answer("Javoblar bo'sh. Qaytadan yuboring.")
        return

    score, total, st_list, corr_list = calculate_score(correct_raw, student_raw)

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

    is_admin = message.from_user.id == SUPER_ADMIN_ID
    await message.answer(
        "✅ <b>Javoblaringiz muvaffaqiyatli qabul qilindi!</b>\n\n"
        f"Hozircha natija yashirin.\n"
        f"O'qituvchi testni yakunlagach, sizga to'liq natija va xatolar yuboriladi.\n\n"
        f"(Javoblar soni: {len(st_list)}, savollar: {total})",
        reply_markup=main_menu(is_admin),
        parse_mode=ParseMode.HTML
    )


# ================== ASOSIY ==================
async def main():
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️  TOKEN ni o'zgartiring! BotFather dan oling.")
        return

    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot ishga tushdi (vaqt cheklovisiz)...")
    print("✅ Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
