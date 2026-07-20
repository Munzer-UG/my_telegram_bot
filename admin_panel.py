from functools import wraps
from flask import request, redirect, url_for, session
from config import ADMIN_IDS

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session['user_id'] not in ADMIN_IDS:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated
