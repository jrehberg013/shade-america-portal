import os, math, json, sqlite3, secrets
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, g, send_file, abort)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import io

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'sa-dev-key-change-in-prod')

# ─────────────────────────────────────────────────────────────
# DATABASE — supports SQLite (local) and PostgreSQL (production)
# Set DATABASE_URL env var on Render to use PostgreSQL.
# ─────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get('DATABASE_URL', '')
# Render provides postgres:// but psycopg2 requires postgresql://
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
else:
    DATABASE = os.environ.get('DATABASE_PATH', 'shade_america.db')

MAX_FILE_MB = 50


class _DB:
    """Thin wrapper so both sqlite3 and psycopg2 share the same API."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        if USE_PG:
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql.replace('?', '%s'), params)
            return cur
        return self._conn.execute(sql, params)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db():
    if 'db' not in g:
        if USE_PG:
            conn = psycopg2.connect(DATABASE_URL)
            g.db = _DB(conn)
        else:
            raw = sqlite3.connect(DATABASE)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA journal_mode=WAL")
            g.db = _DB(raw)
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()


def _bin(data):
    """Wrap binary data correctly for each database driver."""
    if USE_PG:
        return psycopg2.Binary(data)
    return data


def init_db():
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        statements = [
            """CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT,
                role TEXT DEFAULT 'field',
                must_change_password INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS jobs (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                client TEXT,
                phone TEXT,
                location TEXT,
                status TEXT DEFAULT 'quoted',
                estimate_total REAL DEFAULT 0,
                notes TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                job_id INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                doc_type TEXT DEFAULT 'other',
                file_data BYTEA,
                mime_type TEXT,
                file_size INTEGER,
                uploaded_by INTEGER,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS pricing (
                id SERIAL PRIMARY KEY,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                price REAL DEFAULT 0,
                unit TEXT,
                sort_order INTEGER DEFAULT 0
            )""",
        ]
        for stmt in statements:
            cur.execute(stmt)
        conn.commit()
        db = _DB(conn)
        db._conn = conn
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT,
                role TEXT DEFAULT 'field',
                must_change_password INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                client TEXT,
                phone TEXT,
                location TEXT,
                status TEXT DEFAULT 'quoted',
                estimate_total REAL DEFAULT 0,
                notes TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                doc_type TEXT DEFAULT 'other',
                file_data BLOB,
                mime_type TEXT,
                file_size INTEGER,
                uploaded_by INTEGER,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS pricing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                price REAL DEFAULT 0,
                unit TEXT,
                sort_order INTEGER DEFAULT 0
            );
        """)
        conn.commit()
        db = _DB(conn)

    # Seed users
    users = [
        ('james',   'SA-James#1',   'James',   'admin', 1),
        ('muller',  'SA-Muller#1',  'Muller',  'admin', 1),
        ('jaco',    'SA-Jaco#1',    'Jaco',    'admin', 1),
        ('carrie',  'SA-Carrie#1',  'Carrie',  'admin', 1),
        ('stefani', 'SA-Stefani#1', 'Stefani', 'admin', 1),
        ('field',   'SunShade24!',  'Field Team', 'field', 0),
    ]
    for uname, pwd, name, role, must_change in users:
        if not db.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone():
            db.execute(
                "INSERT INTO users (username,password_hash,name,role,must_change_password) VALUES (?,?,?,?,?)",
                (uname, generate_password_hash(pwd), name, role, must_change)
            )

    # Seed pricing
    if not db.execute("SELECT id FROM pricing LIMIT 1").fetchone():
        pricing_data = [
            ('pipe','5" SCH40 Galv 21ft',   412,  '$/stick', 1),
            ('pipe','5" SCH40 Black 21ft',  359,  '$/stick', 2),
            ('pipe','5" SCH40 Black 42ft',  718,  '$/stick', 3),
            ('pipe','6" SCH40 Galv 21ft',   536,  '$/stick', 4),
            ('pipe','6" SCH40 Black 21ft',  383,  '$/stick', 5),
            ('pipe','6" SCH40 Black 42ft',  780,  '$/stick', 6),
            ('pipe','8" SCH40 Galv 21ft',   743,  '$/stick', 7),
            ('pipe','8" SCH40 Black 21ft',  590,  '$/stick', 8),
            ('pipe','8" SCH40 Black 42ft',  1179, '$/stick', 9),
            ('pipe','3" OD Galv Tubing 24ft', 183, '$/stick',10),
            ('pipe','4" OD Galv Tubing 24ft', 259, '$/stick',11),
            ('pipe','5" OD Galv Tubing 24ft', 321, '$/stick',12),
            ('pipe','4x4 HSS 1/4" 20ft',    237,  '$/stick',13),
            ('pipe','4x4 HSS 1/4" 24ft',    317,  '$/stick',14),
            ('pipe','4x4 HSS 1/4" 40ft',    528,  '$/stick',15),
            ('pipe','4x4 HSS 3/16" 20ft',   204,  '$/stick',16),
            ('pipe','4x4 HSS 3/16" 24ft',   244,  '$/stick',17),
            ('pipe','4x6 HSS 1/4" 24ft',    405,  '$/stick',18),
            ('pipe','4x6 HSS 1/4" 40ft',    675,  '$/stick',19),
            ('pipe','4x6 HSS 3/16" 20ft',   259,  '$/stick',20),
            ('pipe','4x6 HSS 3/16" 24ft',   311,  '$/stick',21),
            ('pipe','4x6 HSS 3/16" 40ft',   576,  '$/stick',22),
            ('hardware','Weld Lug',         0,    '$/piece', 1),
            ('hardware','All Thread',       0,    '$/piece', 2),
            ('hardware','Clamp',            0,    '$/piece', 3),
            ('hardware','Wall Mount',       0,    '$/piece', 4),
            ('hardware','Welding Rate',     95,   '$/weld',  5),
            ('powder','5" SCH40',           0,    '$/LF',    1),
            ('powder','6" SCH40',           0,    '$/LF',    2),
            ('powder','8" SCH40',           0,    '$/LF',    3),
            ('powder','3" OD Galv',         0,    '$/LF',    4),
            ('powder','4" OD Galv',         0,    '$/LF',    5),
            ('powder','5" OD Galv',         0,    '$/LF',    6),
            ('powder','4x4 HSS',            0,    '$/LF',    7),
            ('powder','4x6 HSS',            0,    '$/LF',    8),
            ('powder','4x8 HSS',            0,    '$/LF',    9),
            ('fabric','Fabric per Sq Ft',   3.25, '$/sqft',  1),
            ('concrete','Price per CY',     200,  '$/CY',    1),
            ('crew','Rate - Person 1',      650,  '$/day',   1),
            ('crew','Rate - Person 2',      550,  '$/day',   2),
            ('crew','Rate - Person 3',      500,  '$/day',   3),
            ('crew','Rate - Person 4',      450,  '$/day',   4),
            ('crew','Rate - Person 5',      400,  '$/day',   5),
            ('travel','Fuel Cost per Mile', 0.40, '$/mile',  1),
        ]
        for row in pricing_data:
            db.execute("INSERT INTO pricing (category,name,price,unit,sort_order) VALUES (?,?,?,?,?)", row)

    db.commit()
    db.close()


