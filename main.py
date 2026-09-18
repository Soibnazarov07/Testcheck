import asyncio
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

# Bot tokeningizni shu yerga yozing
TOKEN = "8929740278:AAEKrylhzDQ__qQLaqLFyHadEytfMu8ADwM"

logging.basicConfig(level=logging.INFO)
router = Router()

# --- BAZA BILAN ISHLASH ---
def init_db():
    conn = sqlite3.connect("tests.db")
    cursor = conn.cursor()
    # Testlar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            code TEXT PRIMARY KEY,
            teacher_id INTEGER,
            file_id TEXT,
            file_type TEXT,
            answers TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    # O'quvchilar javoblari jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_code TEXT,
            student_id INTEGER,
            student_name TEXT,
            student_answers TEXT,
            score INTEGER,
            total INTEGER,
            FOREIGN KEY(test_code) REFERENCES tests(code)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- FSM (Holatlar) ---
class TeacherStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_answers = State()

class StudentStates(StatesGroup):
    waiting_for_test_code = State()
    waiting_for_student_answers = State()


# --- KEYBOARDLAR ---
def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👨‍🏫 O'qituvchi", callback_data="role_teacher"),
                InlineKeyboardButton(text="👨‍🎓 O'quvchi", callback_data="role_student"),
            ]
        ]
    )

def teacher_panel():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangi test yaratish", callback_data="create_test")],
            [InlineKeyboardButton(text="🏁 Testni yakunlash va natijalar", callback_data="finish_test")],
            [InlineKeyboardButton(text="◀️ Bosh sahifa", callback_data="back_home")],
        ]
    )


# --- START VA ASOSIY MENYU ---
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Assalomu alaykum! Test botiga xush kelibsiz.\nIltimos, o'z rolingizni tanlang:",
        reply_markup=main_menu()
    )

@router.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Iltimos, o'z rolingizni tanlang:",
        reply_markup=main_menu()
    )


# --- O'QITUVCHI QISMI ---
@router.callback_query(F.data == "role_teacher")
async def role_teacher(callback: CallbackQuery):
    await callback.message.edit_text(
        "O'qituvchi bo'limiga xush kelibsiz. Kerakli amalni tanlang:",
        reply_markup=teacher_panel()
    )

