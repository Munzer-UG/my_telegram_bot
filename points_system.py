import random
import string
import sqlite3

def generate_gift_code(points, admin_id=0):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO gift_codes (code, points, created_by) VALUES (?, ?, ?)", (code, points, admin_id))
    conn.commit()
    conn.close()
    return code

def redeem_gift_code(code, user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT points, used FROM gift_codes WHERE code = ?", (code,))
    result = c.fetchone()
    if not result:
        conn.close()
        return "❌ كود غير صالح."
    if result[1] == 1:
        conn.close()
        return "⚠️ هذا الكود مستخدم بالفعل."
    points = result[0]
    c.execute("UPDATE gift_codes SET used = 1 WHERE code = ?", (code,))
    c.execute("UPDATE users SET points = points + ? WHERE id = ?", (points, user_id))
    conn.commit()
    conn.close()
    return f"✅ تم إضافة {points} نقطة إلى رصيدك!"

def get_leaderboard(limit=10):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT name, points FROM users ORDER BY points DESC LIMIT ?", (limit,))
    users = c.fetchall()
    conn.close()
    return [{'name': u[0], 'points': u[1]} for u in users]