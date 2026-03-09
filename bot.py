import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from telegram.error import BadRequest, Forbidden

# --- CONFIGURATION ---
BOT_TOKEN = '8648708297:AAGg9LGFC8YD6DAYE222oK3AM8pX47z5McM'
ADMIN_ID = 8325031590
PAYMENT_LINK_URL = "https://link.payway.com.kh/ABAPAY4r421457y"

# === INVESTMENT PLANS CONFIGURATION ===
# This defines the cost for each specific level
INVESTMENT_PLANS = [
    {"level": 1, "cost": 5, "percent": 40, "duration_hours": 1},
    {"level": 2, "cost": 15, "percent": 50, "duration_hours": 3},
    {"level": 3, "cost": 25, "percent": 30, "duration_hours": 6},
    {"level": 4, "cost": 50, "percent": 40, "duration_hours": 12},
    {"level": 5, "cost": 100, "percent": 30, "duration_hours": 12},
    {"level": 6, "cost": 200, "percent": 30, "duration_hours": 24}
]

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('bank_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT DEFAULT 'មិនទាន់កំណត់',
            age TEXT DEFAULT 'មិនទាន់កំណត់',
            living TEXT DEFAULT 'មិនទាន់កំណត់',
            balance REAL DEFAULT 0.0,
            current_plan_level INTEGER DEFAULT 1,
            investment_end_time TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            type TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
    # Ensure columns exist
    try: cursor.execute("ALTER TABLE users ADD COLUMN current_plan_level INTEGER DEFAULT 1")
    except: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN investment_end_time TEXT")
    except: pass

    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('bank_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, name, age, living, balance, current_plan_level, investment_end_time FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_all_users():
    conn = sqlite3.connect('bank_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def update_user_field(user_id, field, value):
    conn = sqlite3.connect('bank_bot.db')
    cursor = conn.cursor()
    allowed_fields = ['name', 'age', 'living', 'balance', 'current_plan_level', 'investment_end_time']
    if field in allowed_fields:
        query = f"UPDATE users SET {field} = ? WHERE user_id = ?"
        cursor.execute(query, (value, user_id))
        conn.commit()
    conn.close()

def create_user(user_id, username):
    if not get_user(user_id):
        conn = sqlite3.connect('bank_bot.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()
        conn.close()

def add_transaction(user_id, amount, tx_type):
    conn = sqlite3.connect('bank_bot.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO transactions (user_id, amount, type) VALUES (?, ?, ?)", (user_id, amount, tx_type))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return tx_id

def get_transaction(tx_id):
    conn = sqlite3.connect('bank_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE tx_id = ?", (tx_id,))
    tx = cursor.fetchone()
    conn.close()
    return tx

def update_transaction_status(tx_id, status):
    conn = sqlite3.connect('bank_bot.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE transactions SET status = ? WHERE tx_id = ?", (status, tx_id))
    conn.commit()
    conn.close()

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- STATES FOR CONVERSATION ---
(DEPOSIT_AMOUNT, DEPOSIT_PHOTO, WITHDRAW_AMOUNT, WITHDRAW_PHOTO,
 ADMIN_SELECT_USER, ADMIN_EDIT_FIELD, ADMIN_EDIT_VALUE, ADMIN_BROADCAST_MSG) = range(8)

# --- KEYBOARDS ---
def main_keyboard(is_admin=False):
    keyboard = [
        [InlineKeyboardButton("💰 ពិនិត្យសមតុល្យ", callback_data='balance')],
        [InlineKeyboardButton("👤 ព័ត៌មានផ្ទាល់ខ្លួន", callback_data='profile')],
        [InlineKeyboardButton("📥 ដាក់ប្រាក់", callback_data='deposit'),
         InlineKeyboardButton("📤 ដកប្រាក់", callback_data='withdraw')],
        [InlineKeyboardButton("📈 វិនិយោគ", callback_data='invest_menu')],
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton("🛡️ ផ្ទាំងគ្រប់គ្រង", callback_data='admin_panel')])
    return InlineKeyboardMarkup(keyboard)

# --- GENERAL COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "គ្មានឈ្មោះ"
    create_user(user_id, username)
    
    await check_investment_status(context, user_id)

    is_admin = (user_id == ADMIN_ID)
    await update.message.reply_text(
        "សូមស្វាគមន៍មកកាន់ Bot ធនាគារវិនិយោគ!\nសូមជ្រើសរើសជម្រើសខាងក្រោម:",
        reply_markup=main_keyboard(is_admin)
    )

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    await check_investment_status(context, user_id)
    user_data = get_user(user_id) 
    
    is_admin = (user_id == ADMIN_ID)
    
    if data == 'balance':
        balance = user_data[5] if user_data else 0.0
        await query.message.edit_text(f"💰 សមតុល្យបច្ចុប្បន្នរបស់អ្នក: ${balance:.2f}", reply_markup=main_keyboard(is_admin))
    
    elif data == 'profile':
        if user_data:
            # Safe access to plan level
            current_level = user_data[6] if user_data[6] is not None else 1
            inv_status = "ទំនេរ" if not user_data[7] else f"កំពុងដំណើរការ (រួចរាល់ {user_data[7]})"
            
            text = (f"👤 **ព័ត៌មានផ្ទាល់ខ្លួន**\n\n"
                    f"🆔 Telegram ID: `{user_data[0]}`\n"
                    f"ឈ្មោះ: {user_data[2]}\n"
                    f"អាយុ: {user_data[3]}\n"
                    f"ទីកន្លែងរស់: {user_data[4]}\n"
                    f"សមតុល្យ: ${user_data[5]:.2f}\n"
                    f"គម្រោងបច្ចុប្បន្ន: Level {current_level}\n"
                    f"ស្ថានភាពវិនិយោគ: {inv_status}")
        else:
            text = "រកមិនឃើញព័ត៌មានទេ។"
        await query.message.edit_text(text, parse_mode='Markdown', reply_markup=main_keyboard(is_admin))
    
    elif data == 'deposit':
        await query.message.edit_text("📥 សូមបញ្ចូលចំនួនទឹកប្រាក់ដែលចង់ដាក់ ($):")
        return DEPOSIT_AMOUNT
    
    elif data == 'withdraw':
        await query.message.edit_text("📤 សូមបញ្ចូលចំនួនទឹកប្រាក់ដែលចង់ដក ($):")
        return WITHDRAW_AMOUNT
    
    elif data == 'back_menu':
        await query.message.edit_text("ម៉ឺនុយសំខាន់:", reply_markup=main_keyboard(is_admin))
        return ConversationHandler.END
        
    elif data == 'invest_menu':
        await show_investment_menu(update, context)
        return ConversationHandler.END
        
    elif data == 'admin_panel' and is_admin:
        await admin_panel_handler(update, context)
        return ConversationHandler.END
    
    return ConversationHandler.END

# --- INVESTMENT LOGIC ---

async def check_investment_status(context: ContextTypes.DEFAULT_TYPE, user_id):
    user = get_user(user_id)
    if not user: return

    # Safe access to current_plan_level
    current_plan_level = user[6] if user[6] is not None else 1
    end_time_str = user[7]
    
    if end_time_str:
        try:
            end_time = datetime.fromisoformat(end_time_str)
            if datetime.now() >= end_time:
                plan = next((p for p in INVESTMENT_PLANS if p['level'] == current_plan_level), None)
                
                if plan:
                    profit_amt = plan['cost'] * (plan['percent'] / 100)
                    total_return = plan['cost'] + profit_amt
                    
                    new_balance = user[5] + total_return
                    update_user_field(user_id, 'balance', new_balance)
                    
                    next_level = current_plan_level + 1
                    update_user_field(user_id, 'current_plan_level', next_level)
                    update_user_field(user_id, 'investment_end_time', None)
                    
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"🎉 **ការវិនិយោគរួចរាល់!**\n\n"
                                 f"អ្នកបានបំពេញគម្រោង Level {current_plan_level} ដោយជោគជ័យ។\n"
                                 f"ទឹកប្រាក់ទទួលបាន: ${total_return:.2f}\n"
                                 f"សមតុល្យថ្មី: ${new_balance:.2f}\n\n"
                                 f"ឥឡូវនេះអ្នកអាចចាប់ផ្តើមគម្រោងថ្មីបាទទៀត។",
                            parse_mode='Markdown'
                        )
                    except Exception:
                        pass
                else:
                    update_user_field(user_id, 'investment_end_time', None)
        except ValueError:
            pass

async def show_investment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await check_investment_status(context, user_id)
    
    user = get_user(user_id)
    if not user: return

    current_balance = user[5]
    current_level = user[6] if user[6] is not None else 1
    end_time_str = user[7]
    
    text = "📈 **ផ្ទាំងវិនិយោគ**\n\n"
    keyboard = []

    if end_time_str:
        try:
            end_time = datetime.fromisoformat(end_time_str)
            remaining = end_time - datetime.now()
            
            secs = int(remaining.total_seconds())
            if secs < 0: secs = 0
            hours = secs // 3600
            minutes = (secs % 3600) // 60
            
            running_plan = next((p for p in INVESTMENT_PLANS if p['level'] == current_level), None)
            plan_name = f"Level {current_level}" if running_plan else "Unknown"

            text += (f"ស្ថានភាព: 🕒 **កំពុងដំណើរការ**\n"
                     f"គម្រោង: {plan_name}\n"
                     f"នៅសល់ពេល: {hours} ម៉ោង {minutes} នាទី\n\n"
                     f"សូមរង់ចាំរហូតដល់គ្រប់ពេលវេលា។")
        except:
            text += "កំពុងដំណើរការ..."
            
        keyboard.append([InlineKeyboardButton("🔄 ទាញស្ថានភាព", callback_data='invest_menu')])
    
    else:
        text += f"សមតុល្យរបស់អ្នក: ${current_balance:.2f}\n\n"
        text += "សូមជ្រើសរើសគម្រោងដែលអ្នកចង់វិនិយោគ៖\n"
        
        for plan in INVESTMENT_PLANS:
            total_return = plan['cost'] + (plan['cost'] * plan['percent'] / 100)
            btn_text = f"Plan {plan['level']}: ${plan['cost']} ➔ ${total_return:.0f} ({plan['duration_hours']}h)"
            
            if current_balance >= plan['cost']:
                keyboard.append([InlineKeyboardButton(f"✅ {btn_text}", callback_data=f"do_invest_{plan['level']}")])
            else:
                keyboard.append([InlineKeyboardButton(f"🔒 {btn_text}", callback_data=f"do_invest_{plan['level']}")])

    keyboard.append([InlineKeyboardButton("🔙 ត្រឡប់ក្រោយ", callback_data='back_menu')])
    
    try:
        await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            logging.error(f"Error: {e}")
    except Exception as e:
        logging.error(f"Error: {e}")

async def process_start_investment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    
    level = int(query.data.split('_')[2])
    plan = next((p for p in INVESTMENT_PLANS if p['level'] == level), None)
    
    if not plan:
        await query.answer("កំហុសក្នុងគម្រោង!", show_alert=True)
        return

    if user[5] < plan['cost']:
        await query.answer("❌ សមតុល្យមិនគ្រាន់សម្រាប់គម្រោងនេះទេ!", show_alert=True)
        return

    new_balance = user[5] - plan['cost']
    update_user_field(user_id, 'balance', new_balance)
    
    end_time = datetime.now() + timedelta(hours=plan['duration_hours'])
    update_user_field(user_id, 'investment_end_time', end_time.isoformat())
    update_user_field(user_id, 'current_plan_level', plan['level'])
    
    msg_admin = (f"📈 **ការវិនិយោគថ្មី**\n"
                 f"User: @{user[1]} (ID: {user_id})\n"
                 f"Plan: Level {plan['level']} (${plan['cost']})\n"
                 f"Time: {plan['duration_hours']} Hours")
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg_admin, parse_mode='Markdown')
    
    await show_investment_menu(update, context)


# --- DEPOSIT HANDLERS ---

async def deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text
    try:
        amount = float(amount_text)
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("ចំនួនទឹកប្រាក់មិនត្រឹមត្រូវ។ សូមបញ្ចូលជាលេខ (ឧ. 100)។")
        return DEPOSIT_AMOUNT

    context.user_data['tx_amount'] = amount
    
    keyboard = []
    final_link = PAYMENT_LINK_URL.replace("{amount}", str(amount))
    keyboard.append([InlineKeyboardButton("🔗 ចុចទីនេះដើម្បីបង់ប្រាក់", url=final_link)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text_message = (
        f"📥 **ការណែនាំសម្រាប់ដាក់ប្រាក់**\n\n"
        f"ចំនួនទឹកប្រាក់: ${amount:.2f}\n\n"
        f"1. សូមចុចប៊ូតុងខាងក្រោមដើម្បីទៅទំព័របង់ប្រាក់។\n"
        f"2. បន្ទាប់ពីបង់ប្រាក់រួច សូមត្រឡប់មកទីនេះ ហើយផ្ញើរូបភាពបង្កាន់ដៃមក Bot។"
    )
        
    await update.message.reply_text(text_message, parse_mode='Markdown', reply_markup=reply_markup)
    await update.message.reply_text("📷 រង់ចាំរូបភាពបង្កាន់ដៃរបស់អ្នក...")
    return DEPOSIT_PHOTO

async def deposit_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    amount = context.user_data.get('tx_amount', 0)
    
    photo_file = update.message.photo[-1].file_id
    tx_id = add_transaction(user_id, amount, 'deposit')
    
    keyboard = [
        [
            InlineKeyboardButton("✅ អនុម័ត", callback_data=f"approve_{tx_id}"),
            InlineKeyboardButton("❌ បដិសេធ", callback_data=f"reject_{tx_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    caption = (f"📥 **សំណើដាក់ប្រាក់ថ្មី**\n\n"
               f"User ID: {user_id}\n"
               f"ឈ្មោះអ្នកប្រើ: @{user[1]}\n"
               f"ចំនួនទឹកប្រាក់: ${amount:.2f}\n"
               f"លេខសម្គាល់: {tx_id}")
    
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo_file, caption=caption, parse_mode='Markdown', reply_markup=reply_markup)
    await update.message.reply_text("✅ សំណើដាក់ប្រាក់របស់អ្នកបានផ្ញើទៅកាន់ Admin រួចរាល់។", reply_markup=main_keyboard(user_id == ADMIN_ID))
    
    context.user_data.clear()
    return ConversationHandler.END

# --- WITHDRAW HANDLERS ---

async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    try:
        amount = float(amount_text)
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("ចំនួនទឹកប្រាក់មិនត្រឹមត្រូវ។ សូមបញ្ចូលជាលេខ។")
        return WITHDRAW_AMOUNT

    if user[5] < amount:
        await update.message.reply_text("❌ សមតុល្យមិនគ្រប់គ្រាន់។", reply_markup=main_keyboard(user_id == ADMIN_ID))
        return ConversationHandler.END
    
    context.user_data['tx_amount'] = amount
    await update.message.reply_text("📷 សូមផ្ញើរូបភាព QR Code ឬគណនីធនាគាររបស់អ្នកសម្រាប់ទទួលប្រាក់:")
    return WITHDRAW_PHOTO

async def withdraw_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    amount = context.user_data.get('tx_amount', 0)
    
    photo_file = update.message.photo[-1].file_id
    tx_id = add_transaction(user_id, amount, 'withdraw')
    
    keyboard = [
        [
            InlineKeyboardButton("✅ អនុម័ត (បង់ប្រាក់រួច)", callback_data=f"approve_{tx_id}"),
            InlineKeyboardButton("❌ បដិសេធ", callback_data=f"reject_{tx_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    caption = (f"📤 **សំណើដកប្រាក់ថ្មី**\n\n"
               f"User ID: {user_id}\n"
               f"ឈ្មោះអ្នកប្រើ: @{user[1]}\n"
               f"ចំនួនទឹកប្រាក់: ${amount:.2f}\n"
               f"លេខសម្គាល់: {tx_id}")
    
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo_file, caption=caption, parse_mode='Markdown', reply_markup=reply_markup)
    await update.message.reply_text("✅ សំណើដកប្រាក់របស់អ្នកបានផ្ញើទៅកាន់ Admin រួចរាល់។", reply_markup=main_keyboard(user_id == ADMIN_ID))
    
    context.user_data.clear()
    return ConversationHandler.END

# --- ADMIN APPROVAL HANDLERS ---

async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.answer("អ្នកមិនមានសិទ្ធិគ្រប់គ្រងទេ!", show_alert=True)
        return
    
    data = query.data
    parts = data.split('_')
    action = parts[0]
    tx_id = int(parts[1])
    
    tx = get_transaction(tx_id)
    if not tx:
        await query.edit_message_text(text="កំហុស: រកមិនឃើញប្រតិបត្តិការទេ។")
        return
    
    if tx[4] != 'pending':
        await query.answer("ប្រតិបត្តិការនេះត្រូវបានដោះស្រាយរួចហើយ។")
        return

    user_id = tx[1]
    amount = tx[2]
    tx_type = tx[3]
    user = get_user(user_id)
    
    if action == 'approve':
        current_balance = user[5]
        
        if tx_type == 'deposit':
            new_balance = current_balance + amount
            msg_type = "ដាក់ប្រាក់"
            update_user_field(user_id, 'balance', new_balance)
            
        elif tx_type == 'withdraw':
            if current_balance < amount:
                 await query.answer("សមតុល្យអ្នកប្រើមិនគ្រប់គ្រាន់ទេ!", show_alert=True)
                 return
            new_balance = current_balance - amount
            msg_type = "ដកប្រាក់"
            update_user_field(user_id, 'balance', new_balance)
        
        update_transaction_status(tx_id, 'approved')
        
        try:
            await context.bot.send_message(chat_id=user_id, text=f"✅ Admin បានអនុម័តការ{msg_type}របស់អ្នកចំនួន ${amount:.2f}។\nសមតុល្យថ្មី: ${new_balance:.2f}")
        except Exception:
            pass
        
        await query.edit_message_text(text=f"✅ បានអនុម័ត\n\nលេខសម្គាល់: {tx_id}\nអ្នកប្រើ: @{user[1]}\nចំនួន: ${amount:.2f}")
    
    elif action == 'reject':
        update_transaction_status(tx_id, 'rejected')
        msg_type = "ដាក់ប្រាក់" if tx_type == 'deposit' else "ដកប្រាក់"
        try:
            await context.bot.send_message(chat_id=user_id, text=f"❌ Admin បានបដិសេធការ{msg_type}របស់អ្នកចំនួន ${amount:.2f}។")
        except Exception:
            pass
        
        await query.edit_message_text(text=f"❌ បានបដិសេធ\n\nលេខសម្គាល់: {tx_id}\nអ្នកប្រើ: @{user[1]}\nចំនួន: ${amount:.2f}")

# --- ADMIN CONTROL HANDLERS ---

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("👥 គ្រប់គ្រងអ្នកប្រើ (កែសម្រួល)", callback_data='admin_search')],
        [InlineKeyboardButton("📈 គ្រប់គ្រងវិនិយោគ", callback_data='admin_invest_control')],
        [InlineKeyboardButton("📢 ផ្ញើសារទាំងអស់ (Broadcast)", callback_data='admin_broadcast')],
        [InlineKeyboardButton("🔙 ត្រឡប់ក្រោយ", callback_data='back_menu')]
    ]
    if query:
        await query.message.edit_text("🛡️ **ផ្ទាំងគ្រប់គ្រងមេ**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

# --- INVESTMENT CONTROL SUB-MENU ---
async def admin_invest_control_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📊 មើលស្ថានភាពវិនិយោគ User", callback_data='inv_search_user')],
        [InlineKeyboardButton("⏹️ បញ្ឈប់វិនិយោគ (Refund Current Plan)", callback_data='inv_stop_user')],
        [InlineKeyboardButton("⏩ ខ្ទាត់ដំណាក់កាល (Unlock Level)", callback_data='inv_next_user')],
        [InlineKeyboardButton("✅ បញ្ចប់វិនិយោគដោយដៃ (Add Profit)", callback_data='inv_force_user')],
        [InlineKeyboardButton("🔙 ត្រឡប់ក្រោយ", callback_data='admin_panel')]
    ]
    
    text = ("📈 **គ្រប់គ្រងវិនិយោគ**\n\n"
            "ជ្រើសរើសសកម្មភាពដែលចង់ធ្វើ៖")
            
    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

# Handler to ask for User ID for investment actions
async def admin_invest_action_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action_map = {
        'inv_search_user': ('admin_get_inv_status', 'មើលស្ថានភាព'),
        'inv_stop_user': ('admin_stop_inv', 'បញ្ឈប់វិនិយោគ (Refund Current Plan)'),
        'inv_next_user': ('admin_next_inv', 'ខ្ទាត់ដំណាក់កាល'),
        'inv_force_user': ('admin_force_inv', 'បញ្ចប់វិនិយោគ')
    }
    
    action_code, action_name = action_map.get(query.data, ('unknown', 'Unknown'))
    context.user_data['admin_inv_action'] = action_code
    
    await query.message.edit_text(f"🔍 សូមបញ្ចូល **User ID** ដើម្បី **{action_name}**:", parse_mode='Markdown')
    return ADMIN_SELECT_USER

# Process the User ID and perform the investment action
async def admin_process_invest_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    action = context.user_data.get('admin_inv_action')
    
    try:
        user_id = int(user_input)
        user = get_user(user_id)
        if not user:
            await update.message.reply_text("❌ រកមិនឃើញ User ទេ។ សូមព្យាយាមម្តងទៀត។")
            return ADMIN_SELECT_USER
            
        current_level = user[6] if user[6] is not None else 1
        end_time_str = user[7]
        balance = user[5]
        
        # --- ACTION: GET STATUS ---
        if action == 'admin_get_inv_status':
            status_text = "ទំនេរ" if not end_time_str else f"កំពុងរត់ (បញ្ចប់ {end_time_str})"
            text = (f"📊 **ស្ថានភាពវិនិយោគ**\n\n"
                    f"User ID: {user_id}\n"
                    f"សមតុល្យ: ${balance:.2f}\n"
                    f"Level បច្ចុប្បន្ន: {current_level}\n"
                    f"ស្ថានភាព: {status_text}")
            await update.message.reply_text(text, parse_mode='Markdown', reply_markup=main_keyboard(True))
            
        # --- ACTION: STOP SPECIFIC PLAN (Refund) ---
        elif action == 'admin_stop_inv':
            if end_time_str:
                # Find the SPECIFIC plan the user is currently running
                plan = next((p for p in INVESTMENT_PLANS if p['level'] == current_level), None)
                
                if plan:
                    # Calculate refund for ONLY this specific plan
                    refund_amount = plan['cost'] # Just the cost, no profit
                    new_balance = balance + refund_amount
                    
                    # Update database
                    update_user_field(user_id, 'balance', new_balance)
                    update_user_field(user_id, 'investment_end_time', None)
                    
                    text = (f"✅ **បានបញ្ឈប់វិនិយោគ**\n\n"
                            f"User ID: {user_id}\n"
                            f"គម្រោងដែលបានបញ្ឈប់: Level {current_level}\n"
                            f"ប្រាក់ដើមត្រូវបានសង: ${refund_amount:.2f}\n"
                            f"សមតុល្យថ្មី: ${new_balance:.2f}\n"
                            f"ស្ថានភាព: ទំនេរ")
                else:
                    # Fallback if plan config not found
                    update_user_field(user_id, 'investment_end_time', None)
                    text = f"✅ បានបញ្ឈប់វិនិយោគសម្រាប់ User {user_id} រួចរាល់ (រកមិនឃើញតម្លៃ Plan សម្រាប់សង)។"
            else:
                text = f"ℹ️ User {user_id} មិនមានវិនិយោគកំពុងរត់ទេ។"
            await update.message.reply_text(text, parse_mode='Markdown', reply_markup=main_keyboard(True))
            
        # --- ACTION: UNLOCK NEXT LEVEL ---
        elif action == 'admin_next_inv':
            next_lvl = current_level + 1
            if next_lvl > len(INVESTMENT_PLANS):
                await update.message.reply_text("⚠️ User នេះស្ថិតនៅ Level ខ្ពស់បំផុតរួចទៅហើយ!", reply_markup=main_keyboard(True))
            else:
                update_user_field(user_id, 'current_plan_level', next_lvl)
                update_user_field(user_id, 'investment_end_time', None)
                text = f"✅ បានដំណើរការទៅ Level {next_lvl} សម្រាប់ User {user_id} រួចរាល់។"
                await update.message.reply_text(text, reply_markup=main_keyboard(True))
                
        # --- ACTION: FORCE COMPLETE (ADD PROFIT) ---
        elif action == 'admin_force_inv':
            if end_time_str:
                plan = next((p for p in INVESTMENT_PLANS if p['level'] == current_level), None)
                if plan:
                    profit = plan['cost'] * (plan['percent'] / 100)
                    total_return = plan['cost'] + profit
                    new_balance = balance + total_return
                    
                    update_user_field(user_id, 'balance', new_balance)
                    next_lvl = current_level + 1
                    update_user_field(user_id, 'current_plan_level', next_lvl if next_lvl <= len(INVESTMENT_PLANS) else current_level)
                    update_user_field(user_id, 'investment_end_time', None)
                    
                    text = (f"✅ បានបញ្ចប់វិនិយោគដោយដៃ!\n"
                            f"ប្រាក់ទទួលបាន: ${total_return:.2f}\n"
                            f"សមតុល្យថ្មី: ${new_balance:.2f}")
                else:
                    text = "❌ កំហុស៖ រកមិនឃើញគម្រោងទេ។"
            else:
                text = "ℹ️ User នេះមិនមានវិនិយោគកំពុងរត់ទេ។"
            await update.message.reply_text(text, reply_markup=main_keyboard(True))

        context.user_data.clear()
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ សូមបញ្ចូល User ID ជាលេខ។")
        return ADMIN_SELECT_USER

# --- ADMIN USER EDIT HANDLERS ---

async def admin_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("សូមផ្ញើ **User ID** ឬ **ឈ្មោះអ្នកប្រើ** ដើម្បីកែសម្រួលទិន្នន័យ:")
    return ADMIN_SELECT_USER

async def admin_select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if we are in investment action mode
    if context.user_data.get('admin_inv_action'):
        return await admin_process_invest_action(update, context)

    # Standard User Edit Flow
    search_term = update.message.text
    conn = sqlite3.connect('bank_bot.db')
    cursor = conn.cursor()
    
    try:
        if search_term.isdigit():
            cursor.execute("SELECT user_id, username, name FROM users WHERE user_id = ?", (int(search_term),))
        else:
            cursor.execute("SELECT user_id, username, name FROM users WHERE username LIKE ?", (f'%{search_term}%',))
        results = cursor.fetchall()
    except Exception:
        results = []
    finally:
        conn.close()

    if not results:
        await update.message.reply_text("រកមិនឃើញអ្នកប្រើទេ។ សូមព្យាយាមម្តងទៀត។")
        return ADMIN_SELECT_USER
    
    keyboard = []
    for r in results:
        keyboard.append([InlineKeyboardButton(f"ID: {r[0]} | {r[1]}", callback_data=f"edit_{r[0]}")])
    
    await update.message.reply_text("ជ្រើសរើសអ្នកប្រើដើម្បីកែសម្រួល:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_EDIT_FIELD

async def admin_choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.data.split('_')[1]
    context.user_data['edit_target_id'] = int(user_id)
    
    keyboard = [
        [InlineKeyboardButton("កែឈ្មោះ", callback_data='field_name'),
         InlineKeyboardButton("កែសមតុល្យ", callback_data='field_balance')],
        [InlineKeyboardButton("កែអាយុ", callback_data='field_age'),
         InlineKeyboardButton("កែទីកន្លែង", callback_data='field_living')]
    ]
    await query.message.edit_text(f"កំពុងកែ User ID: {user_id}។ សូមជ្រើសរើស៖", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_EDIT_VALUE

async def admin_input_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.split('_')[1]
    context.user_data['edit_field'] = field
    
    field_names = {'name': 'ឈ្មោះ', 'balance': 'សមតុល្យ', 'age': 'អាយុ', 'living': 'ទីកន្លែង'}
    await query.message.edit_text(f"សូមបញ្ចូល {field_names.get(field, field)} ថ្មី:")
    return ADMIN_EDIT_VALUE

async def admin_save_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text
    user_id = context.user_data.get('edit_target_id')
    field = context.user_data.get('edit_field')
    
    if field == 'balance':
        try:
            value = float(value)
        except:
            await update.message.reply_text("សមតុល្យត្រូវតែជាលេខ។")
            return ADMIN_EDIT_VALUE

    update_user_field(user_id, field, value)
    await update.message.reply_text(f"✅ បានធ្វើបច្ចុប្បន្នភាព {field} សម្រាប់ User {user_id}។", reply_markup=main_keyboard(True))
    context.user_data.clear()
    return ConversationHandler.END

# --- ADMIN BROADCAST HANDLERS ---

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ បោះបង់", callback_data='admin_panel')]]
    await query.message.edit_text(
        "📢 **ផ្ញើសារទាំងអស់**\n\n"
        "សូមផ្ញើសារដែលអ្នកចង់ប្រាស្រ័យទៅកាន់អ្នកប្រើទាំងអស់។\n"
        "អ្នកអាចផ្ញើអក្សរ, រូបភាព, ឬវីដេអូបាន។",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_BROADCAST_MSG

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    total = len(users)
    success = 0
    failed = 0
    
    status_msg = await update.message.reply_text(f"📢 កំពុងផ្ញើសារ...\nដំណើរការ: 0/{total}")
    
    for i, user_id in enumerate(users):
        try:
            await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
            success += 1
        except Forbidden:
            failed += 1
        except Exception:
            failed += 1
        
        if (i + 1) % 10 == 0:
            try:
                await status_msg.edit_text(f"📢 កំពុងផ្ញើសារ...\nដំណើរការ: {i+1}/{total}")
            except: pass

    await status_msg.edit_text(
        f"✅ **បានផ្ញើរួចរាល់!**\n\n"
        f"សរុប: {total}\n"
        f"ជោគជ័យ: {success}\n"
        f"បរាជ័យ: {failed}",
        parse_mode='Markdown'
    )
    
    return ConversationHandler.END

# --- MAIN ---

def main():
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()

    deposit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern='^deposit$')],
        states={
            DEPOSIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount)],
            DEPOSIT_PHOTO: [MessageHandler(filters.PHOTO, deposit_photo)],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern='^withdraw$')],
        states={
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            WITHDRAW_PHOTO: [MessageHandler(filters.PHOTO, withdraw_photo)],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    # Conversation for Admin User Edit
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_search_start, pattern='^admin_search$')],
        states={
            ADMIN_SELECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_select_user)],
            ADMIN_EDIT_FIELD: [CallbackQueryHandler(admin_choose_field, pattern=r'^edit_\d+')],
            ADMIN_EDIT_VALUE: [
                CallbackQueryHandler(admin_input_value, pattern=r'^field_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_save_value)
            ]
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    # Conversation for Admin Investment Control
    admin_inv_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_invest_action_start, pattern=r'^inv_(search|stop|next|force)_user$')],
        states={
            ADMIN_SELECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_process_invest_action)]
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern='^admin_broadcast$')],
        states={
            ADMIN_BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_broadcast_send)]
        },
        fallbacks=[CommandHandler('start', start)]
    )

    application.add_handler(CommandHandler("start", start))
    
    # General Menu Callbacks
    application.add_handler(CallbackQueryHandler(menu_callback, pattern='^(balance|profile|admin_panel|back_menu|invest_menu)$'))
    application.add_handler(CallbackQueryHandler(process_start_investment, pattern=r'^do_invest_'))
    application.add_handler(CallbackQueryHandler(admin_decision, pattern=r'^(approve|reject)_\d+'))
    
    # Admin Panel Navigation
    application.add_handler(CallbackQueryHandler(admin_invest_control_menu, pattern='^admin_invest_control$'))
    
    application.add_handler(deposit_conv)
    application.add_handler(withdraw_conv)
    application.add_handler(admin_conv)
    application.add_handler(admin_inv_conv)
    application.add_handler(broadcast_conv)

    print("Bot កំពុងដំណើរការ...")
    application.run_polling()

if __name__ == "__main__":
    main()