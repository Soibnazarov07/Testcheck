import asyncio
from datetime import datetime, timedelta
import logging
import random
import string
import sqlite3
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

TOKEN = "8929740278:AAEKrylhzDQ__qQLaqLFyHadEytfMu8ADwM"
SUPER_ADMIN_ID = ID: 7393342078  # O'z Telegram ID raqamingizni yozing

logging.basicConfig(level=logging.INFO)
router = Router()

# --- BAZA BILAN ISHLASH ---
def init_db():
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    
    # Testlar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            code TEXT PRIMARY KEY,
            teacher_id INTEGER,
            file_id TEXT,
            file_type TEXT,
            answers TEXT,
            duration_minutes INTEGER,
            start_time TEXT,
            expires_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    # O'quvchilar natijalari jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_code TEXT,
            student_id INTEGER,
            student_name TEXT,
            student_answers TEXT,
            score INTEGER,
            total INTEGER,
            time_taken TEXT,
            started_at TEXT,
            FOREIGN KEY(test_code) REFERENCES tests(code)
        )
    """)
    
    # Majburiy obuna kanallari
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            channel_name TEXT,
            channel_link TEXT
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

# --- FSM (Holatlar) ---
class TeacherStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_answers = State()
    waiting_for_duration = State()

class StudentStates(StatesGroup):
    waiting_for_test_code = State()
    waiting_for_student_answers = State()

class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_name = State()
    waiting_for_channel_link = State()


# --- MAJBURIY OBUNANI TEKSHIRISH ---
async def check_subscription(bot: Bot, user_id: int) -> bool:
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_link, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()

    if not channels:
        return True

    for ch_id, ch_link, ch_name in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception:
            # Agar bot kanalga qo'shilmagan bo'lsa yoki xatolik bo'lsa
            pass
    return True

async def get_subscription_markup():
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_link, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()

    keyboard = []
    for link, name in channels:
        keyboard.append([InlineKeyboardButton(text=f"📢 {name}", url=link)])
    keyboard.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# --- KEYBOARDLAR ---
def main_menu(is_admin: bool = False):
    buttons = [
        [
            InlineKeyboardButton(text="👨‍🏫 O'qituvchi", callback_data="role_teacher"),
            InlineKeyboardButton(text="👨‍🎓 O'quvchi", callback_data="role_student"),
        ]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Super Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def teacher_panel():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangi test yaratish", callback_data="create_test")],
            [InlineKeyboardButton(text="🏁 Testni yakunlash va natijalar", callback_data="finish_test_menu")],
            [InlineKeyboardButton(text="◀️ Bosh sahifa", callback_data="back_home")],
        ]
    )

def admin_panel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel")],
            [InlineKeyboardButton(text="➖ Kanalni o'chirish", callback_data="del_channel")],
            [InlineKeyboardButton(text="◀️ Bosh sahifa", callback_data="back_home")],
        ]
    )


# --- START VA OBUNA TEKSHIRUV ---
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    
    if not await check_subscription(bot, message.from_user.id):
        markup = await get_subscription_markup()
        await message.answer(
            "⚠️ Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz kerak:",
            reply_markup=markup
        )
        return

    is_admin = (message.from_user.id == SUPER_ADMIN_ID)
    await message.answer(
        "Assalomu alaykum! Test botiga xush kelibsiz.\nIltimos, o'z rolingizni tanlang:",
        reply_markup=main_menu(is_admin)
    )

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery, bot: Bot):
    if await check_subscription(bot, callback.from_user.id):
        is_admin = (callback.from_user.id == SUPER_ADMIN_ID)
        await callback.message.edit_text(
            "Rahmat! Obuna tasdiqlandi. Rolingizni tanlang:",
            reply_markup=main_menu(is_admin)
        )
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)

@router.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = (callback.from_user.id == SUPER_ADMIN_ID)
    await callback.message.edit_text(
        "Iltimos, o'z rolingizni tanlang:",
        reply_markup=main_menu(is_admin)
    )


# --- SUPER ADMIN QISMI ---
@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("Sizda bu huquq yo'q!", show_alert=True)
        return
    await callback.message.edit_text("⚙️ **Super Admin Paneli**", reply_markup=admin_panel_kb(), parse_mode="Markdown")

@router.callback_query(F.data == "add_channel")
async def add_channel_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await callback.message.answer("Kanal ID sini kiriting (masalan: `@kanal_username` yoki `-100123456789`):")
    await state.set_state(AdminStates.waiting_for_channel_id)
    await callback.answer()

@router.message(AdminStates.waiting_for_channel_id)
async def get_ch_id(message: Message, state: FSMContext):
    await state.update_data(ch_id=message.text.strip())
    await message.answer("Kanal nomini kiriting:")
    await state.set_state(AdminStates.waiting_for_channel_name)

@router.message(AdminStates.waiting_for_channel_name)
async def get_ch_name(message: Message, state: FSMContext):
    await state.update_data(ch_name=message.text.strip())
    await message.answer("Kanal havolasini (linkini) kiriting (masalan: `https://t.me/kanal_link`):")
    await state.set_state(AdminStates.waiting_for_channel_link)

@router.message(AdminStates.waiting_for_channel_link)
async def get_ch_link(message: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = data.get("ch_id")
    ch_name = data.get("ch_name")
    ch_link = message.text.strip()
    
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO channels (channel_id, channel_name, channel_link) VALUES (?, ?, ?)", (ch_id, ch_name, ch_link))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ Kanal muvaffaqiyatli qo'shildi!", reply_markup=admin_panel_kb())

@router.callback_query(F.data == "del_channel")
async def del_channel_menu(callback: CallbackQuery):
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()
    
    if not channels:
        await callback.answer("Hozircha majburiy kanallar yo'q.", show_alert=True)
        return
        
    keyboard = []
    for ch_id, name in channels:
        keyboard.append([InlineKeyboardButton(text=f"❌ O'chirish: {name}", callback_data=f"remove_ch_{ch_id}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin_panel")])
    
    await callback.message.edit_text("O'chirmoqchi bo'lgan kanalni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@router.callback_query(F.data.startswith("remove_ch_"))
async def remove_channel_action(callback: CallbackQuery):
    ch_id = callback.data.replace("remove_ch_", "")
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (ch_id,))
    conn.commit()
    conn.close()
    await callback.answer("Kanal o'chirildi!", show_alert=True)
    await callback.message.edit_text("⚙️ **Super Admin Paneli**", reply_markup=admin_panel_kb(), parse_mode="Markdown")


# --- O'QITUVCHI QISMI ---
@router.callback_query(F.data == "role_teacher")
async def role_teacher(callback: CallbackQuery):
    await callback.message.edit_text("O'qituvchi bo'limi:", reply_markup=teacher_panel())

@router.callback_query(F.data == "create_test")
async def create_test(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Iltimos, test faylini yuboring (PDF, Word yoki rasm):")
    await state.set_state(TeacherStates.waiting_for_file)
    await callback.answer()

@router.message(TeacherStates.waiting_for_file, F.document | F.photo)
async def process_test_file(message: Message, state: FSMContext):
    file_id = message.document.file_id if message.document else message.photo[-1].file_id
    file_type = "document" if message.document else "photo"
    
    await state.update_data(file_id=file_id, file_type=file_type)
    await message.answer("Fayl qabul qilindi.\n\nEndi test kalitlarini yuboring (masalan: `a, b, 22, 45, c` yoki `abcd2245`):")
    await state.set_state(TeacherStates.waiting_for_answers)

@router.message(TeacherStates.waiting_for_answers)
async def process_test_answers(message: Message, state: FSMContext):
    answers = message.text.strip()
    await state.update_data(answers=answers)
    await message.answer("Endi test uchun **vaqtni daqiqalarda** kiriting (masalan: `60` - 1 soat uchun):")
    await state.set_state(TeacherStates.waiting_for_duration)

@router.message(TeacherStates.waiting_for_duration)
async def process_test_duration(message: Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting (masalan: 30, 60):")
        return
        
    data = await state.get_data()
    file_id = data.get("file_id")
    file_type = data.get("file_type")
    answers = data.get("answers")
    
    test_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    now = datetime.now()
    expires_at = now + timedelta(minutes=duration)
    
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tests (code, teacher_id, file_id, file_type, answers, duration_minutes, start_time, expires_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (test_code, message.from_user.id, file_id, file_type, answers, duration, now.isoformat(), expires_at.isoformat())
    )
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(
        f"✅ **Test yaratildi!**\n\n"
        f"🔑 Test kodi: `{test_code}`\n"
        f"⏳ Davomiyligi: {duration} daqiqa\n"
        f"⏰ Tugash vaqti: {expires_at.strftime('%Y-%m-%d %H:%M')}",
        reply_markup=teacher_panel(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "finish_test_menu")
async def finish_test_menu(callback: CallbackQuery):
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code, expires_at FROM tests WHERE teacher_id = ? AND is_active = 1", (callback.from_user.id,))
    tests = cursor.fetchall()
    conn.close()
    
    if not tests:
        await callback.answer("Hozircha faol testlar yo'q.", show_alert=True)
        return
    
    keyboard = []
    for t in tests:
        keyboard.append([InlineKeyboardButton(text=f"Test: {t[0]} ni yakunlash", callback_data=f"close_test_{t[0]}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="role_teacher")])
    
    await callback.message.edit_text("Qaysi testni yakunlamoqchisiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@router.callback_query(F.data.startswith("close_test_"))
async def close_test_action(callback: CallbackQuery, bot: Bot):
    test_code = callback.data.replace("close_test_", "")
    
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE tests SET is_active = 0 WHERE code = ?", (test_code,))
    
    # Natijalarni olish
    cursor.execute("SELECT student_id, student_name, score, total, time_taken FROM student_results WHERE test_code = ?", (test_code,))
    results = cursor.fetchall()
    conn.commit()
    conn.close()
    
    # O'quvchilarga natijalarni yuborish
    for r in results:
        st_id, st_name, score, total, t_taken = r
        try:
            await bot.send_message(
                st_id,
                f"🏁 **{test_code}**-kodli test yakunlandi!\n\n"
                f"📊 Natijangiz: **{score} / {total}**\n"
                f"⏱ Sarflangan vaqt: {t_taken}"
            )
        except Exception:
            pass
            
    # O'qituvchiga natijalar ro'yxatini chiqarish
    keyboard = []
    for r in results:
        st_id, st_name, score, total, t_taken = r
        keyboard.append([InlineKeyboardButton(text=f"{st_name} ({score}/{total})", callback_data=f"view_st_{test_code}_{st_id}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="role_teacher")])
    
    await callback.message.edit_text(
        f"🏁 **{test_code}**-kodli test muvaffaqiyatli yakunlandi va o'quvchilarga natijalar yuborildi.\n\n"
        f"O'quvchi javoblarini ko'rish uchun ismini bosing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("view_st_"))
async def view_student_details(callback: CallbackQuery):
    parts = callback.data.split("_")
    test_code = parts[2]
    student_id = int(parts[3])
    
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("SELECT student_name, student_answers, score, total, time_taken FROM student_results WHERE test_code = ? AND student_id = ?", (test_code, student_id))
    res = cursor.fetchone()
    
    cursor.execute("SELECT answers FROM tests WHERE code = ?", (test_code,))
    t_data = cursor.fetchone()
    conn.close()
    
    if not res or not t_data:
        await callback.answer("Ma'lumot topilmadi", show_alert=True)
        return
        
    st_name, st_ans, score, total, t_taken = res
    correct_ans = t_data[0]
    
    # Xatoliklarni solishtirish uchun parse qilish
    st_list = [x.strip() for x in st_ans.replace(",", " ").split()]
    corr_list = [x.strip() for x in correct_ans.replace(",", " ").split()]
    
    details = f"👤 O'quvchi: **{st_name}**\n📊 Ball: **{score}/{total}**\n⏱ Vaqt: {t_taken}\n\n**Savollar tahlili:**\n"
    for i in range(max(len(st_list), len(corr_list))):
        s_val = st_list[i] if i < len(st_list) else "-"
        c_val = corr_list[i] if i < len(corr_list) else "-"
        status = "✅" if s_val == c_val else "❌"
        details += f"{i+1}-savol: {status} (Sizniki: `{s_val}` | To'g'risi: `{c_val}`)\n"
        
    await callback.message.edit_text(
        details,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Orqaga", callback_data="finish_test_menu")]]),
        parse_mode="Markdown"
    )


# --- O'QUVCHI QISMI ---
@router.callback_query(F.data == "role_student")
async def role_student(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("O'qituvchi bergan **test kodini** kiriting:")
    await state.set_state(StudentStates.waiting_for_test_code)

@router.message(StudentStates.waiting_for_test_code)
async def process_student_code(message: Message, state: FSMContext):
    test_code = message.text.strip().upper()
    
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("SELECT file_id, file_type, expires_at, is_active FROM tests WHERE code = ?", (test_code,))
    test = cursor.fetchone()
    conn.close()
    
    if not test:
        await message.answer("❌ Bunday kodli test topilmadi. Qaytadan kiriting:")
        return
        
    file_id, file_type, expires_at_str, is_active = test
    
    # Vaqtni tekshirish
    expires_at = datetime.fromisoformat(expires_at_str)
    if is_active == 0 or datetime.now() > expires_at:
        await message.answer("❌ Bu test muddati tugagan yoki yakunlangan.")
        await state.clear()
        return
        
    # Boshlanish vaqtini saqlaymiz (vaqtni o'lchash uchun)
    await state.update_data(test_code=test_code, start_time=datetime.now().isoformat())
    
    if file_type == "document":
        await message.answer_document(file_id, caption="📄 Test fayli. Ishlab bo'lgach javoblaringizni yuboring.")
    else:
        await message.answer_photo(file_id, caption="📸 Test rasmi. Ishlab bo'lgach javoblaringizni yuboring.")
        
    await message.answer("Javoblaringizni yuboring (masalan: `a, b, 22, 45, c` yoki `abcd2245`):")
    await state.set_state(StudentStates.waiting_for_student_answers)

@router.message(StudentStates.waiting_for_student_answers)
async def process_student_answers(message: Message, state: FSMContext):
    data = await state.get_data()
    test_code = data.get("test_code")
    start_time_str = data.get("start_time")
    
    conn = sqlite3.connect("tests_advanced.db")
    cursor = conn.cursor()
    cursor.execute("SELECT answers, expires_at, is_active FROM tests WHERE code = ?", (test_code,))
    test_data = cursor.fetchone()
    
    if not test_data or test_data[2] == 0 or datetime.now() > datetime.fromisoformat(test_data[1]):
        await message.answer("❌ Test vaqti tugagan yoki yakunlangan.")
        conn.close()
        await state.clear()
        return
        
    correct_raw = test_data[0]
    student_raw = message.text.strip()
    
    # Listga ajratib taqqoslash
    corr_list = [x.strip().lower() for x in correct_raw.replace(",", " ").split()]
    st_list = [x.strip().lower() for x in student_raw.replace(",", " ").split()]
    
    score = 0
    total = len(corr_list)
    for i in range(min(len(st_list), total)):
        if st_list[i] == corr_list[i]:
            score += 1
            
    # Sarflangan vaqtni hisoblash
    start_time = datetime.fromisoformat(start_time_str)
    diff = datetime.now() - start_time
    minutes = int(diff.total_seconds() // 60)
    seconds = int(diff.total_seconds() % 60)
    time_taken_str = f"{minutes} min {seconds} sek"
    
    student_name = message.from_user.full_name
    student_id = message.from_user.id
    
    cursor.execute(
        "INSERT INTO student_results (test_code, student_id, student_name, student_answers, score, total, time_taken, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (test_code, student_id, student_name, student_raw, score, total, time_taken_str, start_time_str)
    )
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(
        f"✅ **Javoblaringiz qabul qilindi!**\n\n"
        f"⏱ Sarflangan vaqt: {time_taken_str}\n"
        f"⏳ O'qituvchi testni yakunlagach, to'liq natijangiz va xatolaringiz sizga yuboriladi.",
        reply_markup=main_menu()
    )


# --- ASOSIY ISHGA TUSHIRISH ---
async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot yangilangan holda ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