@router.callback_query(F.data == "create_test")
async def create_test(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Iltimos, test faylini yuboring (PDF, Word yoki rasm ko'rinishida):")
    await state.set_state(TeacherStates.waiting_for_file)
    await callback.answer()

@router.message(TeacherStates.waiting_for_file, F.document | F.photo)
async def process_test_file(message: Message, state: FSMContext):
    file_id = message.document.file_id if message.document else message.photo[-1].file_id
    file_type = "document" if message.document else "photo"
    
    await state.update_data(file_id=file_id, file_type=file_type)
    await message.answer(
        "Fayl qabul qilindi.\n\n"
        "Endi test kalitlarini yuboring.\n"
        "Format (ketma-ket): `abcdab...` yoki `1-a, 2-b, 3-c` ko'rinishida yozib yuboring."
    )
    await state.set_state(TeacherStates.waiting_for_answers)

@router.message(TeacherStates.waiting_for_answers)
async def process_test_answers(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("file_id")
    file_type = data.get("file_type")
    answers = message.text.strip()
    
    # Tasodifiy 5 xonali test kodi generatsiya qilish
    test_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    
    # Bazaga saqlash
    conn = sqlite3.connect("tests.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tests (code, teacher_id, file_id, file_type, answers, is_active) VALUES (?, ?, ?, ?, ?, 1)",
        (test_code, message.from_user.id, file_id, file_type, answers)
    )
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(
        f"✅ **Test muvaffaqiyatli yaratildi!**\n\n"
        f"🔑 Test kodi: `{test_code}`\n\n"
        f"O'quvchilarga shu kodni yuboring, ular kodni kiritib testni yechishlari mumkin.",
        reply_markup=teacher_panel(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "finish_test")
async def finish_test_menu(callback: CallbackQuery):
    # O'qituvchining faol testlarini chiqarish
    conn = sqlite3.connect("tests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code FROM tests WHERE teacher_id = ? AND is_active = 1", (callback.from_user.id,))
    tests = cursor.fetchall()
    conn.close()
    
    if not tests:
        await callback.answer("Sizda hozircha faol testlar yo'q.", show_alert=True)
        return
    
    keyboard = []
    for t in tests:
        keyboard.append([InlineKeyboardButton(text=f"Test kodi: {t[0]} ni yakunlash", callback_data=f"close_{t[0]}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="role_teacher")])
    
    await callback.message.edit_text(
        "Qaysi testni yakunlamoqchisiz? Tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("close_"))
async def close_test(callback: CallbackQuery):
    test_code = callback.data.split("_")[1]
    
    conn = sqlite3.connect("tests.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE tests SET is_active = 0 WHERE code = ?", (test_code,))
    
    # Natijalarni yig'ish
    cursor.execute("SELECT student_name, score, total FROM student_results WHERE test_code = ?", (test_code,))
    results = cursor.fetchall()
    conn.commit()
    conn.close()
    
    res_text = f"🏁 **{test_code}-kodli test yakunlandi!**\n\n**O'quvchilar natijalari:**\n"
    if results:
        for idx, r in enumerate(results, 1):
            res_text += f"{idx}. {r[0]} — {r[1]} / {r[2]} ta to'g'ri\n"
    else:
        res_text += "Hali hech kim test ishlamagan."
        
    await callback.message.edit_text(res_text, reply_markup=teacher_panel(), parse_mode="Markdown")


# --- O'QUVCHI QISMI ---
@router.callback_query(F.data == "role_student")
async def role_student(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Iltimos, o'qituvchi bergan **test kodini** kiriting:"
    )
    await state.set_state(StudentStates.waiting_for_test_code)

@router.message(StudentStates.waiting_for_test_code)
async def process_student_code(message: Message, state: FSMContext):
    test_code = message.text.strip().upper()
    
    conn = sqlite3.connect("tests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT file_id, file_type, is_active FROM tests WHERE code = ?", (test_code,))
    test = cursor.fetchone()
    conn.close()
    
    if not test:
        await message.answer("❌ Bunday kodli test topilmadi. Qaytadan kiriting:")
        return
        
    file_id, file_type, is_active = test
    if is_active == 0:
        await message.answer("❌ Bu test o'qituvchi tomonidan allaqachon yakunlangan.")
        await state.clear()
        return
        
    await state.update_data(test_code=test_code)
    
    # Test faylini yuborish
    if file_type == "document":
        await message.answer_document(file_id, caption="📄 Mana test fayli. Uni ishlab bo'lgach, javoblaringizni yuboring.")
    else:
        await message.answer_photo(file_id, caption="📸 Mana test rasmi. Uni ishlab bo'lgach, javoblaringizni yuboring.")
        
    await message.answer(
        "Javoblaringizni yuborish uchun pastdagi formatdan foydalaning:\n"
        "Masalan: `abcdab...` yoki har birini probel bilan `a b c d ...`"
    )
    await state.set_state(StudentStates.waiting_for_student_answers)

@router.message(StudentStates.waiting_for_student_answers)
async def process_student_answers(message: Message, state: FSMContext):
    data = await state.get_data()
    test_code = data.get("test_code")
    student_answers = message.text.strip().replace(" ", "").lower()
    
    # Bazadan to'g'ri javoblarni olish
    conn = sqlite3.connect("tests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT answers, is_active FROM tests WHERE code = ?", (test_code,))
    test_data = cursor.fetchone()
    
    if not test_data or test_data[1] == 0:
        await message.answer("❌ Xatolik: Test topilmadi yoki yakunlangan.")
        conn.close()
        await state.clear()
        return
        
    correct_answers = test_data[0].strip().replace(" ", "").lower()
    
    # Ballarni hisoblash
    score = 0
    total = len(correct_answers)
    for i in range(min(len(student_answers), total)):
        if student_answers[i] == correct_answers[i]:
            score += 1
            
    # O'quvchi natijasini saqlash
    student_name = message.from_user.full_name
    cursor.execute(
        "INSERT INTO student_results (test_code, student_id, student_name, student_answers, score, total) VALUES (?, ?, ?, ?, ?, ?)",
        (test_code, message.from_user.id, student_name, student_answers, score, total)
    )
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(
        "✅ Javoblaringiz qabul qilindi!\n\n"
        "⏳ **Natijangiz hozircha berilmaydi.** O'qituvchi testni yakunlagach, natijangiz hammaga ko'rinadi.",
        reply_markup=main_menu()
    )


# --- ASOSIY ISHGA TUSHIRISH ---
async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
