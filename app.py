import os
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import json
import hashlib
import secrets
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-fallback-key-change-in-production')

DB_FILE = os.environ.get('DB_PATH', 'data/study_optimizer.db')
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        display_name TEXT,
        password_hash TEXT,
        salt TEXT,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS profiles (
        username TEXT PRIMARY KEY,
        name TEXT, year TEXT, semester TEXT, subjects TEXT, extras TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, task TEXT, type TEXT, subject TEXT,
        estimated REAL, actual TEXT DEFAULT '',
        priority TEXT DEFAULT 'Medium',
        recurring TEXT DEFAULT 'none',
        last_generated TEXT DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_plan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, date TEXT, task_id INTEGER,
        task_name TEXT, subject TEXT, estimated REAL,
        done INTEGER DEFAULT 0,
        actual REAL DEFAULT 0
    )''')
    conn.commit()

    # Migrate existing tables
    for col, default in [('priority', "'Medium'"), ('recurring', "'none'"), ('last_generated', "''")]:
        try:
            c.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT DEFAULT {default}")
            conn.commit()
        except:
            pass

    try:
        c.execute("ALTER TABLE daily_plan ADD COLUMN actual REAL DEFAULT 0")
        conn.commit()
    except:
        pass

    conn.close()

init_db()


# ===== AUTH HELPERS =====
def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return hashed, salt


def check_password(password, stored_hash, salt):
    hashed, _ = hash_password(password, salt)
    return hashed == stored_hash


def current_user():
    return session.get('username')


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ===== HELPERS =====
def get_greeting(name):
    hour = datetime.now().hour
    first = name.split()[0] if name and name.strip() else 'there'
    if hour < 12:
        return f"Good morning, {first}"
    elif hour < 17:
        return f"Good afternoon, {first}"
    else:
        return f"Good evening, {first}"


def generate_feedback(estimated, actual):
    try:
        estimated = float(estimated)
        actual = float(actual)
    except (ValueError, TypeError):
        return ""
    if estimated == 0:
        return "No estimate was set for this task."
    diff = actual - estimated
    pct = abs(diff) / estimated * 100
    if diff > 0:
        if pct > 50:
            return f"Underestimated by {round(diff,1)} hrs — this one was tough! Try breaking similar tasks into smaller chunks next time."
        elif pct > 20:
            return f"Underestimated by {round(diff,1)} hrs — you've got this! Push a bit harder and trust the process."
        else:
            return f"Just slightly over by {round(diff,1)} hrs — nearly there, keep refining your estimates!"
    elif diff < 0:
        if pct > 50:
            return f"Finished {round(abs(diff),1)} hrs early — outstanding efficiency! You might be setting your estimates too safe."
        elif pct > 20:
            return f"Finished {round(abs(diff),1)} hrs early — great job wrapping up fast! You're getting more efficient."
        else:
            return f"Just slightly under by {round(abs(diff),1)} hrs — solid work, almost a perfect estimate!"
    else:
        return "Spot on! Your estimate was perfect — excellent planning skills."


PRIORITY_ORDER = {'High': 0, 'Medium': 1, 'Low': 2}

def build_task_list(username):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE username=? ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 WHEN 'Low' THEN 2 ELSE 1 END, id",
        (username,)).fetchall()
    conn.close()
    task_list = []
    for i, row in enumerate(rows):
        actual = row['actual']
        is_complete = actual and str(actual).strip() != ''
        feedback = generate_feedback(row['estimated'], actual) if is_complete else ''
        task_list.append({
            'index': i, 'id': row['id'],
            'Task': row['task'], 'Type': row['type'],
            'Subject': row['subject'], 'Estimated': row['estimated'],
            'Actual': actual if is_complete else '',
            'is_complete': is_complete, 'feedback': feedback,
            'Priority': row['priority'] or 'Medium',
            'Recurring': row['recurring'] or 'none',
        })
    return task_list


def generate_recurring_tasks(username):
    """For recurring tasks, always ensure upcoming days are filled in the plan."""
    conn = get_db()

    recurring = conn.execute(
        "SELECT * FROM tasks WHERE username=? AND recurring != 'none' AND recurring IS NOT NULL",
        (username,)).fetchall()

    for task in recurring:
        recurring_type = task['recurring']

        if recurring_type == 'daily':
            targets = [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
        elif recurring_type == 'weekly':
            targets = [(datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')]
        else:
            continue

        for target in targets:
            already = conn.execute(
                "SELECT id FROM daily_plan WHERE username=? AND date=? AND task_id=?",
                (username, target, task['id'])).fetchone()

            if not already:
                conn.execute(
                    "INSERT INTO daily_plan (username, date, task_id, task_name, subject, estimated, done) VALUES (?,?,?,?,?,?,0)",
                    (username, target, task['id'], task['task'],
                     task['subject'], task['estimated']))

    conn.commit()
    conn.close()


# ===== ML =====
def get_productivity_data(username):
    today_str = datetime.now().strftime('%Y-%m-%d')
    conn = get_db()
    dates = conn.execute(
        'SELECT DISTINCT date FROM daily_plan WHERE username=? AND date<=? ORDER BY date',
        (username, today_str)).fetchall()
    real_data = []
    for d in dates:
        date = d['date']
        rows = conn.execute('SELECT * FROM daily_plan WHERE username=? AND date=?',
                            (username, date)).fetchall()
        total = len(rows)
        if total == 0:
            continue
        done = sum(1 for r in rows if r['done'] == 1)
        hours = sum(float(r['estimated'] or 0) for r in rows)
        completion_rate = done / total
        real_data.append({
            'date': date, 'num_tasks': total, 'total_hours': hours,
            'completion_rate': completion_rate,
            'label': 1 if completion_rate >= 0.7 else 0
        })
    conn.close()
    synthetic = [
        {'num_tasks': 5, 'total_hours': 6.0, 'completion_rate': 0.9, 'label': 1},
        {'num_tasks': 3, 'total_hours': 3.5, 'completion_rate': 1.0, 'label': 1},
        {'num_tasks': 6, 'total_hours': 8.0, 'completion_rate': 0.83, 'label': 1},
        {'num_tasks': 4, 'total_hours': 5.0, 'completion_rate': 0.75, 'label': 1},
        {'num_tasks': 2, 'total_hours': 2.0, 'completion_rate': 1.0, 'label': 1},
        {'num_tasks': 7, 'total_hours': 9.0, 'completion_rate': 0.71, 'label': 1},
        {'num_tasks': 3, 'total_hours': 4.0, 'completion_rate': 0.67, 'label': 0},
        {'num_tasks': 8, 'total_hours': 12.0, 'completion_rate': 0.5, 'label': 0},
        {'num_tasks': 6, 'total_hours': 10.0, 'completion_rate': 0.33, 'label': 0},
        {'num_tasks': 5, 'total_hours': 7.0, 'completion_rate': 0.4, 'label': 0},
        {'num_tasks': 9, 'total_hours': 11.0, 'completion_rate': 0.44, 'label': 0},
        {'num_tasks': 4, 'total_hours': 6.0, 'completion_rate': 0.25, 'label': 0},
        {'num_tasks': 2, 'total_hours': 3.0, 'completion_rate': 0.5, 'label': 0},
        {'num_tasks': 5, 'total_hours': 5.5, 'completion_rate': 0.8, 'label': 1},
        {'num_tasks': 4, 'total_hours': 4.5, 'completion_rate': 0.75, 'label': 1},
        {'num_tasks': 7, 'total_hours': 8.5, 'completion_rate': 0.57, 'label': 0},
        {'num_tasks': 3, 'total_hours': 2.5, 'completion_rate': 1.0, 'label': 1},
        {'num_tasks': 6, 'total_hours': 9.5, 'completion_rate': 0.33, 'label': 0},
        {'num_tasks': 4, 'total_hours': 5.0, 'completion_rate': 0.5, 'label': 0},
        {'num_tasks': 5, 'total_hours': 6.0, 'completion_rate': 0.8, 'label': 1},
    ]
    return real_data, synthetic


def predict_productivity(username, num_tasks, total_hours, done_today=0):
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        real_data, synthetic = get_productivity_data(username)
        if num_tasks > 0 and done_today > 0:
            today_completion = done_today / num_tasks
        elif real_data:
            today_str = datetime.now().strftime('%Y-%m-%d')
            past_only = [d for d in real_data if d['date'] < today_str]
            today_completion = sum(d['completion_rate'] for d in past_only) / len(past_only) if past_only else 0.7
        else:
            today_completion = 0.7
        all_data = synthetic + real_data
        X = [[d['num_tasks'], d['total_hours'], d['completion_rate']] for d in all_data]
        y = [d['label'] for d in all_data]
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = LogisticRegression(random_state=42)
        model.fit(X_scaled, y)
        today_scaled = scaler.transform([[num_tasks, total_hours, today_completion]])
        prediction = model.predict(today_scaled)[0]
        confidence = model.predict_proba(today_scaled)[0][prediction]
        return {
            'prediction': int(prediction),
            'confidence': round(confidence * 100),
            'past_completion': round(today_completion * 100),
            'label': 'High productivity day' if prediction == 1 else 'Challenging day ahead',
            'color': '#16a34a' if prediction == 1 else '#d97706',
            'bg': '#f0fdf4' if prediction == 1 else '#fffbeb',
        }
    except ImportError:
        score = done_today / num_tasks if num_tasks > 0 else 0.7
        return {
            'prediction': 1 if score >= 0.7 else 0,
            'confidence': round(score * 100),
            'past_completion': round(score * 100),
            'label': 'High productivity day' if score >= 0.7 else 'Challenging day ahead',
            'color': '#16a34a' if score >= 0.7 else '#d97706',
            'bg': '#f0fdf4' if score >= 0.7 else '#fffbeb',
        }


def get_productivity_chart_data(username):
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    real_data, _ = get_productivity_data(username)
    rate_by_date = {d['date']: d['completion_rate'] for d in real_data if d['date'] <= today_str}
    labels, values = [], []
    for i in range(13, -1, -1):
        d = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        labels.append((today - timedelta(days=i)).strftime('%d %b'))
        values.append(round(rate_by_date[d] * 100) if d in rate_by_date else None)
    return labels, values


# ===========================
# ===== AUTH ROUTES =====
# ===========================

@app.route('/')
def index():
    if current_user():
        return redirect(url_for('tasks'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user():
        return redirect(url_for('tasks'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        conn.close()
        if user and check_password(password, user['password_hash'], user['salt']):
            session['username'] = username
            session['display_name'] = user['display_name']
            return redirect(url_for('tasks'))
        else:
            error = 'Invalid username or password.'
    return render_template('login.html', error=error)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user():
        return redirect(url_for('tasks'))
    error = None
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not display_name or not username or not password:
            error = 'All fields are required.'
        elif len(username) < 3:
            error = 'Username must be at least 3 characters.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        elif password != confirm:
            error = 'Passwords do not match.'
        else:
            conn = get_db()
            existing = conn.execute('SELECT username FROM users WHERE username=?', (username,)).fetchone()
            if existing:
                error = 'Username already taken. Please choose another.'
                conn.close()
            else:
                password_hash, salt = hash_password(password)
                conn.execute(
                    'INSERT INTO users (username, display_name, password_hash, salt, created_at) VALUES (?,?,?,?,?)',
                    (username, display_name, password_hash, salt, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
                conn.close()
                session['username'] = username
                session['display_name'] = display_name
                return redirect(url_for('profile'))

    return render_template('signup.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ===========================
# ===== APP ROUTES =====
# ===========================

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    username = current_user()
    conn = get_db()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        year = request.form.get('year', '')
        semester = request.form.get('semester', '')
        subjects = request.form.get('subjects', '')
        extras = request.form.get('extras', '')

        existing = conn.execute('SELECT username FROM profiles WHERE username=?', (username,)).fetchone()
        if existing:
            conn.execute('UPDATE profiles SET name=?,year=?,semester=?,subjects=?,extras=? WHERE username=?',
                         (name, year, semester, subjects, extras, username))
        else:
            conn.execute('INSERT INTO profiles (username,name,year,semester,subjects,extras) VALUES (?,?,?,?,?,?)',
                         (username, name, year, semester, subjects, extras))
        conn.commit()
        conn.close()
        return redirect(url_for('tasks'))

    row = conn.execute('SELECT * FROM profiles WHERE username=?', (username,)).fetchone()
    conn.close()
    name = year = semester = subjects = extras = ''
    if row:
        name = row['name'] or ''
        year = row['year'] or ''
        semester = row['semester'] or ''
        subjects = row['subjects'] or ''
        extras = row['extras'] or ''

    return render_template('profile.html', name=name, year=year,
                           semester=semester, subjects=subjects, extras=extras)


@app.route('/tasks', methods=['GET', 'POST'])
@login_required
def tasks():
    username = current_user()

    # Generate any due recurring tasks
    generate_recurring_tasks(username)

    conn = get_db()
    prof = conn.execute('SELECT * FROM profiles WHERE username=?', (username,)).fetchone()
    profile_name = prof['name'] if prof else session.get('display_name', '')
    greeting = get_greeting(profile_name)

    user_subjects = []
    if prof and prof['subjects']:
        user_subjects = [s.strip() for s in prof['subjects'].split(',') if s.strip()]

    if request.method == 'POST':
        conn.execute(
            'INSERT INTO tasks (username,task,type,subject,estimated,actual,priority,recurring,last_generated) VALUES (?,?,?,?,?,?,?,?,?)',
            (username, request.form['task'], request.form['type'],
             request.form['subject'], request.form['estimated'], '',
             request.form.get('priority', 'Medium'),
             request.form.get('recurring', 'none'),
             datetime.now().strftime('%Y-%m-%d') if request.form.get('recurring', 'none') != 'none' else ''))
        conn.commit()

    today = datetime.now().strftime('%Y-%m-%d')
    today_plan = conn.execute('SELECT * FROM daily_plan WHERE username=? AND date=?',
                              (username, today)).fetchall()
    today_plan = [dict(r) for r in today_plan]

    # Recurring tasks with their plan entries per date
    recurring_tasks = [t for t in build_task_list(username) if t['Recurring'] != 'none']
    for t in recurring_tasks:
        entries = conn.execute(
            'SELECT * FROM daily_plan WHERE username=? AND task_id=? ORDER BY date',
            (username, t['id'])).fetchall()
        t['plan_entries'] = [dict(e) for e in entries]
        if t['Recurring'] == 'daily':
            t['upcoming'] = [(datetime.now() + timedelta(days=i)).strftime('%d %b') for i in range(7)]
        elif t['Recurring'] == 'weekly':
            t['upcoming'] = [(datetime.now() + timedelta(days=7)).strftime('%d %b')]

    conn.close()

    task_list = build_task_list(username)
    pending = [t for t in task_list if not t['is_complete']]
    completed = [t for t in task_list if t['is_complete']]

    return render_template('tasks.html',
                           tasks=task_list, pending=pending, completed=completed,
                           today_plan=today_plan, subjects=user_subjects,
                           profile_name=profile_name, greeting=greeting,
                           recurring_tasks=recurring_tasks)


@app.route('/remove_recurring/<int:task_id>', methods=['POST'])
@login_required
def remove_recurring(task_id):
    username = current_user()
    conn = get_db()
    # Remove all future plan entries for this task
    today = datetime.now().strftime('%Y-%m-%d')
    conn.execute('DELETE FROM daily_plan WHERE username=? AND task_id=? AND date>=?',
                 (username, task_id, today))
    # Remove the task itself
    conn.execute('DELETE FROM tasks WHERE id=? AND username=?', (task_id, username))
    conn.commit()
    conn.close()
    return redirect(url_for('tasks'))


@app.route('/update_plan_entry/<int:entry_id>', methods=['POST'])
@login_required
def update_plan_entry(entry_id):
    conn = get_db()
    actual = float(request.form.get('actual', 0))
    conn.execute('UPDATE daily_plan SET done=1, actual=? WHERE id=? AND username=?',
                 (actual, entry_id, current_user()))
    conn.commit()
    conn.close()
    return redirect(url_for('tasks'))


@app.route('/delete_task/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    username = current_user()
    conn = get_db()
    # Remove from all plans too
    conn.execute('DELETE FROM daily_plan WHERE username=? AND task_id=?', (username, task_id))
    conn.execute('DELETE FROM tasks WHERE id=? AND username=?', (task_id, username))
    conn.commit()
    conn.close()
    return redirect(url_for('tasks'))


@app.route('/edit_task/<int:task_id>', methods=['POST'])
@login_required
def edit_task(task_id):
    username = current_user()
    conn = get_db()
    conn.execute('''UPDATE tasks SET task=?, subject=?, type=?, estimated=?, priority=?
                    WHERE id=? AND username=?''',
                 (request.form['task'], request.form['subject'],
                  request.form['type'], request.form['estimated'],
                  request.form.get('priority', 'Medium'),
                  task_id, username))
    conn.commit()
    conn.close()
    return redirect(url_for('tasks'))



@login_required
def update_task(task_id):
    conn = get_db()
    conn.execute('UPDATE tasks SET actual=? WHERE id=? AND username=?',
                 (float(request.form['actual']), task_id, current_user()))
    conn.commit()
    conn.close()
    return redirect(url_for('tasks'))


@app.route('/clear', methods=['POST'])
@login_required
def clear_data():
    conn = get_db()
    conn.execute('DELETE FROM tasks WHERE username=?', (current_user(),))
    conn.commit()
    conn.close()
    return redirect(url_for('tasks'))


@app.route('/plan_add', methods=['POST'])
@login_required
def plan_add():
    username = current_user()
    date = request.form.get('date')
    task_id = request.form.get('task_id')
    conn = get_db()

    # Check if this specific task is already on this specific date
    already = conn.execute(
        'SELECT id FROM daily_plan WHERE username=? AND date=? AND task_id=?',
        (username, date, task_id)).fetchone()

    if not already:
        conn.execute(
            'INSERT INTO daily_plan (username,date,task_id,task_name,subject,estimated,done) VALUES (?,?,?,?,?,?,0)',
            (username, date, task_id,
             request.form.get('task_name', ''),
             request.form.get('subject', ''),
             request.form.get('estimated', 0)))
        conn.commit()
    conn.close()
    return redirect(url_for('plan', date=date))


@app.route('/plan_done/<date>/<int:task_id>')
@login_required
def plan_done(date, task_id):
    conn = get_db()
    conn.execute('UPDATE daily_plan SET done=1 WHERE username=? AND date=? AND task_id=?',
                 (current_user(), date, task_id))
    conn.commit()
    conn.close()
    return redirect(url_for('plan', date=date, just_done=task_id))


@app.route('/plan_undone/<date>/<int:task_id>')
@login_required
def plan_undone(date, task_id):
    conn = get_db()
    conn.execute('UPDATE daily_plan SET done=0 WHERE username=? AND date=? AND task_id=?',
                 (current_user(), date, task_id))
    conn.commit()
    conn.close()
    return redirect(url_for('plan', date=date))


@app.route('/plan_remove/<date>/<int:task_id>')
@login_required
def plan_remove(date, task_id):
    conn = get_db()
    conn.execute('DELETE FROM daily_plan WHERE username=? AND date=? AND task_id=?',
                 (current_user(), date, task_id))
    conn.commit()
    conn.close()
    return redirect(url_for('plan', date=date))


@app.route('/plan')
@login_required
def plan():
    username = current_user()
    generate_recurring_tasks(username)
    conn = get_db()
    prof = conn.execute('SELECT * FROM profiles WHERE username=?', (username,)).fetchone()
    profile_name = prof['name'] if prof else session.get('display_name', '')
    greeting = get_greeting(profile_name)
    today = datetime.now().strftime('%Y-%m-%d')

    selected_date = request.args.get('date', today)
    try:
        selected_dt = datetime.strptime(selected_date, '%Y-%m-%d')
    except ValueError:
        selected_date = today
        selected_dt = datetime.strptime(today, '%Y-%m-%d')

    selected_display = selected_dt.strftime('%A, %d %B %Y')
    is_today = selected_date == today
    is_future = selected_date > today
    just_done = request.args.get('just_done', '')

    selected_plan = conn.execute(
        '''SELECT dp.*, COALESCE(t.recurring, 'none') as recurring,
           COALESCE(t.priority, 'Medium') as priority
           FROM daily_plan dp
           LEFT JOIN tasks t ON dp.task_id = t.id
           WHERE dp.username=? AND dp.date=?''',
        (username, selected_date)).fetchall()
    selected_plan = [dict(r) for r in selected_plan]

    done_count = sum(1 for p in selected_plan if p['done'] == 1)
    total_hrs = sum(float(p['estimated'] or 0) for p in selected_plan)

    dates = conn.execute('SELECT DISTINCT date FROM daily_plan WHERE username=? ORDER BY date DESC',
                         (username,)).fetchall()
    history = []
    for d in dates:
        d = d['date']
        day_rows = conn.execute('SELECT * FROM daily_plan WHERE username=? AND date=?',
                                (username, d)).fetchall()
        day_done = sum(1 for r in day_rows if r['done'] == 1)
        try:
            d_display = datetime.strptime(d, '%Y-%m-%d').strftime('%d %b %Y')
        except:
            d_display = d
        history.append({
            'date': d, 'display': d_display,
            'total': len(day_rows), 'done': day_done,
            'is_selected': d == selected_date,
            'is_future': d > today,
        })

    productivity = None
    chart_labels, chart_values = [], []
    if is_today and len(selected_plan) > 0:
        productivity = predict_productivity(username, len(selected_plan), total_hrs, done_today=done_count)
        chart_labels, chart_values = get_productivity_chart_data(username)

    # For non-recurring: block if already planned on any day
    # For recurring: only block if already on THIS specific date
    all_planned = conn.execute(
        'SELECT dp.task_id, t.recurring FROM daily_plan dp '
        'LEFT JOIN tasks t ON dp.task_id = t.id '
        'WHERE dp.username=?', (username,)).fetchall()

    # Non-recurring tasks planned anywhere → block from all dates
    non_recurring_planned = [r['task_id'] for r in all_planned
                              if not r['recurring'] or r['recurring'] == 'none']
    # Tasks already on this specific date → block regardless
    date_planned_ids = [p['task_id'] for p in selected_plan]

    all_planned_ids = list(set(non_recurring_planned + date_planned_ids))

    task_list = build_task_list(username)
    pending = [t for t in task_list if not t['is_complete']]
    conn.close()

    return render_template('plan.html',
                           greeting=greeting, today=today,
                           selected_date=selected_date,
                           selected_display=selected_display,
                           is_today=is_today, is_future=is_future,
                           selected_plan=selected_plan, pending=pending,
                           done_count=done_count,
                           total_count=len(selected_plan),
                           total_hrs=round(total_hrs, 1),
                           history=history, just_done=just_done,
                           productivity=productivity,
                           chart_labels=json.dumps(chart_labels),
                           chart_values=json.dumps(chart_values),
                           all_planned_ids=all_planned_ids)


@app.route('/performance')
@login_required
def performance():
    username = current_user()
    conn = get_db()
    prof = conn.execute('SELECT * FROM profiles WHERE username=?', (username,)).fetchone()
    profile_name = prof['name'] if prof else session.get('display_name', '')
    greeting = get_greeting(profile_name)
    today = datetime.now().strftime('%Y-%m-%d')

    dates = conn.execute(
        'SELECT DISTINCT date FROM daily_plan WHERE username=? AND date<=? ORDER BY date',
        (username, today)).fetchall()

    daily_stats = []
    total_planned_all = total_done_all = 0
    total_hrs_all = 0.0
    streak = current_streak = 0

    for d in dates:
        date = d['date']
        rows = conn.execute('SELECT * FROM daily_plan WHERE username=? AND date=?',
                            (username, date)).fetchall()
        total = len(rows)
        done = sum(1 for r in rows if r['done'] == 1)
        hrs = sum(float(r['estimated'] or 0) for r in rows)
        rate = round((done / total * 100) if total > 0 else 0)
        total_planned_all += total
        total_done_all += done
        total_hrs_all += hrs
        if rate >= 70:
            current_streak += 1
            streak = max(streak, current_streak)
        else:
            current_streak = 0
        try:
            d_display = datetime.strptime(date, '%Y-%m-%d').strftime('%d %b')
        except:
            d_display = date
        daily_stats.append({
            'date': date, 'display': d_display,
            'total': total, 'done': done, 'hrs': round(hrs, 1), 'rate': rate
        })

    overall_rate = round((total_done_all / total_planned_all * 100) if total_planned_all > 0 else 0)
    avg_hrs = round(total_hrs_all / len(daily_stats), 1) if daily_stats else 0

    subject_stats = conn.execute(
        '''SELECT subject, COUNT(*) as total,
           SUM(CASE WHEN actual != "" AND actual IS NOT NULL THEN 1 ELSE 0 END) as done
           FROM tasks WHERE username=? GROUP BY subject''',
        (username,)).fetchall()
    subject_stats = [dict(t) for t in subject_stats]

    chart_labels, chart_values = get_productivity_chart_data(username)

    today_plan = conn.execute('SELECT * FROM daily_plan WHERE username=? AND date=?',
                              (username, today)).fetchall()
    today_plan = [dict(r) for r in today_plan]
    today_hrs = sum(float(p['estimated'] or 0) for p in today_plan)
    today_done = sum(1 for p in today_plan if p['done'] == 1)
    productivity = None
    if today_plan:
        productivity = predict_productivity(username, len(today_plan), today_hrs, done_today=today_done)

    conn.close()

    return render_template('performance.html',
                           greeting=greeting, profile_name=profile_name, today=today,
                           daily_stats=daily_stats, overall_rate=overall_rate,
                           total_planned=total_planned_all, total_done=total_done_all,
                           total_hrs=round(total_hrs_all, 1), avg_hrs=avg_hrs,
                           streak=streak, current_streak=current_streak,
                           subject_stats=subject_stats, productivity=productivity,
                           chart_labels=json.dumps(chart_labels),
                           chart_values=json.dumps(chart_values))



# ===== SUMMARY PAGE =====
@app.route('/summary')
@login_required
def summary():
    username = current_user()
    conn = get_db()
    prof = conn.execute('SELECT * FROM profiles WHERE username=?', (username,)).fetchone()
    profile_name = prof['name'] if prof else session.get('display_name', '')
    greeting = get_greeting(profile_name)
    today = datetime.now().strftime('%Y-%m-%d')

    # Period filter
    period = request.args.get('period', 'week')
    if period == 'month':
        since = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        period_label = 'Last 30 days'
    elif period == 'alltime':
        since = '2000-01-01'
        period_label = 'All time'
    else:
        since = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        period_label = 'Last 7 days'

    # Subject hours breakdown — use actual if logged, else estimated
    subject_hours = conn.execute('''
        SELECT subject,
               SUM(CASE WHEN actual != "" AND actual IS NOT NULL
                   THEN CAST(actual AS REAL)
                   ELSE estimated END) as actual_hrs,
               SUM(estimated) as estimated_hrs,
               COUNT(*) as task_count
        FROM tasks
        WHERE username=?
        GROUP BY subject
        ORDER BY actual_hrs DESC
    ''', (username,)).fetchall()
    subject_hours = [dict(r) for r in subject_hours]

    total_actual = sum(r['actual_hrs'] or 0 for r in subject_hours)

    # Add percentage to each
    for r in subject_hours:
        r['pct'] = round((r['actual_hrs'] / total_actual * 100) if total_actual > 0 else 0)

    # Daily plan stats in period
    plan_dates = conn.execute('''
        SELECT date,
               COUNT(*) as total,
               SUM(done) as done,
               SUM(estimated) as hrs
        FROM daily_plan
        WHERE username=? AND date >= ? AND date <= ?
        GROUP BY date ORDER BY date
    ''', (username, since, today)).fetchall()
    plan_dates = [dict(r) for r in plan_dates]

    # Best day
    best_day = max(plan_dates, key=lambda d: d['done'] / d['total'] if d['total'] > 0 else 0, default=None)
    worst_day = min(plan_dates, key=lambda d: d['done'] / d['total'] if d['total'] > 0 else 1, default=None)

    # Period totals
    period_hrs = sum(float(d['hrs'] or 0) for d in plan_dates)
    period_tasks_done = sum(d['done'] for d in plan_dates)
    period_tasks_total = sum(d['total'] for d in plan_dates)
    period_rate = round((period_tasks_done / period_tasks_total * 100) if period_tasks_total > 0 else 0)

    # Weekly breakdown (group by week)
    from collections import defaultdict
    week_data = defaultdict(lambda: {'hrs': 0, 'done': 0, 'total': 0})
    for d in plan_dates:
        try:
            dt = datetime.strptime(d['date'], '%Y-%m-%d')
            week_key = dt.strftime('W%W %Y')
            week_data[week_key]['hrs'] += float(d['hrs'] or 0)
            week_data[week_key]['done'] += d['done']
            week_data[week_key]['total'] += d['total']
        except:
            pass

    weekly = [{'week': k, 'hrs': round(v['hrs'], 1), 'done': v['done'], 'total': v['total'],
                'rate': round(v['done'] / v['total'] * 100 if v['total'] > 0 else 0)}
              for k, v in sorted(week_data.items())]

    # Chart data for pie — subject hours
    pie_labels = [r['subject'] or 'Other' for r in subject_hours]
    pie_values = [round(r['actual_hrs'] or 0, 1) for r in subject_hours]

    # Daily hours bar chart
    bar_labels = [d['date'] for d in plan_dates]
    bar_labels_display = []
    for d in plan_dates:
        try:
            bar_labels_display.append(datetime.strptime(d['date'], '%Y-%m-%d').strftime('%d %b'))
        except:
            bar_labels_display.append(d['date'])
    bar_values = [round(float(d['hrs'] or 0), 1) for d in plan_dates]

    conn.close()

    return render_template('summary.html',
                           greeting=greeting,
                           profile_name=profile_name,
                           period=period,
                           period_label=period_label,
                           subject_hours=subject_hours,
                           total_actual=round(total_actual, 1),
                           period_hrs=round(period_hrs, 1),
                           period_tasks_done=period_tasks_done,
                           period_tasks_total=period_tasks_total,
                           period_rate=period_rate,
                           best_day=best_day,
                           worst_day=worst_day,
                           weekly=weekly,
                           pie_labels=json.dumps(pie_labels),
                           pie_values=json.dumps(pie_values),
                           bar_labels=json.dumps(bar_labels_display),
                           bar_values=json.dumps(bar_values))


if __name__ == '__main__':
    app.run(debug=True)