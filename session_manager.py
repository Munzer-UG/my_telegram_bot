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
        active_sessions[session_id]['active'] = False
        del active_sessions[session_id]
        return True
    return False

def get_active_sessions():
    return list(active_sessions.keys())

def report_target(target, report_type):
    """
    تنفيذ التبليغ عبر جميع الجلسات النشطة
    target: الرقم أو معرف المجموعة
    report_type: 'number' أو 'group'
    """
    sessions = get_active_sessions()
    if not sessions:
        return 0, "لا توجد جلسات نشطة"
    
    success_count = 0
    failed_sessions = []
    
    for session_id in sessions:
        session = active_sessions.get(session_id)
        if not session:
            continue
        
        phone = session.get('phone')
        if not phone:
            continue
        
        try:
            # محاكاة إرسال البلاغ
            print(f"✅ إرسال بلاغ من {phone} إلى {target} (نوع: {report_type})")
            success_count += 1
            log_report(target, report_type, session_id, 'success')
        except Exception as e:
            failed_sessions.append(phone)
            log_report(target, report_type, session_id, f'error: {str(e)}')
    
    if success_count == 0:
        return 0, f"فشل الإرسال من جميع الجلسات."
    
    return success_count, f"تم الإرسال بنجاح من {success_count} جلسة."

def log_report(target, report_type, session_id, status):
    """تسجيل عمليات التبليغ في قاعدة البيانات"""
    try:
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS report_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target TEXT,
            report_type TEXT,
            session_id TEXT,
            status TEXT,
            reported_at TEXT
        )''')
        c.execute("INSERT INTO report_logs (target, report_type, session_id, status, reported_at) VALUES (?, ?, ?, ?, ?)",
                  (target, report_type, session_id, status, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except:
        pass
