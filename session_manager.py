import time
import pywhatkit as kit
import sqlite3
from datetime import datetime

active_sessions = {}

def start_session(phone, code):
    """بدء جلسة جديدة"""
    session_id = f"session_{phone}_{int(time.time())}"
    active_sessions[session_id] = {
        'phone': phone,
        'code': code,
        'active': True,
        'started': time.time()
    }
    return session_id

def stop_session(session_id):
    """إيقاف جلسة"""
    if session_id in active_sessions:
        active_sessions[session_id]['active'] = False
        del active_sessions[session_id]
        return True
    return False

def get_active_sessions():
    """الحصول على جميع الجلسات النشطة"""
    return list(active_sessions.keys())

def send_whatsapp_report(target, report_type, session_phone):
    """
    إرسال بلاغ عبر واتساب
    target: الرقم أو معرف المجموعة
    report_type: 'number' أو 'group'
    session_phone: رقم الجلسة المستخدمة
    """
    try:
        if report_type == 'number':
            # تبليغ رقم - إرسال رسالة للرقم
            kit.sendwhatmsg_instantly(
                phone_no=f"+{target}",
                message=f"⚠️ تم الإبلاغ عن هذا الرقم بسبب مخالفة السياسة.",
                wait_time=20,
                tab_close=True
            )
            return True
        elif report_type == 'group':
            # تبليغ مجموعة - إرسال رسالة للمجموعة
            kit.sendwhatmsg_to_group(
                group_id=target,
                message=f"⚠️ تم الإبلاغ عن هذه المجموعة بسبب مخالفة السياسة.",
                wait_time=20,
                tab_close=True
            )
            return True
        return False
    except Exception as e:
        print(f"❌ خطأ في الإرسال: {e}")
        return False

def report_target(target, report_type):
    """
    تنفيذ التبليغ عبر جميع الجلسات النشطة
    تعيد عدد الجلسات التي نجحت في الإرسال
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
            result = send_whatsapp_report(target, report_type, phone)
            if result:
                success_count += 1
                # تسجيل العملية في قاعدة البيانات
                log_report(target, report_type, session_id, 'success')
            else:
                failed_sessions.append(phone)
                log_report(target, report_type, session_id, 'failed')
        except Exception as e:
            failed_sessions.append(phone)
            log_report(target, report_type, session_id, f'error: {str(e)}')
    
    if success_count == 0:
        return 0, f"فشل الإرسال من جميع الجلسات. الجلسات الفاشلة: {', '.join(failed_sessions)}"
    
    return success_count, f"تم الإرسال بنجاح من {success_count} جلسة."

def log_report(target, report_type, session_id, status):
    """تسجيل عمليات التبليغ في قاعدة البيانات"""
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