# ─────────────────────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────────────────────

def get_current_user():
    if 'user_id' not in session:
        return None
    return {'id': session['user_id'], 'username': session['username'],
            'name': session.get('name', ''), 'role': session['role']}

@app.context_processor
def inject_user():
    return {'current_user': get_current_user()}

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('field') if session.get('role') == 'field' else url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['name'] = user['name'] or user['username']
            session['role'] = user['role']
            if user['must_change_password']:
                session['must_change'] = True
                return redirect(url_for('change_password'))
            return redirect(url_for('field') if user['role'] == 'field' else url_for('dashboard'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    must_change = session.get('must_change', False)
    if request.method == 'POST':
        new_pw  = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if len(new_pw) < 6:
            flash('Password must be at least 6 characters.', 'error')
        elif new_pw != confirm:
            flash('Passwords do not match.', 'error')
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                       (generate_password_hash(new_pw), session['user_id']))
            db.commit()
            session.pop('must_change', None)
            flash('Password updated.', 'success')
            return redirect(url_for('field') if session.get('role') == 'field' else url_for('dashboard'))
    return render_template('change_password.html', must_change=must_change)


# ─────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────

@app.route('/dashboard')
@admin_required
def dashboard():
    db = get_db()
    all_jobs = db.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    statuses = ['quoted', 'approved', 'in_progress', 'install', 'completed']
    jobs_by_status = {s: [j for j in all_jobs if j['status'] == s] for s in statuses}
    stats = {
        'total':       len(all_jobs),
        'quoted':      len(jobs_by_status['quoted']),
        'in_progress': len(jobs_by_status['in_progress']),
        'completed':   len(jobs_by_status['completed']),
    }
    return render_template('dashboard.html', jobs_by_status=jobs_by_status, stats=stats)


# ─────────────────────────────────────────────────────────────
# JOBS
# ─────────────────────────────────────────────────────────────

@app.route('/jobs')
@admin_required
def jobs():
    db = get_db()
    all_jobs = db.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    return render_template('jobs.html', jobs=all_jobs)

@app.route('/jobs/new', methods=['GET', 'POST'])
@admin_required
def new_job():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Job name is required.', 'error')
            return redirect(url_for('new_job'))
        db = get_db()
        try:
            est = float(request.form.get('estimate_total', 0) or 0)
        except ValueError:
            est = 0
        db.execute(
            "INSERT INTO jobs (name,client,phone,location,status,estimate_total,notes,created_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (name,
             request.form.get('client', ''),
             request.form.get('phone', ''),
             request.form.get('location', ''),
             request.form.get('status', 'quoted'),
             est,
             request.form.get('notes', ''),
             session['user_id'])
        )
        db.commit()
        flash(f'Job "{name}" created.', 'success')
        return redirect(url_for('dashboard'))
    prefill = {
        'name':           request.args.get('name', ''),
        'client':         request.args.get('client', ''),
        'estimate_total': request.args.get('estimate', ''),
    }
    return render_template('new_job.html', prefill=prefill)

