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
import asyncio
from config import BOT_TOKEN, ADMIN_IDS, SUPPORT_USERNAME

# استيراد Telethon للطيران
try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
    TELETHON_AVAILABLE = True
except:
    TELETHON_AVAILABLE = False
    print("⚠️ Telethon غير مثبت. ثبته: pip install telethon")

app = Flask(__name__)
app.secret_key = os.urandom(24)

# تخزين كلاينتات الجلسات في الذاكرة
active_clients = {}

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT, name TEXT,
        points INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0,
        joined_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY, phone TEXT UNIQUE,
        api_id INTEGER DEFAULT 0, api_hash TEXT DEFAULT '',
        session_string TEXT DEFAULT '', status TEXT DEFAULT 'active',
        added_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS gift_codes (
        code TEXT PRIMARY KEY, points INTEGER,
        used INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT,
        type TEXT, reported_by INTEGER,
        reported_at TEXT DEFAULT CURRENT_TIMESTAMP,
        result TEXT DEFAULT ''
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS fly_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT,
        type TEXT, total_sessions INTEGER,
        success INTEGER, failed INTEGER,
        details TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()

# ==================== HELPERS ====================
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
        return {'id': user[0], 'username': user[1], 'name': user[2], 'points': user[3], 'referrals': user[4], 'joined_at': user[5]}
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
    c.execute("INSERT OR REPLACE INTO sessions (session_id, phone, api_id, api_hash, session_string) VALUES (?, ?, ?, ?, ?)", (session_id, phone, api_id, api_hash, session_string))
    conn.commit()
    conn.close()

def delete_session_db(session_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    if session_id in active_clients:
        try:
            active_clients[session_id].disconnect()
        except:
            pass
        del active_clients[session_id]

def get_sessions():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM sessions WHERE status='active' ORDER BY added_at DESC")
    sessions = c.fetchall()
    conn.close()
    return sessions

def generate_gift_code(points):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO gift_codes (code, points) VALUES (?, ?)", (code, points))
    conn.commit()
    conn.close()
    return code

def redeem_gift_code(code, user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT points, used FROM gift_codes WHERE code = ?", (code,))
    gift = c.fetchone()
    if not gift:
        conn.close()
        return "❌ الكود غير صالح!"
    if gift[1] == 1:
        conn.close()
        return "⚠️ الكود مستخدم!"
    c.execute("UPDATE gift_codes SET used = 1 WHERE code = ?", (code,))
    c.execute("UPDATE users SET points = points + ? WHERE id = ?", (gift[0], user_id))
    conn.commit()
    conn.close()
    return f"✅ تم إضافة {gift[0]} نقطة!"

def get_leaderboard(limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, points FROM users ORDER BY points DESC LIMIT ?", (limit,))
    users = c.fetchall()
    conn.close()
    return [{'name': u[0], 'points': u[1]} for u in users]

def get_referral_link(user_id):
    return f"https://t.me/{BOT_TOKEN.split(':')[0]}?start=ref_{user_id}"

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ==================== نظام الطيران الحقيقي ====================
async def fly_single_session(session_data, target, report_type):
    """تطير الهدف بجلسة واحدة"""
    phone = session_data[1]
    session_string = session_data[4]
    api_id = session_data[2]
    api_hash = session_data[3]
    
    if not TELETHON_AVAILABLE:
        return phone, False, "Telethon غير مثبت"
    
    if not api_id or not api_hash:
        return phone, False, "ينقص API ID/Hash"
    
    try:
        if session_string:
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
        else:
            return phone, False, "لا توجد جلسة محفوظة"
        
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            return phone, False, "الجلسة منتهية"
        
        if report_type == 'number':
            # تبليغ رقم - نرسل ريبورت سبام
            try:
                entity = await client.get_entity(target)
                await client.send_message(entity, "spam")
                await client.send_message(entity, "spam")
                await client.report_peer(entity, reason="spam")
                result_msg = "✅ تم التبليغ"
                success = True
            except FloodWaitError as e:
                result_msg = f"⏳ انتظار {e.seconds} ثانية"
                success = False
            except Exception as e:
                # نحاول طريقة بديلة
                try:
                    await client.report_peer(target, reason="spam")
                    result_msg = "✅ تم (بديل)"
                    success = True
                except:
                    result_msg = f"❌ فشل"
                    success = False
        
        elif report_type == 'group':
            # تبليغ مجموعة
            try:
                entity = await client.get_entity(target)
                await client.send_message(entity, "spam report")
                await client.report_peer(entity, reason="spam")
                result_msg = "✅ تم التبليغ"
                success = True
            except Exception as e:
                try:
                    await client.report_peer(target, reason="spam")
                    result_msg = "✅ تم (بديل)"
                    success = True
                except:
                    result_msg = f"❌ فشل"
                    success = False
        
        await client.disconnect()
        return phone, success, result_msg
    
    except Exception as e:
        return phone, False, f"خطأ: {str(e)[:50]}"

async def fly_mass(target, report_type):
    """تطير الهدف بكل الجلسات"""
    sessions = get_sessions()
    if not sessions:
        return 0, 0, "لا توجد جلسات نشطة!"
    
    tasks = []
    for s in sessions:
        tasks.append(fly_single_session(s, target, report_type))
    
    results = await asyncio.gather(*tasks)
    
    success_count = sum(1 for r in results if r[1])
    failed_count = len(results) - success_count
    
    details = ""
    for phone, ok, msg in results:
        emoji = "✅" if ok else "❌"
        details += f"{emoji} {phone}: {msg}\n"
    
    # حفظ النتيجة
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO fly_results (target, type, total_sessions, success, failed, details) VALUES (?, ?, ?, ?, ?, ?)", (target, report_type, len(results), success_count, failed_count, details))
    c.execute("INSERT INTO reports (target, type, reported_by, result) VALUES (?, ?, ?, ?)", (target, report_type, 0, f"نجاح: {success_count}/{len(results)}"))
    conn.commit()
    conn.close()
    
    return success_count, failed_count, details

def run_fly_sync(target, report_type):
    """تشغيل الطيران بشكل متزامن"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    success, failed, details = loop.run_until_complete(fly_mass(target, report_type))
    loop.close()
    return success, failed, details

# ==================== KEYBOARDS ====================
def main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("📱 تبليغ رقم (10 نقاط)", callback_data="report_number")],
        [InlineKeyboardButton("👥 تبليغ مجموعة (15 نقاط)", callback_data="report_group")],
        [InlineKeyboardButton("🎁 كود هدية", callback_data="gift")],
        [InlineKeyboardButton("📊 معلومات حسابي", callback_data="profile")],
        [InlineKeyboardButton("🔗 رابط الدعوة", callback_data="referral")],
        [InlineKeyboardButton("💬 تواصل مع المطور", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("🏆 لوحة المتصدرين", callback_data="leaderboard")]
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("🔧 لوحة الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def back_only_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])

def back_to_admin_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للوحة الأدمن", callback_data="admin_panel")]])

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
    
    await update.message.reply_text(
        f"✅ أهلاً {user.first_name}!\n\n⭐ البوت VIP مع نظام الطيران\n✈️ يطير أرقام ومجموعات بكل الجلسات\n\nاختر من القائمة:",
        reply_markup=main_menu_keyboard(user.id)
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    if not user_data:
        await query.message.edit_text("⚠️ لم يتم العثور على حسابك", reply_markup=back_only_keyboard())
        return
    
    referral_link = get_referral_link(user_id)
    text = (
        f"📋 معلومات الحساب:\n"
        f"🆔 الايدي: <code>{user_data['id']}</code>\n"
        f"👤 الاسم: {user_data['name']}\n"
        f"⭐ الرصيد: {user_data['points']} نقطة\n"
        f"👥 الدعوات: {user_data['referrals']}\n"
        f"📅 تاريخ التسجيل: {user_data['joined_at']}\n\n"
        f"🔗 رابط الدعوة:\n<code>{referral_link}</code>"
    )
    await query.message.edit_text(text, reply_markup=back_only_keyboard(), parse_mode='HTML')

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
    await query.message.edit_text(text, reply_markup=back_only_keyboard(), parse_mode='HTML')

async def report_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    points = get_user_points(user_id)
    if points < 10:
        await query.answer(f"❌ رصيدك {points} نقطة فقط! تحتاج 10 نقاط", show_alert=True)
        return
    context.user_data['awaiting_input'] = 'report_number'
    await query.message.edit_text(
        "📱 أرسل الرقم للتبليغ (مع مفتاح الدولة):\nمثال: +249123456789",
        reply_markup=back_only_keyboard()
    )

async def report_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    points = get_user_points(user_id)
    if points < 15:
        await query.answer(f"❌ رصيدك {points} نقطة فقط! تحتاج 15 نقطة", show_alert=True)
        return
    context.user_data['awaiting_input'] = 'report_group'
    await query.message.edit_text(
        "👥 أرسل معرف المجموعة للتبليغ:\nمثال: @group",
        reply_markup=back_only_keyboard()
    )

async def gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_input'] = 'gift'
    await query.message.edit_text("🎁 أرسل كود الهدية:", reply_markup=back_only_keyboard())

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    top_users = get_leaderboard(10)
    if not top_users:
        await query.message.edit_text("🏆 لا يوجد مستخدمين!", reply_markup=back_only_keyboard())
        return
    text = "🏆 <b>لوحة المتصدرين:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for idx, user in enumerate(top_users):
        medal = medals[idx] if idx < 3 else f"{idx+1}."
        text += f"{medal} {user['name']} - ⭐ {user['points']} نقطة\n"
    await query.message.edit_text(text, reply_markup=back_only_keyboard(), parse_mode='HTML')

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop('awaiting_input', None)
    context.user_data.pop('admin_action', None)
    await query.message.edit_text("🔙 القائمة الرئيسية:", reply_markup=main_menu_keyboard(query.from_user.id))

# ==================== HANDLE TEXT INPUT ====================
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Admin actions
    admin_action = context.user_data.get('admin_action')
    if admin_action and is_admin(user_id):
        if admin_action == 'add_session':
            context.user_data['temp_phone'] = text
            context.user_data['admin_action'] = 'add_session_api_id'
            await update.message.reply_text("🔑 أرسل API ID:", reply_markup=back_to_admin_keyboard())
            return
        
        elif admin_action == 'add_session_api_id':
            try:
                api_id = int(text)
                context.user_data['temp_api_id'] = api_id
                context.user_data['admin_action'] = 'add_session_api_hash'
                await update.message.reply_text("🔑 أرسل API Hash:", reply_markup=back_to_admin_keyboard())
            except:
                await update.message.reply_text("❌ أرسل رقم صحيح!", reply_markup=back_to_admin_keyboard())
            return
        
        elif admin_action == 'add_session_api_hash':
            api_hash = text
            phone = context.user_data.get('temp_phone')
            api_id = context.user_data.get('temp_api_id')
            context.user_data['temp_api_hash'] = api_hash
            
            if TELETHON_AVAILABLE:
                try:
                    client = TelegramClient(f"sessions/{phone}", api_id, api_hash)
                    await client.connect()
                    sent = await client.send_code_request(phone)
                    context.user_data['temp_client'] = client
                    context.user_data['temp_phone_code_hash'] = sent.phone_code_hash
                    context.user_data['admin_action'] = 'add_session_code'
                    await update.message.reply_text("📱 أرسل كود التفعيل المرسل للرقم:", reply_markup=back_to_admin_keyboard())
                except Exception as e:
                    await update.message.reply_text(f"❌ خطأ: {str(e)}", reply_markup=back_to_admin_keyboard())
                    context.user_data['admin_action'] = None
            else:
                session_id = f"session_{uuid.uuid4().hex[:16]}"
                add_session_db(session_id, phone, api_id, api_hash, '')
                await update.message.reply_text(f"✅ تم إضافة الجلسة (بدون Telethon)\n📱 {phone}\n🆔 {session_id}", reply_markup=back_to_admin_keyboard())
                context.user_data['admin_action'] = None
            return
        
        elif admin_action == 'add_session_code':
            code = text
            client = context.user_data.get('temp_client')
            phone = context.user_data.get('temp_phone')
            api_id = context.user_data.get('temp_api_id')
            api_hash = context.user_data.get('temp_api_hash')
            phone_code_hash = context.user_data.get('temp_phone_code_hash')
            
            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                session_string = StringSession.save(client.session)
                session_id = f"session_{uuid.uuid4().hex[:16]}"
                add_session_db(session_id, phone, api_id, api_hash, session_string)
                await client.disconnect()
                await update.message.reply_text(f"✅ تم إضافة الجلسة بنجاح!\n📱 {phone}\n🆔 {session_id}", reply_markup=back_to_admin_keyboard())
            except SessionPasswordNeededError:
                context.user_data['admin_action'] = 'add_session_password'
                await update.message.reply_text("🔒 الحساب محمي بكلمة مرور. أرسل كلمة المرور:", reply_markup=back_to_admin_keyboard())
                return
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {str(e)}", reply_markup=back_to_admin_keyboard())
            
            context.user_data['admin_action'] = None
            return
        
        elif admin_action == 'add_session_password':
            password = text
            client = context.user_data.get('temp_client')
            phone = context.user_data.get('temp_phone')
            api_id = context.user_data.get('temp_api_id')
            api_hash = context.user_data.get('temp_api_hash')
            
            try:
                await client.sign_in(password=password)
                session_string = StringSession.save(client.session)
                session_id = f"session_{uuid.uuid4().hex[:16]}"
                add_session_db(session_id, phone, api_id, api_hash, session_string)
                await client.disconnect()
                await update.message.reply_text(f"✅ تم إضافة الجلسة بنجاح!\n📱 {phone}\n🆔 {session_id}", reply_markup=back_to_admin_keyboard())
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {str(e)}", reply_markup=back_to_admin_keyboard())
            
            context.user_data['admin_action'] = None
            return
        
        elif admin_action == 'delete_session':
            delete_session_db(text)
            await update.message.reply_text(f"✅ تم حذف الجلسة: {text}", reply_markup=back_to_admin_keyboard())
            context.user_data['admin_action'] = None
            return
        
        elif admin_action == 'gift':
            try:
                points = int(text)
                code = generate_gift_code(points)
                await update.message.reply_text(f"🎁 كود الهدية:\n<code>{code}</code>\n⭐ {points} نقطة", parse_mode='HTML', reply_markup=back_to_admin_keyboard())
            except:
                await update.message.reply_text("❌ أرسل رقم صحيح!", reply_markup=back_to_admin_keyboard())
            context.user_data['admin_action'] = None
            return
        
        elif admin_action == 'broadcast':
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT id FROM users")
            users = c.fetchall()
            conn.close()
            success = 0
            for user in users:
                try:
                    await context.bot.send_message(user[0], f"📨 {text}")
                    success += 1
                except:
                    pass
            await update.message.reply_text(f"✅ تم الإرسال لـ {success} مستخدم", reply_markup=back_to_admin_keyboard())
            context.user_data['admin_action'] = None
            return
    
    # User actions
    awaiting = context.user_data.get('awaiting_input')
    if awaiting:
        if awaiting in ['report_number', 'report_group']:
            report_type = 'number' if awaiting == 'report_number' else 'group'
            points_cost = 10 if report_type == 'number' else 15
            points = get_user_points(user_id)
            
            if points < points_cost:
                await update.message.reply_text("❌ رصيدك غير كاف!", reply_markup=back_only_keyboard())
                context.user_data['awaiting_input'] = None
                return
            
            deduct_points(user_id, points_cost)
            
            # رسالة انتظار
            wait_msg = await update.message.reply_text(f"🔄 جاري التبليغ عن {text}...\n✈️ استخدام كل الجلسات النشطة...")
            
            # تشغيل الطيران في ثريد منفصل
            def do_fly():
                success, failed, details = run_fly_sync(text, report_type)
                result_text = (
                    f"{'📱' if report_type == 'number' else '👥'} نتيجة التبليغ:\n"
                    f"🎯 الهدف: {text}\n"
                    f"✅ نجاح: {success}\n"
                    f"❌ فشل: {failed}\n"
                    f"⭐ خصم: {points_cost} نقطة\n\n"
                    f"📋 التفاصيل:\n{details}"
                )
                import asyncio as asc
                loop = asc.new_event_loop()
                asc.set_event_loop(loop)
                loop.run_until_complete(wait_msg.edit_text(result_text, reply_markup=back_only_keyboard()))
                loop.close()
                
                # إبلاغ الأدمن
                for admin_id in ADMIN_IDS:
                    try:
                        loop2 = asc.new_event_loop()
                        asc.set_event_loop(loop2)
                        loop2.run_until_complete(context.bot.send_message(admin_id, f"🚨 تبليغ {report_type}\nالهدف: {text}\nنجاح: {success}/{success+failed}"))
                        loop2.close()
                    except:
                        pass
            
            threading.Thread(target=do_fly).start()
            context.user_data['awaiting_input'] = None
        
        elif awaiting == 'gift':
            result = redeem_gift_code(text, user_id)
            await update.message.reply_text(result, reply_markup=back_only_keyboard())
            context.user_data['awaiting_input'] = None

# ==================== ADMIN PANEL ====================
async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    
    sessions = get_sessions()
    active_count = len(sessions)
    
    keyboard = [
        [InlineKeyboardButton("📱 إضافة جلسة", callback_data="admin_add_session")],
        [InlineKeyboardButton(f"📋 عرض الجلسات ({active_count})", callback_data="admin_list_sessions")],
        [InlineKeyboardButton("🗑️ حذف جلسة", callback_data="admin_delete_session")],
        [InlineKeyboardButton("🎁 إنشاء كود هدية", callback_data="admin_gift")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("📨 بث رسالة", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back")]
    ]
    await query.message.edit_text(
        f"🔧 <b>لوحة تحكم الأدمن</b>\n\n📱 الجلسات النشطة: {active_count}\n\nاختر الإجراء:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def admin_add_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data['admin_action'] = 'add_session'
    await query.message.edit_text(
        "📱 أرسل رقم الهاتف (مع مفتاح الدولة):\nمثال: 249123456789",
        reply_markup=back_to_admin_keyboard()
    )

async def admin_list_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    sessions = get_sessions()
    if not sessions:
        await query.message.edit_text("📱 لا توجد جلسات نشطة!", reply_markup=back_to_admin_keyboard())
        return
    text = f"📋 <b>الجلسات النشطة ({len(sessions)}):</b>\n\n"
    for s in sessions:
        text += f"🆔 <code>{s[0][:16]}...</code>\n📱 {s[1]}\n📅 {s[5]}\n\n"
    await query.message.edit_text(text, reply_markup=back_to_admin_keyboard(), parse_mode='HTML')

async def admin_delete_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data['admin_action'] = 'delete_session'
    await query.message.edit_text("🆔 أرسل معرف الجلسة المراد حذفها:", reply_markup=back_to_admin_keyboard())

async def admin_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data['admin_action'] = 'gift'
    await query.message.edit_text("🎁 أرسل عدد النقاط للكود:", reply_markup=back_to_admin_keyboard())

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sessions WHERE status='active'")
    total_sessions = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM reports")
    total_reports = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM fly_results")
    total_fly = c.fetchone()[0]
    conn.close()
    text = f"📊 <b>الإحصائيات:</b>\n\n👥 المستخدمين: {total_users}\n📱 الجلسات النشطة: {total_sessions}\n📋 التبليغات: {total_reports}\n✈️ عمليات الطيران: {total_fly}"
    await query.message.edit_text(text, reply_markup=back_to_admin_keyboard(), parse_mode='HTML')

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data['admin_action'] = 'broadcast'
    await query.message.edit_text("📨 أرسل الرسالة التي تريد بثها للجميع:", reply_markup=back_to_admin_keyboard())

# ==================== RUN ====================
def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel_handler))
    
    application.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    application.add_handler(CallbackQueryHandler(referral, pattern="^referral$"))
    application.add_handler(CallbackQueryHandler(report_number, pattern="^report_number$"))
    application.add_handler(CallbackQueryHandler(report_group, pattern="^report_group$"))
    application.add_handler(CallbackQueryHandler(gift_code, pattern="^gift$"))
    application.add_handler(CallbackQueryHandler(leaderboard, pattern="^leaderboard$"))
    application.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    application.add_handler(CallbackQueryHandler(admin_panel_handler, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_add_session, pattern="^admin_add_session$"))
    application.add_handler(CallbackQueryHandler(admin_list_sessions, pattern="^admin_list_sessions$"))
    application.add_handler(CallbackQueryHandler(admin_delete_session, pattern="^admin_delete_session$"))
    application.add_handler(CallbackQueryHandler(admin_gift, pattern="^admin_gift$"))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    
    application.run_polling()

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_flask).start()
    run_bot()