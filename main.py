from flask import Flask, render_template, request, redirect, url_for, session
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import threading
import sqlite3
import os
import random
import string
from datetime import datetime
from config import BOT_TOKEN, ADMIN_IDS, CHANNEL_LINK, GROUP_LINK, SUPPORT_USERNAME
from database import init_db, add_session, delete_session, get_sessions, add_user, get_user
from points_system import generate_gift_code, redeem_gift_code, get_leaderboard
from session_manager import start_session, stop_session, get_active_sessions, report_target
from admin_panel import admin_required

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route('/')
def home():
    return "✅ البوت شغال 100%!"

# ==================== دوال مساعدة ====================
def get_user_points(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT points FROM users WHERE id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def deduct_points(user_id, points):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET points = points - ? WHERE id = ?", (points, user_id))
    conn.commit()
    conn.close()

def get_referral_link(user_id):
    return f"https://t.me/{(BOT_TOKEN.split(':')[0])}?start=ref_{user_id}"

# ==================== TELEGRAM BOT HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    if context.args and context.args[0].startswith('ref_'):
        referrer_id = int(context.args[0].split('_')[1])
        if referrer_id != user.id:
            conn = sqlite3.connect('bot.db')
            c = conn.cursor()
            c.execute("UPDATE users SET referrals = referrals + 1, points = points + 1 WHERE id = ?", (referrer_id,))
            conn.commit()
            conn.close()
            await update.message.reply_text("✅ تمت الدعوة بنجاح! حصل المدعو على نقطة.")
    
    keyboard = [
        [InlineKeyboardButton("📢 اشترك في القناة", url=CHANNEL_LINK)],
        [InlineKeyboardButton("👥 اشترك في المجموعة", url=GROUP_LINK)],
        [InlineKeyboardButton("📱 تبليغ رقم (10 نقاط)", callback_data="report_number")],
        [InlineKeyboardButton("👥 تبليغ مجموعة (15 نقاط)", callback_data="report_group")],
        [InlineKeyboardButton("🎁 كود هدية", callback_data="gift")],
        [InlineKeyboardButton("📊 معلومات حسابي", callback_data="profile")],
        [InlineKeyboardButton("🔗 رابط الدعوة", callback_data="referral")],
        [InlineKeyboardButton("💬 تواصل مع المطور", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("🏆 لوحة الأداء", callback_data="leaderboard")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"مرحباً {user.first_name}!\n"
        "👋 أهلاً بك في البوت الأسطوري VIP!\n\n"
        "📌 اشترك في القناة والمجموعة لتفعيل البوت.\n"
        "⭐ استخدم الأزرار أدناه للتنقل.",
        reply_markup=reply_markup
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    if not user_data:
        await query.message.edit_text("⚠️ لم يتم العثور على حسابك")
        return
    
    referral_link = get_referral_link(user_id)
    
    text = (f"📋 معلومات الحساب:\n"
            f"🆔 الايدي: {user_data['id']}\n"
            f"👤 الاسم: {user_data['name']}\n"
            f"⭐ الرصيد: {user_data['points']} نقطة\n"
            f"🔗 الدعوات: {user_data['referrals']}\n"
            f"📅 تاريخ التسجيل: {user_data['joined_at']}\n\n"
            f"🔗 رابط الدعوة:\n{referral_link}")
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    referral_link = get_referral_link(user_id)
    user_data = get_user(user_id)
    
    text = (f"🔗 رابط الدعوة الخاص بك:\n\n"
            f"{referral_link}\n\n"
            f"📌 كل صديق يسجل عبر رابطك تحصل على نقطة!\n"
            f"👥 عدد المدعوين: {user_data['referrals'] if user_data else 0}")
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

async def report_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    points = get_user_points(user_id)
    if points < 10:
        await query.message.edit_text(
            f"❌ رصيدك غير كافٍ!\n⭐ رصيدك: {points} نقطة\n📱 تحتاج 10 نقاط.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
        )
        return
    
    context.user_data['report_type'] = 'number'
    await query.message.edit_text(
        "📱 أرسل الرقم (مثال: 966501234567):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
    )

async def report_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    points = get_user_points(user_id)
    if points < 15:
        await query.message.edit_text(
            f"❌ رصيدك غير كافٍ!\n⭐ رصيدك: {points} نقطة\n👥 تحتاج 15 نقطة.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
        )
        return
    
    context.user_data['report_type'] = 'group'
    await query.message.edit_text(
        "👥 أرسل معرف المجموعة (مثال: @group):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
    )

async def handle_report_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    target = update.message.text.strip()
    report_type = context.user_data.get('report_type')
    
    if not report_type:
        return
    
    points_cost = 10 if report_type == 'number' else 15
    points = get_user_points(user_id)
    if points < points_cost:
        await update.message.reply_text("❌ رصيدك غير كافٍ!")
        return
    
    deduct_points(user_id, points_cost)
    success_count, message = report_target(target, report_type)
    
    if success_count == 0:
        await update.message.reply_text(f"❌ فشل التبليغ!\n{message}")
        return
    
    await update.message.reply_text(
        f"✅ تم تبليغ {target} بنجاح!\n"
        f"📊 {message}\n"
        f"⭐ تم خصم {points_cost} نقطة."
    )
    context.user_data['report_type'] = None

async def gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "🎁 أرسل كود الهدية:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
    )

async def handle_gift_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user_id = update.effective_user.id
    result = redeem_gift_code(code, user_id)
    await update.message.reply_text(result)

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    top_users = get_leaderboard(10)
    if not top_users:
        await query.message.edit_text("لا يوجد مستخدمين.")
        return
    text = "🏆 لوحة المتصدرين:\n\n"
    for idx, user in enumerate(top_users, 1):
        text += f"{idx}. {user['name']} - ⭐ {user['points']} نقطة\n"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📢 اشترك في القناة", url=CHANNEL_LINK)],
        [InlineKeyboardButton("👥 اشترك في المجموعة", url=GROUP_LINK)],
        [InlineKeyboardButton("📱 تبليغ رقم (10 نقاط)", callback_data="report_number")],
        [InlineKeyboardButton("👥 تبليغ مجموعة (15 نقاط)", callback_data="report_group")],
        [InlineKeyboardButton("🎁 كود هدية", callback_data="gift")],
        [InlineKeyboardButton("📊 معلومات حسابي", callback_data="profile")],
        [InlineKeyboardButton("🔗 رابط الدعوة", callback_data="referral")],
        [InlineKeyboardButton("💬 تواصل مع المطور", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("🏆 لوحة الأداء", callback_data="leaderboard")]
    ]
    await query.message.edit_text(
        "🔙 القائمة الرئيسية:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def session_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ غير مصرح لك.")
        return
    await update.message.reply_text("📱 أرسل رقم الهاتف:")

async def handle_session_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    phone = update.message.text.strip()
    context.user_data['temp_phone'] = phone
    await update.message.reply_text("🔑 أرسل كود التفعيل:")

async def handle_session_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    code = update.message.text.strip()
    phone = context.user_data.get('temp_phone')
    if not phone:
        await update.message.reply_text("⚠️ أعد إرسال الرقم.")
        return
    
    session_id = start_session(phone, code)
    if session_id:
        add_session(session_id, phone)
        await update.message.reply_text(f"✅ تم إضافة الجلسة: {phone}")
    else:
        await update.message.reply_text("❌ فشل في إضافة الجلسة.")

# ==================== ADMIN PANEL ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if int(request.form['user_id']) in ADMIN_IDS:
            session['user_id'] = int(request.form['user_id'])
            return redirect(url_for('admin'))
    return '''
        <form method="post">
            <input type="text" name="user_id" placeholder="Telegram ID">
            <button type="submit">دخول</button>
        </form>
    '''

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_session':
            phone = request.form['phone']
            code = request.form['code']
            session_id = start_session(phone, code)
            if session_id:
                add_session(session_id, phone)
        elif action == 'delete_session':
            session_id = request.form['session_id']
            delete_session(session_id)
            stop_session(session_id)
        elif action == 'generate_gift':
            points = int(request.form['points'])
            code = generate_gift_code(points)
            return f"🎁 كود الهدية: {code} (نقاط: {points})"
    sessions = get_sessions()
    return render_template('admin.html', sessions=sessions)

# ==================== RUN ====================

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(back, pattern="back"))
    application.add_handler(CallbackQueryHandler(profile, pattern="profile"))
    application.add_handler(CallbackQueryHandler(referral, pattern="referral"))
    application.add_handler(CallbackQueryHandler(report_number, pattern="report_number"))
    application.add_handler(CallbackQueryHandler(report_group, pattern="report_group"))
    application.add_handler(CallbackQueryHandler(gift_code, pattern="gift"))
    application.add_handler(CallbackQueryHandler(leaderboard, pattern="leaderboard"))
    application.add_handler(CommandHandler("addsession", session_add))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_session_number))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_session_code))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_report_input))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gift_input))
    application.run_polling()

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_flask).start()
    run_bot()