@app.route('/jobs/<int:job_id>')
@login_required
def job_detail(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        abort(404)
    is_admin = session.get('role') == 'admin'
    docs = db.execute(
        "SELECT * FROM documents WHERE job_id=? ORDER BY uploaded_at DESC", (job_id,)
    ).fetchall()
    if not is_admin:
        docs = [d for d in docs if d['doc_type'] in ('drawing', 'photo')]
    return render_template('job_detail.html', job=job, documents=docs, is_admin=is_admin)

@app.route('/jobs/<int:job_id>/status', methods=['POST'])
@admin_required
def update_status(job_id):
    status = request.form.get('status')
    if status in ['quoted', 'approved', 'in_progress', 'install', 'completed']:
        db = get_db()
        db.execute("UPDATE jobs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, job_id))
        db.commit()
    return redirect(request.referrer or url_for('dashboard'))


# ─────────────────────────────────────────────────────────────
# DOCUMENTS
# ─────────────────────────────────────────────────────────────

@app.route('/jobs/<int:job_id>/upload', methods=['POST'])
@login_required
def upload_doc(job_id):
    db = get_db()
    if not db.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone():
        abort(404)
    doc_type = request.form.get('doc_type', 'photo')
    if doc_type != 'photo' and session.get('role') != 'admin':
        abort(403)
    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('job_detail', job_id=job_id))
    file_data = file.read()
    if len(file_data) > MAX_FILE_MB * 1024 * 1024:
        flash(f'File too large (max {MAX_FILE_MB} MB).', 'error')
        return redirect(url_for('job_detail', job_id=job_id))
    db.execute(
        "INSERT INTO documents (job_id,original_name,doc_type,file_data,mime_type,file_size,uploaded_by) "
        "VALUES (?,?,?,?,?,?,?)",
        (job_id, secure_filename(file.filename), doc_type, _bin(file_data),
         file.content_type or 'application/octet-stream', len(file_data), session['user_id'])
    )
    db.commit()
    flash('File uploaded.', 'success')
    return redirect(url_for('job_detail', job_id=job_id))

@app.route('/docs/<int:doc_id>')
@login_required
def serve_doc(doc_id):
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        abort(404)
    if doc['doc_type'] in ('estimate', 'contract', 'other') and session.get('role') != 'admin':
        abort(403)
    return send_file(
        io.BytesIO(bytes(doc['file_data'])),
        mimetype=doc['mime_type'],
        as_attachment=False,
        download_name=doc['original_name']
    )

@app.route('/docs/<int:doc_id>/delete', methods=['POST'])
@admin_required
def delete_doc(doc_id):
    db = get_db()
    doc = db.execute("SELECT job_id FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        abort(404)
    job_id = doc['job_id']
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db.commit()
    flash('File deleted.', 'success')
    return redirect(url_for('job_detail', job_id=job_id))


# ─────────────────────────────────────────────────────────────
# FIELD VIEW
# ─────────────────────────────────────────────────────────────

@app.route('/field')
@login_required
def field():
    db = get_db()
    raw_jobs = db.execute(
        "SELECT * FROM jobs WHERE status IN ('approved','in_progress','install') ORDER BY updated_at DESC"
    ).fetchall()
    jobs = []
    for job in raw_jobs:
        docs = db.execute(
            "SELECT * FROM documents WHERE job_id=? AND doc_type IN ('drawing','photo')"
            " ORDER BY uploaded_at DESC", (job['id'],)
        ).fetchall()
        jobs.append({
            'id':       job['id'],
            'name':     job['name'],
            'location': job['location'],
            'status':   job['status'],
            'drawings': [d for d in docs if d['doc_type'] == 'drawing'],
            'photos':   [d for d in docs if d['doc_type'] == 'photo'],
        })
    return render_template('field.html', jobs=jobs)


# ─────────────────────────────────────────────────────────────
# ESTIMATOR
# ─────────────────────────────────────────────────────────────

def get_pricing_map(db):
    rows = db.execute("SELECT name, price FROM pricing").fetchall()
    return {r['name']: r['price'] for r in rows}

def pipe_cost_calc(size, length_ft, qty, pm):
    if not size or not length_ft or not qty:
        return 0, 0
    length_ft = float(length_ft)
    qty = int(qty)
    options = []
    if size in ('4x4', '4x6', '4x8'):
        for wall in ['1/4"', '3/16"']:
            for stick_len in [20, 24, 40, 48]:
                key = f'{size} HSS {wall} {stick_len}ft'
                if key in pm and pm[key] > 0:
                    options.append((stick_len, pm[key]))
    elif 'OD Galv' in size:
        key = f'{size} 24ft'
        if key in pm and pm[key] > 0:
            options.append((24, pm[key]))
    else:
        for color in ['Galv', 'Black']:
            for stick_len in [21, 24, 40, 42, 48]:
                key = f'{size} {color} {stick_len}ft'
                if key in pm and pm[key] > 0:
                    options.append((stick_len, pm[key]))
    if not options:
        return 0, 0
    best_cost = None
    best_unit = 0
    for stick_len, price in options:
        sticks_per_pole = math.ceil(length_ft / stick_len)
        cost_per_pole = sticks_per_pole * price
        if best_cost is None or cost_per_pole < best_cost:
            best_cost = cost_per_pole
            best_unit = cost_per_pole
    return (best_cost or 0) * qty, best_unit

def get_powder_rate(size, pm):
    key_map = {
        '5" SCH40': '5" SCH40', '6" SCH40': '6" SCH40', '8" SCH40': '8" SCH40',
        '3" OD Galv Tubing': '3" OD Galv', '4" OD Galv Tubing': '4" OD Galv',
        '5" OD Galv Tubing': '5" OD Galv',
        '4x4': '4x4 HSS', '4x6': '4x6 HSS', '4x8': '4x8 HSS',
    }
    return pm.get(key_map.get(size, ''), 0)

def parse_pole_rows(prefix, f):
    n = int(f.get(f'{prefix}_count', 1) or 1)
    rows = []
    for i in range(n):
        rows.append({
            'size':   f.get(f'{prefix}_size_{i}', ''),
            'length': f.get(f'{prefix}_len_{i}', 0),
            'qty':    f.get(f'{prefix}_qty_{i}', 0),
            'attach': f.get(f'{prefix}_attach_{i}', ''),
        })
    return rows

@app.route('/estimator')
@admin_required
def estimator():
    return render_template('estimator.html')


# ─────────────────────────────────────────────────────────────
# HIP SHADE CALCULATOR
# ─────────────────────────────────────────────────────────────

def _half_round(val):
    """Round to nearest 0.5 — matches Excel's ROUND(x*2,0)/2 pattern."""
    return round(val * 2) / 2

def _fmt_fraction(sixteenths):
    """Convert a count of 1/16-inch units to a simplified fraction string."""
    from math import gcd
    if sixteenths == 0:
        return ''
    g = gcd(int(sixteenths), 16)
    return f'{int(sixteenths)//g}/{16//g}'

def _diagonal_sq(A1, D1):
    """Z2 formula: feet'-whole_inches  fraction" """
    import math
    diag_ft   = math.sqrt(A1**2 + D1**2)
    n16       = round(diag_ft * 12 * 16)          # total 1/16-inch units
    feet      = int(n16 // (12 * 16))
    remain16  = n16 - feet * 12 * 16
    whole_in  = remain16 // 16
    frac16    = remain16 % 16
    frac      = _fmt_fraction(frac16)
    return f"{feet}'-{whole_in}  {frac}\"" if frac else f"{feet}'-{whole_in}\""

def _diagonal_rect(A1, D1):
    """Z3 formula: total inches as simplified fraction" """
    import math
    diag_ft = math.sqrt(A1**2 + D1**2)
    n16     = round(diag_ft * 12 * 16)
    whole   = n16 // 16
    frac16  = n16 % 16
    frac    = _fmt_fraction(frac16)
    return f"{whole} {frac}\"" if frac else f'{whole}"'

def hip_calc_compute(A1, D1, F1, col_size, rafter_dia, qty=1, glides='No Glides'):
    import math
    B9   = qty
    AB4  = 0.67   # constant from spreadsheet

    # Profile
    ratio   = A1 / D1 if D1 else 1
    profile = 'Square' if 1 <= ratio < 1.175 else 'Rectangle'

    # Rafter OD for powder calc (per J4-J8 options)
    rafter_od = {
        'Ø2 1/2" 12-Ga': 2.5,
        'Ø2 7/8" 12-Ga': 2.875,
        'Ø3 1/2" 11-Ga': 3.5,
        'Ø5" 11-Ga':     5.0,
        'Ø5" 7-Ga':      5.0,
    }.get(rafter_dia, 3.5)

    def _sq():
        rafter  = _half_round(D1 * 0.6535 * 12)
        swage   = rafter - 4.25
        ridge   = _half_round(D1 * 0.25 * 12 if A1 == D1 else (D1 * 0.25 * 12) + (A1 - D1) * 12)
        rswage  = ridge - 8.5
        total   = _half_round((rafter * 4 + ridge) * B9)
        powder  = round(math.pi * rafter_od * total * 0.000376, 2)
        peak_v  = D1 * 0.1853 + AB4
        peak    = f"{int(peak_v)}'-{round((peak_v - int(peak_v)) * 12)}\""
        cable_sz = '3/16"' if A1*D1<400 else ('1/4"' if A1*D1<1000 else '5/16"')
        diag    = _diagonal_sq(A1, D1)
        return dict(
            profile='Square', rafter=rafter, to_swage=swage,
            ridge=ridge, ridge_swage=rswage, total=total,
            cable_size=cable_sz,
            cable_1=f"{round(A1*2+D1*2+10)}'",
            cable_2=f"{round(A1+D1+10)}' Each",
            diagonal=diag,
            powder=f'{powder} lb',
            peak=peak,
        )

    def _rect():
        rafter  = _half_round(D1 * 0.7115 * 12)
        swage   = rafter - 4.25
        ridge   = _half_round(D1 * 0.06655 * 12 if A1 == D1 else (D1 * 0.06655 * 12) + (A1 - D1) * 12)
        rswage  = ridge - 8.5
        total   = _half_round((rafter * 4 + ridge) * B9)
        powder  = round(math.pi * rafter_od * total * 0.000376, 2)
        peak_v  = D1 * 0.2026 + AB4
        peak    = f"{int(peak_v)}'-{round((peak_v - int(peak_v)) * 12)}\""
        perim   = A1 * 2 + D1 * 2 + 10
        c_qty   = 1 if (glides == 'Glides' or perim < 150) else 2
        cable_sz = '3/16"' if A1*D1<400 else ('1/4"' if A1*D1<1000 else '5/16"')
        diag    = _diagonal_rect(A1, D1)
        return dict(
            profile='Rectangle', rafter=rafter, to_swage=swage,
            ridge=ridge, ridge_swage=rswage, total=total,
            cable_size=f'Qty: {c_qty}',
            cable_1=f'{round(perim)*12*B9}" Total',
            cable_2=f'{round(A1+D1+10)*2*12*B9}" Total',
            diagonal=diag,
            powder=f'{powder} lb',
            peak=peak,
        )

    sq   = _sq()
    rect = _rect()
    return profile, sq, rect

@app.route('/hip-calc', methods=['GET', 'POST'])
@admin_required
def hip_calc():
    col_options = [
        'Ø3.5" 11-Ga', 'Ø5.0" 11-Ga', 'Ø5.0" 7-Ga', 'Ø5.5" Sch-40',
        'Ø6.6" Sch-40', 'Ø8.6" Sch-40', '10"x10"x1/4"', '12"x12"x1/4"',
    ]
    rafter_options = [
        'Ø2 1/2" 12-Ga', 'Ø2 7/8" 12-Ga', 'Ø3 1/2" 11-Ga',
        'Ø5" 11-Ga', 'Ø5" 7-Ga',
    ]
    result = None
    inputs = {}
    if request.method == 'POST':
        try:
            inputs = {
                'long_side':  float(request.form.get('long_side', 0)),
                'short_side': float(request.form.get('short_side', 0)),
                'eave_ht':    float(request.form.get('eave_ht', 0)),
                'col_size':   request.form.get('col_size', col_options[3]),
                'rafter_dia': request.form.get('rafter_dia', rafter_options[2]),
                'qty':        int(request.form.get('qty', 1) or 1),
                'glides':     request.form.get('glides', 'No Glides'),
            }
            profile, sq, rect = hip_calc_compute(
                inputs['long_side'], inputs['short_side'], inputs['eave_ht'],
                inputs['col_size'], inputs['rafter_dia'],
                inputs['qty'], inputs['glides'],
            )
            result = {'profile': profile, 'sq': sq, 'rect': rect}
        except (ValueError, ZeroDivisionError) as e:
            flash(f'Check your inputs: {e}', 'error')
    return render_template('hip_calc.html',
                           col_options=col_options,
                           rafter_options=rafter_options,
                           inputs=inputs, result=result)

@app.route('/estimator/calculate', methods=['POST'])
@admin_required
def calculate():
    db = get_db()
    pm = get_pricing_map(db)
    f = request.form

    job_name   = f.get('job_name', '')
    client     = f.get('client', '')
    markup_pct = float(f.get('markup_pct', 30) or 30)
    tax_pct    = float(f.get('tax_pct', 0) or 0)

    sail_rows  = parse_pole_rows('sail', f)
    hip_rows   = parse_pole_rows('hip', f)
    cpost_rows = parse_pole_rows('cpost', f)
    cbeam_rows = parse_pole_rows('cbeam', f)

    pole_detail = []
    steel_cost = 0
    weld_lug_count = 0

    for section, rows in [('Sail', sail_rows), ('Hip/Canopy', hip_rows),
                           ('Cant. Post', cpost_rows), ('Cant. Beam', cbeam_rows)]:
        for row in rows:
            if not row['size'] or not row['length'] or not row['qty']:
                continue
            cost, unit_cost = pipe_cost_calc(row['size'], row['length'], row['qty'], pm)
            steel_cost += cost
            pole_detail.append({
                'section': section, 'size': row['size'],
                'length': row['length'], 'qty': row['qty'],
                'unit_cost': unit_cost, 'total': cost,
            })
            if row.get('attach') == 'Weld Lug':
                weld_lug_count += int(row['qty'] or 0)

    weld_rate    = pm.get('Welding Rate', 95)
    cant_posts   = sum(int(r['qty'] or 0) for r in cpost_rows if r['size'])
    cant_beams   = sum(int(r['qty'] or 0) for r in cbeam_rows if r['size'])
    welding_cost = (weld_lug_count + cant_posts + cant_beams) * weld_rate

    powder_cost = 0
    for rows in [sail_rows, hip_rows, cpost_rows, cbeam_rows]:
        for row in rows:
            if not row['size'] or not row['length'] or not row['qty']:
                continue
            rate = get_powder_rate(row['size'], pm)
            powder_cost += rate * float(row['length'] or 0) * int(row['qty'] or 0)

    fabric_cost    = float(f.get('fabric_cost', 0) or 0)
    superior_quote = float(f.get('superior_quote', 0) or 0)
    labor_hours    = float(f.get('labor_hours', 0) or 0)
    labor_rate     = float(f.get('labor_rate', 75) or 75)
    labor_cost     = labor_hours * labor_rate

    materials_total = steel_cost + welding_cost + powder_cost + fabric_cost + superior_quote
    subtotal        = materials_total + labor_cost
    markup_amount   = subtotal * (markup_pct / 100)
    tax_amount      = (subtotal + markup_amount) * (tax_pct / 100)
    total           = subtotal + markup_amount + tax_amount

    result = {
        'job_name': job_name, 'client': client,
        'steel_cost': steel_cost, 'welding_cost': welding_cost,
        'powder_cost': powder_cost, 'fabric_cost': fabric_cost,
        'superior_quote': superior_quote,
        'materials_total': materials_total,
        'labor_hours': labor_hours, 'labor_rate': labor_rate, 'labor_cost': labor_cost,
        'subtotal': subtotal,
        'markup_pct': markup_pct, 'markup_amount': markup_amount,
        'tax_pct': tax_pct, 'tax_amount': tax_amount,
        'total': total,
        'pole_detail': pole_detail,
    }
    return render_template('estimate_result.html', result=result)


# ─────────────────────────────────────────────────────────────
# PRICING
# ─────────────────────────────────────────────────────────────

@app.route('/pricing')
@admin_required
def pricing():
    db = get_db()
    rows = db.execute("SELECT * FROM pricing ORDER BY category, sort_order").fetchall()
    return render_template('pricing.html', pricing=rows)

@app.route('/pricing/update', methods=['POST'])
@admin_required
def update_pricing():
    db = get_db()
    for key, val in request.form.items():
        if key.startswith('price_'):
            pid = int(key.split('_')[1])
            try:
                db.execute("UPDATE pricing SET price=? WHERE id=?", (float(val), pid))
            except (ValueError, TypeError):
                pass
    db.commit()
    flash('Prices updated.', 'success')
    return redirect(url_for('pricing'))


# ─────────────────────────────────────────────────────────────
# ADMIN — USER MANAGEMENT
# ─────────────────────────────────────────────────────────────

@app.route('/admin/users')
@admin_required
def admin_users():
    db = get_db()
    users = db.execute(
        "SELECT id,username,name,role,must_change_password FROM users ORDER BY role,name"
    ).fetchall()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/<int:user_id>/reset', methods=['POST'])
@admin_required
def reset_user(user_id):
    temp_pw = 'SA-' + secrets.token_hex(3).upper()
    db = get_db()
    user = db.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        abort(404)
    db.execute("UPDATE users SET password_hash=?, must_change_password=1 WHERE id=?",
               (generate_password_hash(temp_pw), user_id))
    db.commit()
    flash(f'Password for {user["username"]} reset to: {temp_pw}  — send this to them.', 'success')
    return redirect(url_for('admin_users'))


# ─────────────────────────────────────────────────────────────
# ERROR PAGES
# ─────────────────────────────────────────────────────────────

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', error='Access Denied',
                           message="You don't have permission to view this page."), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error='Page Not Found',
                           message="The page you're looking for doesn't exist."), 404


# ─────────────────────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────────────────────

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
