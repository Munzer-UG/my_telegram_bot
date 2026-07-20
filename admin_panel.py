from functools import wraps
from flask import request, redirect, url_for, session
from config import ADMIN_IDS

# لا تغير أي شيء آخر، كل شيء يعمل بشكل مثالي
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session['user_id'] not in ADMIN_IDS:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

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