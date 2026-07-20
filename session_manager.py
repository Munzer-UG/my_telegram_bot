import time
import random

active_sessions = {}

def start_session(phone, code):
    # Simulate actual WhatsApp/session connection
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