from flask import Flask, render_template, request, redirect, url_for, session
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import asyncio
import threading
import sqlite3
import json
import os
from config import BOT_TOKEN, ADMIN_IDS, HOST_URL
from database import init_db, add_session, delete_session, get_sessions, add_user, get_user, update_points, add_referral
from points_system import generate_gift_code, redeem_gift_code, get_leaderboard
from session_manager import start_session, stop_session, get_active_sessions
from admin_panel import admin_required, admin_dashboard

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ==================== TELEGRAM BOT HANDLERS ====================
from config import BOT_TOKEN, ADMIN_IDS, HOST_URL, CHANNEL_LINK, GROUP_LINK, SUPPORT_USERNAME

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("📢 اشترك في القناة", url=CHANNEL_LINK)],
        [InlineKeyboardButton("👥 اشترك في المجموعة", url=GROUP_LINK)],
        [InlineKeyboardButton("🎁 كود هدية", callback_data="gift")],
        [InlineKeyboardButton("📊 معلومات حسابي", callback_data="profile")],
        [InlineKeyboardButton("💬 تواصل مع المطور", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("🏆 لوحة الأداء", callback_data="leaderboard")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"مرحباً {user.first_name}!\n"
        "اشترك في القناة والمجموعة لتفعيل البوت بالكامل.\n"
        "استخدم الأزرار أدناه للتنقل.",
        reply_markup=reply_markup
    ))

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data:
        await update.callback_query.answer("⚠️ لم يتم العثور على حسابك")
        return
    
    text = (f"📋 معلومات الحساب:\n"
            f"🆔 الايدي: {user_data['id']}\n"
            f"👤 الاسم: {user_data['name']}\n"
            f"⭐ الرصيد: {user_data['points']} نقطة\n"
            f"🔗 الدعوات: {user_data['referrals']}\n"
            f"📅 تاريخ التسجيل: {user_data['joined_at']}")
    await update.callback_query.message.edit_text(text)

async def gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("📨 أرسل كود الهدية الآن:")

async def handle_gift_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user_id = update.effective_user.id
    result = redeem_gift_code(code, user_id)
    await update.message.reply_text(result)

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = get_leaderboard(10)
    if not top_users:
        await update.callback_query.message.reply_text("لا يوجد مستخدمين حتى الآن.")
        return
    text = "🏆 لوحة المتصدرين:\n\n"
    for idx, user in enumerate(top_users, 1):
        text += f"{idx}. {user['name']} - {user['points']} نقطة\n"
    await update.callback_query.message.edit_text(text)

async def session_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ غير مصرح لك.")
        return
    await update.message.reply_text("📱 أرسل رقم الهاتف (مثال: 966501234567):")

async def handle_session_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    phone = update.message.text.strip()
    context.user_data['temp_phone'] = phone
    await update.message.reply_text("🔑 أرسل كود التفعيل (من التطبيق):")

async def handle_session_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    code = update.message.text.strip()
    phone = context.user_data.get('temp_phone')
    if not phone:
        await update.message.reply_text("⚠️ أعد إرسال الرقم أولاً.")
        return
    
    session_id = start_session(phone, code)
    if session_id:
        add_session(session_id, phone)
        await update.message.reply_text(f"✅ تم إضافة الجلسة: {phone}")
    else:
        await update.message.reply_text("❌ فشل في إضافة الجلسة. تحقق من الرقم والكود.")

# ==================== ADMIN PANEL (WEB) ====================
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
        elif action == 'add_subscription_group':
            group_id = request.form['group_id']
            # Store in DB
            conn = sqlite3.connect('bot.db')
            c = conn.cursor()
            c.execute("INSERT INTO subscription_groups (group_id) VALUES (?)", (group_id,))
            conn.commit()
            conn.close()
    sessions = get_sessions()
    return render_template('admin.html', sessions=sessions)

# ==================== FLASK + TELEGRAM THREAD ====================
def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(profile, pattern="profile"))
    application.add_handler(CallbackQueryHandler(gift_code, pattern="gift"))
    application.add_handler(CallbackQueryHandler(leaderboard, pattern="leaderboard"))
    application.add_handler(CommandHandler("addsession", session_add))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_session_number))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_session_code))
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()