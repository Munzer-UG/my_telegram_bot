# main.py - الكود الأساسي للبوت
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
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

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        points INTEGER DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        is_premium INTEGER DEFAULT 0,
        premium_until TEXT,
        joined_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        phone TEXT UNIQUE,
        status TEXT DEFAULT 'active',
        added_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_active TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS gift_codes (
        code TEXT PRIMARY KEY,
        points INTEGER,
        max_uses INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS redeemed_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT,
        user_id INTEGER,
        redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT,
        type TEXT,
        reported_by INTEGER,
        reported_at TEXT DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending'
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS forced_subs (
        user_id INTEGER,
        channel_sub INTEGER DEFAULT 0,
        group_sub INTEGER DEFAULT 0,
        PRIMARY KEY (user_id)
    )''')
    
    conn.commit()
    conn.close()

# ==================== HELPERS ====================
def get_db():
    return sqlite3.connect('bot.db', check_same_thread=False)

def add_user(user_id, username, name):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (id, username, name) VALUES (?, ?, ?)", 
              (user_id, username, name))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return {
            'id': user[0],
            'username': user[1],
            'name': user[2],
            'points': user[3],
            'referrals': user[4],
            'is_premium': user[5],
            'premium_until': user[6],
            'joined_at': user[7]
        }
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
    c.execute("UPDATE users SET points = points - ? WHERE id = ? AND points >= ?", 
              (points, user_id, points))
    conn.commit()
    conn.close()

def add_session_db(session_id, phone):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO sessions (session_id, phone, last_active) VALUES (?, ?, ?)", 
              (session_id, phone, datetime.now().isoformat()))
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
    c.execute("INSERT INTO gift_codes (code, points, max_uses, expires_at) VALUES (?, ?, ?, ?)", 
              (code, points, max_uses, expires))
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
        return "❌ الكود غير صالح!"
    
    if gift[5] and datetime.now() > datetime.fromisoformat(gift[5]):
        conn.close()
        return "❌ الكود منتهي الصلاحية!"
    
    if gift[3] >= gift[4]:
        conn.close()
        return "❌ الكود مستنفذ!"
    
    c.execute("SELECT * FROM redeemed_codes WHERE code = ? AND user_id = ?", (code, user_id))
    if c.fetchone():
        conn.close()
        return "❌ لقد استخدمت هذا الكود مسبقاً!"
    
    c.execute("INSERT INTO redeemed_codes (code, user_id) VALUES (?, ?)", (code, user_id))
    c.execute("UPDATE gift_codes SET used_count = used_count + 1 WHERE code = ?", (code,))
    c.execute("UPDATE users SET points = points + ? WHERE id = ?", (gift[1], user_id))
    conn.commit()
    conn.close()
    return f"✅ تم استرداد الكود! حصلت على ⭐ {gift[1]} نقطة"

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

# ==================== BOT HANDLERS ====================
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
            [InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
            [InlineKeyboardButton("👥 اشترك في المجموعة", url=f"https://t.me/{GROUP_USERNAME.replace('@','')}")],
            [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="verify_sub")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ يجب الاشتراك في القناة والمجموعة لاستخدام البوت!\n\nاشترك ثم اضغط 'تحقق من الاشتراك'",
            reply_markup=reply_markup
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("📱 تبليغ رقم (10 نقاط)", callback_data="report_number")],
        [InlineKeyboardButton("👥 تبليغ مجموعة (15 نقاط)", callback_data="report_group")],
        [InlineKeyboardButton("🎁 كود هدية", callback_data="gift")],
        [InlineKeyboardButton("📊 معلومات حسابي", callback_data="profile")],
        [InlineKeyboardButton("🔗 رابط الدعوة", callback_data="referral")],
        [InlineKeyboardButton("💬 تواصل مع المطور", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("🏆 لوحة المتصدرين", callback_data="leaderboard")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"✅ أهلاً {user.first_name}!\n\n⭐ البوت VIP يعمل بكفاءة 100%\nاختر من القائمة:",
        reply_markup=reply_markup
    )

async def verify_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    
    channel_sub, group_sub = check_forced_subscription(user.id, context)
    
    if channel_sub and group_sub:
        await query.message.edit_text("✅ تم التحقق من الاشتراك!")
        keyboard = [
            [InlineKeyboardButton("📱 تبليغ رقم (10 نقاط)", callback_data="report_number")],
            [InlineKeyboardButton("👥 تبليغ مجموعة (15 نقاط)", callback_data="report_group")],
            [InlineKeyboardButton("🎁 كود هدية", callback_data="gift")],
            [InlineKeyboardButton("📊 معلومات حسابي", callback_data="profile")],
            [InlineKeyboardButton("🔗 رابط الدعوة", callback_data="referral")],
            [InlineKeyboardButton("💬 تواصل مع المطور", url=f"https://t.me/{SUPPORT_USERNAME}")],
            [InlineKeyboardButton("🏆 لوحة المتصدرين", callback_data="leaderboard")]
        ]
        await query.message.edit_text("القائمة الرئيسية:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.answer("❌ لم تشترك بعد! اشترك ثم حاول مجدداً", show_alert=True)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    if not user_data:
        await query.message.edit_text("⚠️ لم يتم العثور على حسابك")
        return
    
    referral_link = get_referral_link(user_id)
    
    text = (
        f"📋 معلومات الحساب:\n"
        f"🆔 الايدي: <code>{user_data['id']}</code>\n"
        f"👤 الاسم: {user_data['name']}\n"
        f"⭐ الرصيد: {user_data['points']} نقطة\n"
        f"👥 الدعوات: {user_data['referrals']}\n"
        f"💎 VIP: {'نعم' if user_data['is_premium'] else 'لا'}\n"
        f"📅 تاريخ التسجيل: {user_data['joined_at']}\n\n"
        f"🔗 رابط الدعوة:\n<code>{referral_link}</code>"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    referral_link = get_referral_link(user_id)
    user_data = get_user(user_id)
    
    text = (
        f"🔗 رابط الدعوة الخاص بك:\n\n"
        f"<code>{referral_link}</code>\n\n"
        f"📌 كل صديق يسجل تحصل على نقطة!\n"
        f"👥 عدد المدعوين: {user_data['referrals'] if user_data else 0}"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def report_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    points = get_user_points(user_id)
    if points < 10:
        await query.answer(f"❌ رصيدك {points} نقطة فقط! تحتاج 10 نقاط", show_alert=True)
        return
    
    context.user_data['awaiting_report'] = 'number'
    await query.message.edit_text(
        "📱 أرسل رقم الهاتف للتبليغ (مع مفتاح الدولة):\nمثال: 966501234567",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="back")]])
    )

async def report_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    points = get_user_points(user_id)
    if points < 15:
        await query.answer(f"❌ رصيدك {points} نقطة فقط! تحتاج 15 نقطة", show_alert=True)
        return
    
    context.user_data['awaiting_report'] = 'group'
    await query.message.edit_text(
        "👥 أرسل معرف/رابط المجموعة للتبليغ:\nمثال: @group أو https://t.me/group",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="back")]])
    )

async def handle_report_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    target = update.message.text.strip()
    report_type = context.user_data.get('awaiting_report')
    
    if not report_type:
        return
    
    points_cost = 10 if report_type == 'number' else 15
    points = get_user_points(user_id)
    
    if points < points_cost:
        await update.message.reply_text(f"❌ رصيدك غير كاف! لديك {points} نقطة فقط")
        context.user_data['awaiting_report'] = None
        return
    
    deduct_points(user_id, points_cost)
    
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO reports (target, type, reported_by) VALUES (?, ?, ?)", 
              (target, report_type, user_id))
    conn.commit()
    conn.close()
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🚨 تبليغ جديد!\n\nالنوع: {'رقم' if report_type == 'number' else 'مجموعة'}\nالهدف: {target}\nالمبلغ: {user_id}\nالتكلفة: {points_cost} نقطة"
            )
        except:
            pass
    
    await update.message.reply_text(
        f"✅ تم استلام التبليغ!\n🎯 الهدف: {target}\n⭐ تم خصم {points_cost} نقطة\n📊 سيتم معالجة التبليغ قريباً"
    )
    context.user_data['awaiting_report'] = None

async def gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_gift'] = True
    await query.message.edit_text(
        "🎁 أرسل كود الهدية:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="back")]])
    )

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
        await query.message.edit_text("🏆 لا يوجد مستخدمين بعد!")
        return
    
    text = "🏆 <b>لوحة المتصدرين:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for idx, user in enumerate(top_users):
        medal = medals[idx] if idx < 3 else f"{idx+1}."
        text += f"{medal} {user['name']} - ⭐ {user['points']} نقطة\n"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop('awaiting_report', None)
    context.user_data.pop('awaiting_gift', None)
    context.user_data.pop('adding_session', None)
    
    keyboard = [
        [InlineKeyboardButton("📱 تبليغ رقم (10 نقاط)", callback_data="report_number")],
        [InlineKeyboardButton("👥 تبليغ مجموعة (15 نقاط)", callback_data="report_group")],
        [InlineKeyboardButton("🎁 كود هدية", callback_data="gift")],
        [InlineKeyboardButton("📊 معلومات حسابي", callback_data="profile")],
        [InlineKeyboardButton("🔗 رابط الدعوة", callback_data="referral")],
        [InlineKeyboardButton("💬 تواصل مع المطور", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("🏆 لوحة المتصدرين", callback_data="leaderboard")]
    ]
    await query.message.edit_text("🔙 القائمة الرئيسية:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==================== ADMIN COMMANDS ====================
async def admin_add_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    context.user_data['adding_session'] = True
    context.user_data['session_step'] = 'phone'
    await update.message.reply_text("📱 أرسل رقم الهاتف (مع مفتاح الدولة):\nمثال: 249123456789")

async def admin_generate_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    if not context.args:
        await update.message.reply_text("❌ استخدم: /gift النقاط الحد_الأقصى_للاستخدام")
        return
    
    points = int(context.args[0])
    max_uses = int(context.args[1]) if len(context.args) > 1 else 1
    
    code = generate_gift_code(points, max_uses, 48)
    await update.message.reply_text(
        f"🎁 تم إنشاء كود الهدية:\n\n<code>{code}</code>\n\n⭐ النقاط: {points}\n👥 الحد الأقصى: {max_uses}\n⏰ صالح لمدة 48 ساعة",
        parse_mode='HTML'
    )

async def admin_list_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    sessions = get_sessions()
    if not sessions:
        await update.message.reply_text("📱 لا توجد جلسات مفعلة!")
        return
    
    text = "📱 <b>الجلسات المفعلة:</b>\n\n"
    for s in sessions:
        text += f"🆔 <code>{s[0][:12]}...</code>\n📱 {s[1]}\n📅 {s[3]}\n\n"
    
    await update.message.reply_text(text, parse_mode='HTML')

async def admin_delete_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    if not context.args:
        await update.message.reply_text("❌ استخدم: /delsession session_id")
        return
    
    session_id = context.args[0]
    delete_session_db(session_id)
    await update.message.reply_text(f"✅ تم حذف الجلسة: {session_id}")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ استخدم الأمر كرد على رسالة لإرسالها للجميع!")
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
    
    await update.message.reply_text(f"📊 تم الإرسال:\n✅ نجاح: {success}\n❌ فشل: {len(users) - success}")

async def admin_users_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sessions WHERE status='active'")
    active_sessions = c.fetchone()[0]
    conn.close()
    
    await update.message.reply_text(
        f"📊 <b>إحصائيات البوت:</b>\n\n👥 المستخدمين: {total_users}\n📱 الجلسات النشطة: {active_sessions}",
        parse_mode='HTML'
    )

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return
    
    if context.user_data.get('adding_session'):
        step = context.user_data.get('session_step')
        
        if step == 'phone':
            context.user_data['temp_phone'] = update.message.text.strip()
            context.user_data['session_step'] = 'code'
            await update.message.reply_text("🔑 أرسل كود التفعيل:")
        
        elif step == 'code':
            code = update.message.text.strip()
            phone = context.user_data.get('temp_phone')
            
            if not phone:
                await update.message.reply_text("❌ حدث خطأ! أعد المحاولة بـ /addsession")
                context.user_data['adding_session'] = False
                return
            
            session_id = f"session_{uuid.uuid4().hex[:16]}"
            add_session_db(session_id, phone)
            
            await update.message.reply_text(
                f"✅ تم إضافة الجلسة بنجاح!\n\n📱 الرقم: {phone}\n🆔 معرف الجلسة: <code>{session_id}</code>",
                parse_mode='HTML'
            )
            
            for admin_id in ADMIN_IDS:
                if admin_id != user_id:
                    try:
                        await context.bot.send_message(admin_id, f"📱 جلسة جديدة!\nالرقم: {phone}\nالمعرف: {session_id}")
                    except:
                        pass
            
            context.user_data['adding_session'] = False
            context.user_data['session_step'] = None

# ==================== FLASK ADMIN PANEL ====================
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
    return jsonify({"status": "running", "bot": "VIP BOT", "version": "3.0"})

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = int(request.form.get('user_id', 0))
        if user_id in ADMIN_IDS:
            session['user_id'] = user_id
            return redirect(url_for('admin_dashboard'))
        return "❌ غير مصرح!", 403
    
    return '''
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>تسجيل دخول الأدمن</title>
    <style>body{font-family:Arial;background:#1a1a2e;color:white;display:flex;justify-content:center;align-items:center;height:100vh;}.container{background:#16213e;padding:30px;border-radius:10px;}input{width:100%;padding:10px;margin:10px 0;border:none;border-radius:5px;}button{background:#e94560;color:white;padding:10px 20px;border:none;border-radius:5px;cursor:pointer;}</style>
    </head>
    <body><div class="container"><h2>دخول لوحة التحكم</h2>
    <form method="post"><input type="number" name="user_id" placeholder="Telegram ID" required><button type="submit">دخول</button></form></div></body></html>'''

@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sessions WHERE status='active'")
    active_sessions = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM reports WHERE status='pending'")
    pending_reports = c.fetchone()[0]
    c.execute("SELECT * FROM sessions ORDER BY added_at DESC")
    sessions_list = c.fetchall()
    conn.close()
    
    generated_code = session.pop('generated_code', None)
    
    html = f'''
    <!DOCTYPE html><html dir="rtl"><head><title>لوحة تحكم البوت VIP</title><meta charset="UTF-8">
    <style>*{{margin:0;padding:0;box-sizing:border-box;}}body{{font-family:'Segoe UI',Tahoma;background:#0f0f23;color:#e0e0e0;}}.sidebar{{width:250px;background:#1a1a3e;height:100vh;position:fixed;padding:20px;}}.sidebar h2{{color:#e94560;margin-bottom:30px;}}.sidebar a{{display:block;color:#aaa;text-decoration:none;padding:10px;margin:5px 0;border-radius:5px;}}.sidebar a:hover{{background:#e94560;color:white;}}.main{{margin-right:250px;padding:30px;}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:30px;}}.stat-card{{background:#1a1a3e;padding:20px;border-radius:10px;text-align:center;}}.stat-card h3{{color:#e94560;font-size:2em;}}.card{{background:#1a1a3e;padding:20px;border-radius:10px;margin-bottom:20px;}}input{{width:100%;padding:10px;margin:10px 0;background:#0f0f23;border:1px solid #333;color:white;border-radius:5px;}}button{{background:#e94560;color:white;padding:12px 30px;border:none;border-radius:5px;cursor:pointer;}}table{{width:100%;border-collapse:collapse;}}th,td{{padding:12px;text-align:right;border-bottom:1px solid #333;}}th{{background:#16213e;color:#e94560;}}.badge{{padding:5px 10px;border-radius:20px;font-size:12px;}}.badge-success{{background:#00b894;color:white;}}.gift-code{{background:#0f0f23;padding:15px;border-radius:5px;margin:10px 0;font-family:monospace;font-size:18px;text-align:center;color:#00b894;}}</style></head>
    <body><div class="sidebar"><h2>لوحة VIP</h2><a href="#sessions">إدارة الجلسات</a><a href="#gifts">أكواد الهدايا</a><a href="/admin/logout">خروج</a></div>
    <div class="main"><h1>لوحة التحكم الرئيسية</h1>
    <div class="stats"><div class="stat-card"><h3>{total_users}</h3><p>المستخدمين</p></div><div class="stat-card"><h3>{active_sessions}</h3><p>جلسات نشطة</p></div><div class="stat-card"><h3>{pending_reports}</h3><p>تبليغات معلقة</p></div></div>
    <div class="card" id="gifts"><h2>إنشاء كود هدية</h2><form method="post" action="/admin/generate_gift"><input type="number" name="points" placeholder="عدد النقاط" required><input type="number" name="max_uses" placeholder="الحد الأقصى للاستخدام" value="1"><input type="number" name="expires_hours" placeholder="مدة الصلاحية (ساعات)" value="48"><button type="submit">إنشاء الكود</button></form>'''
    
    if generated_code:
        html += f'<div class="gift-code">{generated_code}</div>'
    
    html += '</div><div class="card" id="sessions"><h2>إضافة جلسة جديدة</h2><form method="post" action="/admin/add_session"><input type="text" name="phone" placeholder="رقم الهاتف مع مفتاح الدولة" required><input type="text" name="code" placeholder="كود التفعيل" required><button type="submit">إضافة الجلسة</button></form><h3 style="margin-top:30px;">الجلسات الحالية:</h3><table><tr><th>المعرف</th><th>الرقم</th><th>الحالة</th><th>التاريخ</th><th>حذف</th></tr>'
    
    for s in sessions_list:
        badge = 'badge-success' if s[2]=='active' else ''
        html += f'<tr><td><code>{s[0][:12]}...</code></td><td>{s[1]}</td><td><span class="badge {badge}">{s[2]}</span></td><td>{s[3]}</td><td><form method="post" action="/admin/delete_session"><input type="hidden" name="session_id" value="{s[0]}"><button type="submit">حذف</button></form></td></tr>'
    
    html += '</table></div></div></body></html>'
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

@app.route('/admin/add_session', methods=['POST'])
@admin_required
def add_session_web():
    phone = request.form.get('phone', '')
    code = request.form.get('code', '')
    
    session_id = f"session_{uuid.uuid4().hex[:16]}"
    add_session_db(session_id, phone)
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

# ==================== MAIN ====================
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
    application.add_handler(CommandHandler("stats", admin_users_count))
    application.add_handler(MessageHandler(filters.TEXT & ~filters
