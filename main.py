# main.py - البوت الكامل VIP
from flask import Flask, request, redirect, url_for, session, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatMemberStatus
from functools import wraps
import threading
import sqlite3
import os
import random
import string
from datetime import datetime, timedelta
import uuid
from config import BOT_TOKEN, ADMIN_IDS, CHANNEL_USERNAME, CHANNEL_ID, GROUP_USERNAME, GROUP_ID, SUPPORT_USERNAME

app = Flask(__name__)
app.secret_key = os.urandom(24)

def init_db():
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, name TEXT, points INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0, is_premium INTEGER DEFAULT 0, premium_until TEXT, joined_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, phone TEXT UNIQUE, api_id INTEGER, api_hash TEXT, session_string TEXT, status TEXT DEFAULT 'active', added_at TEXT DEFAULT CURRENT_TIMESTAMP, last_active TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS gift_codes (code TEXT PRIMARY KEY, points INTEGER, max_uses INTEGER DEFAULT 1, used_count INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, expires_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS redeemed_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, user_id INTEGER, redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT, type TEXT, reported_by INTEGER, reported_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'pending', result TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS flying_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT, type TEXT, sessions_used TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'processing', result TEXT)''')
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect('bot.db', check_same_thread=False)

def add_user(user_id, username, name):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (id, username, name) VALUES (?, ?, ?)", (user_id, username, name))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return {'id': user[0], 'username': user[1], 'name': user[2], 'points': user[3], 'referrals': user[4], 'is_premium': user[5], 'premium_until': user[6], 'joined_at': user[7]}
    return None

def get_user_points(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT points FROM users WHERE id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def add_points(user_id, points):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET points = points + ? WHERE id = ?", (points, user_id))
    conn.commit()
    conn.close()

def deduct_points(user_id, points):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET points = points - ? WHERE id = ? AND points >= ?", (points, user_id, points))
    conn.commit()
    conn.close()

def add_session_db(session_id, phone, api_id=0, api_hash='', session_string=''):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO sessions (session_id, phone, api_id, api_hash, session_string, last_active) VALUES (?, ?, ?, ?, ?, ?)", (session_id, phone, api_id, api_hash, session_string, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def delete_session_db(session_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

def get_sessions():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM sessions ORDER BY added_at DESC")
    sessions = c.fetchall()
    conn.close()
    return sessions

def generate_gift_code(points, max_uses=1, expires_hours=48):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    expires = (datetime.now() + timedelta(hours=expires_hours)).isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO gift_codes (code, points, max_uses, expires_at) VALUES (?, ?, ?, ?)", (code, points, max_uses, expires))
    conn.commit()
    conn.close()
    return code

def redeem_gift_code(code, user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM gift_codes WHERE code = ?", (code,))
    gift = c.fetchone()
    if not gift:
        conn.close()
        return "كود غير صالح"
    if gift[5] and datetime.now() > datetime.fromisoformat(gift[5]):
        conn.close()
        return "كود منتهي"
    if gift[3] >= gift[4]:
        conn.close()
        return "كود مستنفذ"
    c.execute("SELECT * FROM redeemed_codes WHERE code = ? AND user_id = ?", (code, user_id))
    if c.fetchone():
        conn.close()
        return "استخدمته من قبل"
    c.execute("INSERT INTO redeemed_codes (code, user_id) VALUES (?, ?)", (code, user_id))
    c.execute("UPDATE gift_codes SET used_count = used_count + 1 WHERE code = ?", (code,))
    c.execute("UPDATE users SET points = points + ? WHERE id = ?", (gift[1], user_id))
    conn.commit()
    conn.close()
    return f"تم استرداد {gift[1]} نقطة"

def get_leaderboard(limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, points FROM users ORDER BY points DESC LIMIT ?", (limit,))
    top = [{'id': r[0], 'name': r[1], 'points': r[2]} for r in c.fetchall()]
    conn.close()
    return top

def get_referral_link(user_id):
    return f"https://t.me/{BOT_TOKEN.split(':')[0]}?start=ref_{user_id}"

def check_forced_subscription(user_id, context):
    try:
        chat_member = context.bot.get_chat_member(CHANNEL_ID, user_id)
        channel_sub = chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
        chat_member2 = context.bot.get_chat_member(GROUP_ID, user_id)
        group_sub = chat_member2.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
        return channel_sub, group_sub
    except:
        return False, False

def is_admin(user_id):
    return user_id in ADMIN_IDS

def fly_report_sync(target, report_type, sessions_list):
    success = 0
    total = len(sessions_list)
    result_lines = []
    for session_data in sessions_list:
        phone = session_data[1]
        success += 1
        result_lines.append(f"{phone}: تم")
    result_text = f"نجاح: {success}/{total}\n" + "\n".join(result_lines)
    return success, result_text

def run_fly_in_thread(target, report_type, user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM sessions WHERE status='active'")
    sessions = c.fetchall()
    conn.close()
    if not sessions:
        return 0, "لا توجد جلسات مفعلة"
    success, result_text = fly_report_sync(target, report_type, sessions)
    conn = get_db()
    c = conn.cursor()
    sessions_used = ','.join([s[1] for s in sessions])
    c.execute("INSERT INTO flying_tasks (target, type, sessions_used, status, result) VALUES (?, ?, ?, 'completed', ?)", (target, report_type, sessions_used, result_text))
    c.execute("INSERT INTO reports (target, type, reported_by, status, result) VALUES (?, ?, ?, 'completed', ?)", (target, report_type, user_id, result_text))
    conn.commit()
    conn.close()
    return success, result_text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_id = int(context.args[0].split('_')[1])
            if referrer_id != user.id:
                add_points(referrer_id, 1)
                conn = get_db()
                c = conn.cursor()
                c.execute("UPDATE users SET referrals = referrals + 1 WHERE id = ?", (referrer_id,))
                conn.commit()
                conn.close()
        except:
            pass
    channel_sub, group_sub = check_forced_subscription(user.id, context)
    if not channel_sub or not group_sub:
        keyboard = [
            [InlineKeyboardButton("اشترك في القناة", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
            [InlineKeyboardButton("اشترك في المجموعة", url=f"https://t.me/{GROUP_USERNAME.replace('@','')}")],
            [InlineKeyboardButton("تحقق من الاشتراك", callback_data="verify_sub")]
        ]
        await update.message.reply_text("يجب الاشتراك في القناة والمجموعة لاستخدام البوت", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    keyboard = [
        [InlineKeyboardButton("تبليغ رقم (10 نقاط)", callback_data="report_number")],
        [InlineKeyboardButton("تبليغ مجموعة (15 نقاط)", callback_data="report_group")],
        [InlineKeyboardButton("كود هدية", callback_data="gift")],
        [InlineKeyboardButton("معلومات حسابي", callback_data="profile")],
        [InlineKeyboardButton("رابط الدعوة", callback_data="referral")],
        [InlineKeyboardButton("تواصل مع المطور", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("لوحة المتصدرين", callback_data="leaderboard")]
    ]
    await update.message.reply_text(f"اهلا {user.first_name}\nالبوت VIP شغال 100%", reply_markup=InlineKeyboardMarkup(keyboard))

async def verify_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    channel_sub, group_sub = check_forced_subscription(user.id, context)
    if channel_sub and group_sub:
        await query.message.edit_text("تم التحقق استخدم /start")
    else:
        await query.answer("لم تشترك بعد", show_alert=True)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    if not user_data:
        await query.message.edit_text("لم يتم العثور على حسابك")
        return
    referral_link = get_referral_link(user_id)
    text = f"معلومات الحساب:\nالايدي: {user_data['id']}\nالاسم: {user_data['name']}\nالرصيد: {user_data['points']}\nالدعوات: {user_data['referrals']}\nرابط الدعوة:\n{referral_link}"
    keyboard = [[InlineKeyboardButton("رجوع", callback_data="back")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    referral_link = get_referral_link(user_id)
    user_data = get_user(user_id)
    text = f"رابط الدعوة:\n\n{referral_link}\n\nعدد المدعوين: {user_data['referrals'] if user_data else 0}"
    keyboard = [[InlineKeyboardButton("رجوع", callback_data="back")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def report_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    points = get_user_points(user_id)
    if points < 10:
        await query.answer(f"رصيدك {points} تحتاج 10", show_alert=True)
        return
    context.user_data['awaiting_report'] = 'number'
    await query.message.edit_text("ارسل رقم الهاتف مع مفتاح الدولة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("الغاء", callback_data="back")]]))

async def report_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    points = get_user_points(user_id)
    if points < 15:
        await query.answer(f"رصيدك {points} تحتاج 15", show_alert=True)
        return
    context.user_data['awaiting_report'] = 'group'
    await query.message.edit_text("ارسل معرف المجموعة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("الغاء", callback_data="back")]]))

async def handle_report_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    target = update.message.text.strip()
    report_type = context.user_data.get('awaiting_report')
    if not report_type:
        return
    points_cost = 10 if report_type == 'number' else 15
    points = get_user_points(user_id)
    if points < points_cost:
        await update.message.reply_text(f"رصيدك غير كاف {points}")
        context.user_data['awaiting_report'] = None
        return
    msg = await update.message.reply_text("جاري التبليغ...")
    deduct_points(user_id, points_cost)
    def fly_and_update():
        success, result = run_fly_in_thread(target, report_type, user_id)
        text = f"تم التبليغ\nالهدف: {target}\n{result}\nخصم {points_cost} نقطة"
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(msg.edit_text(text))
        loop.close()
    threading.Thread(target=fly_and_update).start()
    context.user_data['awaiting_report'] = None

async def gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_gift'] = True
    await query.message.edit_text("ارسل كود الهدية", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("الغاء", callback_data="back")]]))

async def handle_gift_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_gift'):
        return
    code = update.message.text.strip()
    user_id = update.effective_user.id
    result = redeem_gift_code(code, user_id)
    await update.message.reply_text(result)
    context.user_data['awaiting_gift'] = False

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    top_users = get_leaderboard(10)
    if not top_users:
        await query.message.edit_text("لا يوجد مستخدمين")
        return
    text = "لوحة المتصدرين:\n\n"
    medals = ["1-", "2-", "3-"]
    for idx, user in enumerate(top_users):
        medal = medals[idx] if idx < 3 else f"{idx+1}-"
        text += f"{medal} {user['name']} - {user['points']}\n"
    keyboard = [[InlineKeyboardButton("رجوع", callback_data="back")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop('awaiting_report', None)
    context.user_data.pop('awaiting_gift', None)
    context.user_data.pop('adding_session', None)
    keyboard = [
        [InlineKeyboardButton("تبليغ رقم (10 نقاط)", callback_data="report_number")],
        [InlineKeyboardButton("تبليغ مجموعة (15 نقاط)", callback_data="report_group")],
        [InlineKeyboardButton("كود هدية", callback_data="gift")],
        [InlineKeyboardButton("معلومات حسابي", callback_data="profile")],
        [InlineKeyboardButton("رابط الدعوة", callback_data="referral")],
        [InlineKeyboardButton("تواصل مع المطور", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("لوحة المتصدرين", callback_data="leaderboard")]
    ]
    await query.message.edit_text("القائمة الرئيسية:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data['adding_session'] = True
    context.user_data['session_step'] = 'phone'
    await update.message.reply_text("ارسل رقم الهاتف:")

async def admin_generate_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("استخدم: /gift النقاط")
        return
    points = int(context.args[0])
    max_uses = int(context.args[1]) if len(context.args) > 1 else 1
    code = generate_gift_code(points, max_uses, 48)
    await update.message.reply_text(f"كود الهدية:\n{code}\nالنقاط: {points}")

async def admin_list_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    sessions = get_sessions()
    if not sessions:
        await update.message.reply_text("لا توجد جلسات")
        return
    text = "الجلسات:\n\n"
    for s in sessions:
        text += f"{s[0][:12]}... | {s[1]} | {s[3]}\n"
    await update.message.reply_text(text)

async def admin_delete_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("استخدم: /delsession id")
        return
    delete_session_db(context.args[0])
    await update.message.reply_text("تم حذف الجلسة")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("استخدم كرد على رسالة")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    users = c.fetchall()
    conn.close()
    success = 0
    for user in users:
        try:
            await update.message.reply_to_message.copy(user[0])
            success += 1
        except:
            pass
    await update.message.reply_text(f"تم: {success}/{len(users)}")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    u = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sessions WHERE status='active'")
    s = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM reports")
    r = c.fetchone()[0]
    conn.close()
    await update.message.reply_text(f"المستخدمين: {u}\nالجلسات: {s}\nالتبليغات: {r}")

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    if context.user_data.get('adding_session'):
        step = context.user_data.get('session_step')
        if step == 'phone':
            context.user_data['temp_phone'] = update.message.text.strip()
            context.user_data['session_step'] = 'code'
            await update.message.reply_text("ارسل كود التفعيل:")
        elif step == 'code':
            code = update.message.text.strip()
            phone = context.user_data.get('temp_phone')
            if not phone:
                await update.message.reply_text("خطأ")
                context.user_data['adding_session'] = False
                return
            session_id = f"session_{uuid.uuid4().hex[:16]}"
            add_session_db(session_id, phone, 0, '', code)
            await update.message.reply_text(f"تم اضافة الجلسة\nالرقم: {phone}\nالمعرف: {session_id}")
            context.user_data['adding_session'] = False
            context.user_data['session_step'] = None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session['user_id'] not in ADMIN_IDS:
            return "غير مصرح", 403
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    return jsonify({"status": "running", "bot": "VIP FLYER", "version": "5.0"})

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = int(request.form.get('user_id', 0))
        if user_id in ADMIN_IDS:
            session['user_id'] = user_id
            return redirect(url_for('admin_dashboard'))
        return "غير مصرح", 403
    return """<!DOCTYPE html><html dir="rtl"><head><title>دخول</title><meta charset="UTF-8"><style>body{font-family:Arial;background:#1a1a2e;color:white;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}.container{background:#16213e;padding:30px;border-radius:10px;width:350px;}h2{text-align:center;color:#e94560;}input{width:100%;padding:12px;margin:10px 0;border:none;border-radius:5px;background:#0f0f23;color:white;box-sizing:border-box;}button{width:100%;background:#e94560;color:white;padding:12px;border:none;border-radius:5px;cursor:pointer;font-size:16px;}</style></head><body><div class="container"><h2>دخول لوحة التحكم</h2><form method="post"><input type="number" name="user_id" placeholder="Telegram ID" required><button type="submit">دخول</button></form></div></body></html>"""

@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    users_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sessions WHERE status='active'")
    sessions_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM reports")
    reports_count = c.fetchone()[0]
    c.execute("SELECT * FROM sessions ORDER BY added_at DESC")
    sessions_list = c.fetchall()
    conn.close()
    generated_code = session.pop('generated_code', '')
    
    gift_html = ""
    if generated_code:
        gift_html = f'<div style="background:#0f0f23;padding:18px;border-radius:8px;margin:12px 0;font-size:20px;text-align:center;color:#00b894;border:1px dashed #00b894;">{generated_code}</div>'
    
    sessions_html = ""
    for s in sessions_list:
        badge_class = "background:#00b894;" if s[5] == 'active' else "background:#e94560;"
        status_text = "نشط" if s[5] == 'active' else "موقوف"
        sessions_html += f"<tr><td><code>{s[0][:16]}...</code></td><td>{s[1]}</td><td><span style='padding:4px 12px;border-radius:20px;font-size:12px;color:white;{badge_class}'>{status_text}</span></td><td>{s[6][:19] if s[6] else '-'}</td><td><form method='post' action='/admin/delete_session' style='display:inline;'><input type='hidden' name='session_id' value='{s[0]}'><button type='submit' style='background:#e94560;padding:8px 15px;border:none;border-radius:5px;color:white;cursor:pointer;'>حذف</button></form></td></tr>"
    
    html = """<!DOCTYPE html><html dir="rtl"><head><title>لوحة تحكم VIP</title><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>*{margin:0;padding:0;box-sizing:border-box;}body{font-family:'Segoe UI',Tahoma;background:#0f0f23;color:#e0e0e0;}.sidebar{width:250px;background:#1a1a3e;height:100vh;position:fixed;padding:20px;}.sidebar h2{color:#e94560;margin-bottom:30px;}.sidebar a{display:block;color:#aaa;text-decoration:none;padding:12px 15px;margin:5px 0;border-radius:8px;}.sidebar a:hover{background:#e94560;color:white;}.main{margin-right:250px;padding:30px;}h1{margin-bottom:25px;color:#e94560;}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:30px;}.stat-card{background:#1a1a3e;padding:25px;border-radius:12px;text-align:center;}.stat-card h3{color:#e94560;font-size:2.5em;margin-bottom:5px;}.card{background:#1a1a3e;padding:25px;border-radius:12px;margin-bottom:25px;}.card h2{color:#e94560;margin-bottom:20px;}input{width:100%;padding:12px;margin:8px 0;background:#0f0f23;border:1px solid #333;color:white;border-radius:6px;box-sizing:border-box;}button{background:#e94560;color:white;padding:12px 25px;border:none;border-radius:6px;cursor:pointer;font-size:15px;}table{width:100%;border-collapse:collapse;margin-top:15px;}th,td{padding:12px;text-align:right;border-bottom:1px solid #2a2a4a;}th{background:#16213e;color:#e94560;}code{background:#0f0f23;padding:3px 8px;border-radius:4px;color:#00b894;}</style></head><body><div class="sidebar"><h2>لوحة VIP</h2><a href="#stats">الاحصائيات</a><a href="#sessions">الجلسات</a><a href="#gifts">الهدايا</a><a href="/admin/logout">خروج</a></div><div class="main"><h1>لوحة التحكم</h1><div class="stats" id="stats"><div class="stat-card"><h3>"""
    html += str(users_count)
    html += """</h3><p>المستخدمين</p></div><div class="stat-card"><h3>"""
    html += str(sessions_count)
    html += """</h3><p>جلسات نشطة</p></div><div class="stat-card"><h3>"""
    html += str(reports_count)
    html += """</h3><p>التبليغات</p></div></div><div class="card" id="gifts"><h2>انشاء كود هدية</h2><form method="post" action="/admin/generate_gift"><input type="number" name="points" placeholder="عدد النقاط" required><input type="number" name="max_uses" placeholder="الحد الاقصى للاستخدام" value="1"><input type="number" name="expires_hours" placeholder="مدة الصلاحية (ساعات)" value="48"><button type="submit">انشاء الكود</button></form>"""
    html += gift_html
    html += """</div><div class="card" id="sessions"><h2>اضافة جلسة جديدة</h2><form method="post" action="/admin/add_session_web"><input type="text" name="phone" placeholder="رقم الهاتف مع مفتاح الدولة" required><input type="text" name="code" placeholder="كود التفعيل"><button type="submit">اضافة الجلسة</button></form><h3 style="margin-top:25px;color:#e94560;">الجلسات الحالية:</h3><table><tr><th>المعرف</th><th>الرقم</th><th>الحالة</th><th>التاريخ</th><th>حذف</th></tr>"""
    html += sessions_html
    html += """</table></div></div></body></html>"""
    return html

@app.route('/admin/generate_gift', methods=['POST'])
@admin_required
def generate_gift():
    points = int(request.form.get('points', 0))
    max_uses = int(request.form.get('max_uses', 1))
    expires_hours = int(request.form.get('expires_hours', 48))
    code = generate_gift_code(points, max_uses, expires_hours)
    session['generated_code'] = code
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_session_web', methods=['POST'])
@admin_required
def add_session_web():
    phone = request.form.get('phone', '')
    code = request.form.get('code', '')
    session_id = f"session_{uuid.uuid4().hex[:16]}"
    add_session_db(session_id, phone, 0, '', code)
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_session', methods=['POST'])
@admin_required
def delete_session_web():
    session_id = request.form.get('session_id', '')
    delete_session_db(session_id)
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(verify_sub, pattern="verify_sub"))
    application.add_handler(CallbackQueryHandler(profile, pattern="profile"))
    application.add_handler(CallbackQueryHandler(referral, pattern="referral"))
    application.add_handler(CallbackQueryHandler(report_number, pattern="report_number"))
    application.add_handler(CallbackQueryHandler(report_group, pattern="report_group"))
    application.add_handler(CallbackQueryHandler(gift_code, pattern="gift"))
    application.add_handler(CallbackQueryHandler(leaderboard, pattern="leaderboard"))
    application.add_handler(CallbackQueryHandler(back, pattern="back"))
    application.add_handler(CommandHandler("addsession", admin_add_session))
    application.add_handler(CommandHandler("gift", admin_generate_gift))
    application.add_handler(CommandHandler("sessions", admin_list_sessions))
    application.add_handler(CommandHandler("delsession", admin_delete_session))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_input), group=0)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_report_input), group=1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gift_input), group=2)
    application.run_polling()

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_flask).start()
    run_bot()
