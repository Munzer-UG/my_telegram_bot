import sqlite3
from datetime import datetime

def init_db():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        points INTEGER DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        joined_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        phone TEXT,
        added_by INTEGER,
        added_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS gift_codes (
        code TEXT PRIMARY KEY,
        points INTEGER,
        used INTEGER DEFAULT 0,
        created_by INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS subscription_groups (
        group_id TEXT PRIMARY KEY
    )''')
    conn.commit()
    conn.close()

def add_user(user_id, username, name):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (id, username, name, joined_at) VALUES (?, ?, ?, ?)",
              (user_id, username, name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return {'id': user[0], 'username': user[1], 'name': user[2], 'points': user[3], 'referrals': user[4], 'joined_at': user[5]}
    return None

def add_session(session_id, phone, admin_id=0):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO sessions (session_id, phone, added_by, added_at) VALUES (?, ?, ?, ?)",
              (session_id, phone, admin_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def delete_session(session_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

def get_sessions():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM sessions")
    sessions = c.fetchall()
    conn.close()
    return sessions

def update_points(user_id, points):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET points = points + ? WHERE id = ?", (points, user_id))
    conn.commit()
    conn.close()

def add_referral(user_id, referrer_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET referrals = referrals + 1, points = points + 2 WHERE id = ?", (referrer_id,))
    conn.commit()
    conn.close()