import time
import sqlite3
from datetime import datetime

active_sessions = {}

def start_session(phone, code):
    session_id = f"session_{phone}_{int(time.time())}"
    active_sessions[session_id] = {
        'phone': phone,
        'code': code,
        'active': True,
        'started': time.time()
    }
    return session_id

def stop_session(session_id):
    if session_id in active_sessions:
        del active_sessions[session_id]
        return True
    return False

def get_active_sessions():
    return list(active_sessions.keys())

def report_target(target, report_type):
    sessions = get_active_sessions()
    if not sessions:
        return 0, "لا توجد جلسات نشطة"
    
    success_count = 0
    for session_id in sessions:
        session = active_sessions.get(session_id)
        if session:
            print(f"✅ إرسال بلاغ من {session['phone']} إلى {target}")
            success_count += 1
            log_report(target, report_type, session_id, 'success')
    
    if success_count == 0:
        return 0, "فشل الإرسال"
    
    return success_count, f"تم الإرسال من {success_count} جلسة"

def log_report(target, report_type, session_id, status):
    try:
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS report_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target TEXT, report_type TEXT, session_id TEXT, status TEXT, reported_at TEXT
        )''')
        c.execute("INSERT INTO report_logs (target, report_type, session_id, status, reported_at) VALUES (?,?,?,?,?)",
                  (target, report_type, session_id, status, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except:
        pass
