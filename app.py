import os, math, json, sqlite3, secrets, urllib.request, urllib.parse
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, g, send_file, abort, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import io

# ─────────────────────────────────────────────────────────────
# LOCATION DISTANCE TABLE (one-way miles from St. Augustine, FL)
# ─────────────────────────────────────────────────────────────
LOCATION_MILES = {
    "Green Cove Springs, FL": 28, "Palm Coast, FL": 30, "Orange Park, FL": 35,
    "Palatka, FL": 35, "Flagler Beach, FL": 38, "Jacksonville, FL": 40,
    "Crescent City, FL": 45, "Starke, FL": 50, "Ormond Beach, FL": 55,
    "Daytona Beach, FL": 62, "Fernandina Beach, FL": 65, "Lake City, FL": 65,
    "Port Orange, FL": 65, "Amelia Island, FL": 68, "DeLand, FL": 75,
    "Gainesville, FL": 77, "Brunswick, GA": 77, "Deltona, FL": 80,
    "New Smyrna Beach, FL": 82, "Live Oak, FL": 82, "Ocala, FL": 87,
    "Sanford, FL": 90, "Lake Mary, FL": 92, "The Villages, FL": 92,
    "Titusville, FL": 96, "Cocoa, FL": 102, "Altamonte Springs, FL": 102,
    "Leesburg, FL": 102, "Cocoa Beach, FL": 106, "Oviedo, FL": 107,
    "Winter Park, FL": 112, "Orlando, FL": 112, "Apopka, FL": 118,
    "Savannah, GA": 118, "Kissimmee, FL": 122, "Winter Garden, FL": 123,
    "Celebration, FL": 126, "Clermont, FL": 128, "Melbourne, FL": 128,
    "Palm Bay, FL": 133, "Winter Haven, FL": 142, "Lakeland, FL": 147,
    "Valdosta, GA": 147, "Sebastian, FL": 148, "Bartow, FL": 152,
    "Vero Beach, FL": 158, "Brooksville, FL": 158, "Spring Hill, FL": 162,
    "Zephyrhills, FL": 167, "Wesley Chapel, FL": 168, "Plant City, FL": 168,
    "Brandon, FL": 172, "Tampa, FL": 177, "New Port Richey, FL": 178,
    "Riverview, FL": 178, "Fort Pierce, FL": 178, "Safety Harbor, FL": 187,
    "Port St. Lucie, FL": 188, "Clearwater, FL": 192, "Largo, FL": 193,
    "St. Petersburg, FL": 193, "Tarpon Springs, FL": 197, "Dunedin, FL": 198,
    "Stuart, FL": 203, "Bradenton, FL": 207, "Hobe Sound, FL": 215,
    "Sarasota, FL": 218, "Tallahassee, FL": 218, "Venice, FL": 228,
    "North Port, FL": 232, "Jupiter, FL": 232, "Quincy, FL": 232,
    "Englewood, FL": 238, "Palm Beach Gardens, FL": 247, "Port Charlotte, FL": 248,
    "Punta Gorda, FL": 253, "Marianna, FL": 258, "West Palm Beach, FL": 263,
    "Lake Worth, FL": 268, "Boynton Beach, FL": 272, "Delray Beach, FL": 278,
    "Cape Coral, FL": 278, "Chipley, FL": 278, "Boca Raton, FL": 283,
    "Fort Myers, FL": 283, "Deerfield Beach, FL": 288, "Bonita Springs, FL": 292,
    "Estero, FL": 297, "Pompano Beach, FL": 298, "Naples, FL": 308,
    "Fort Lauderdale, FL": 308, "Hollywood, FL": 318, "Panama City, FL": 318,
    "Hallandale Beach, FL": 322, "Panama City Beach, FL": 322, "Marco Island, FL": 323,
    "Miramar, FL": 323, "Hialeah, FL": 337, "Miami, FL": 338, "Doral, FL": 342,
    "Coral Gables, FL": 342, "Miami Beach, FL": 348, "Niceville, FL": 362,
    "Homestead, FL": 363, "Fort Walton Beach, FL": 363, "Destin, FL": 368,
    "Crestview, FL": 373, "Key Largo, FL": 378, "Milton, FL": 387,
    "Pensacola, FL": 398, "Islamorada, FL": 403, "Marathon, FL": 428,
    "Key West, FL": 468,
}

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
                trello_url TEXT,
                contract_value REAL DEFAULT 0,
                deposit_paid REAL DEFAULT 0,
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
            """CREATE TABLE IF NOT EXISTS forms (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                file_data BYTEA,
                mime_type TEXT DEFAULT 'application/pdf',
                file_size INTEGER,
                uploaded_by INTEGER,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
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
                trello_url TEXT,
                contract_value REAL DEFAULT 0,
                deposit_paid REAL DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                file_data BLOB,
                mime_type TEXT DEFAULT 'application/pdf',
                file_size INTEGER,
                uploaded_by INTEGER,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        conn.commit()
        db = _DB(conn)

    # Seed users
    users = [
        ('james',   'SA-James#1',   'James',   'admin', 1),
        ('muller',  'SA-Muller#1',  'Muller',  'manager', 1),
        ('jaco',    'SA-Jaco#1',    'Jaco',    'manager', 1),
        ('carrie',  'SA-Carrie#1',  'Carrie',  'manager', 1),
        ('stefani', 'SA-Stefani#1', 'Stefani', 'manager', 1),
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
            ('tubing','2 1/2" OD Tubing 24ft',  0, '$/stick', 1),
            ('tubing','2 7/8" OD Tubing 24ft',  0, '$/stick', 2),
            ('tubing','3 1/2" OD Tubing 24ft',  0, '$/stick', 3),
            ('tubing','5" OD Tubing 24ft',       0, '$/stick', 4),
            ('fittings','Elbow',        0, '$/ea', 1),
            ('fittings','Y Fitting',    0, '$/ea', 2),
            ('fittings','Adapter',      0, '$/ea', 3),
            ('fittings','Swivel Cross', 0, '$/ea', 4),
            ('fittings','Post/Purlin Adapter Slip In', 45, '$/ea', 5),
            ('pipe','1.9" Steel Tubing 16ft', 63, '$/stick', 23),
            ('pipe','1.9" Steel Tubing 24ft', 94, '$/stick', 24),
        ]
        for row in pricing_data:
            db.execute("INSERT INTO pricing (category,name,price,unit,sort_order) VALUES (?,?,?,?,?)", row)

    # Add new pricing items if missing (for existing databases)
    new_items = [
        ('tubing','2 1/2" OD Tubing 24ft',  0, '$/stick', 1),
        ('tubing','2 7/8" OD Tubing 24ft',  0, '$/stick', 2),
        ('tubing','3 1/2" OD Tubing 24ft',  0, '$/stick', 3),
        ('tubing','5" OD Tubing 24ft',       0, '$/stick', 4),
        ('fittings','Elbow',        0, '$/ea', 1),
        ('fittings','Y Fitting',    0, '$/ea', 2),
        ('fittings','Adapter',      0, '$/ea', 3),
        ('fittings','Swivel Cross', 0, '$/ea', 4),
        ('fittings','Post/Purlin Adapter Slip In', 45, '$/ea', 5),
        ('pipe','1.9" Steel Tubing 16ft', 63, '$/stick', 23),
        ('pipe','1.9" Steel Tubing 24ft', 94, '$/stick', 24),
    ]
    for cat, name, price, unit, sort in new_items:
        if not db.execute("SELECT id FROM pricing WHERE category=? AND name=?", (cat, name)).fetchone():
            db.execute("INSERT INTO pricing (category,name,price,unit,sort_order) VALUES (?,?,?,?,?)",
                       (cat, name, price, unit, sort))

    # Migrate existing databases — add Trello sync columns if missing
    for col, typedef in [('trello_url','TEXT'), ('contract_value','REAL DEFAULT 0'), ('deposit_paid','REAL DEFAULT 0')]:
        try:
            if USE_PG:
                db.execute(f"ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {col} {typedef}")
            else:
                db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typedef}")
        except Exception:
            pass

    db.commit()
    db.close()


# ─────────────────────────────────────────────────────────────
# STAT CARDS CONFIG
# ─────────────────────────────────────────────────────────────

_DEFAULT_STAT_CARDS = json.dumps([
    {"key": "total",           "label": "Total Jobs",        "color": ""},
    {"key": "contract_total",  "label": "Total Job Value",   "color": "text-blue"},
    {"key": "balance_owed",    "label": "Balance Owed",      "color": "text-orange"},
    {"key": "pipeline_value",  "label": "Pipeline Value",    "color": "text-green"},
    {"key": "installation",    "label": "Installation",      "color": "text-orange"},
    {"key": "completed",       "label": "Completed",         "color": "text-grey"},
])

def get_stat_cards_config(db):
    try:
        row = db.execute("SELECT value FROM settings WHERE key='stat_cards'").fetchone()
        return json.loads(row['value'] if row else _DEFAULT_STAT_CARDS)
    except Exception:
        return json.loads(_DEFAULT_STAT_CARDS)


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

def manager_required(f):
    """Allows admin and manager roles."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') not in ('admin', 'manager'):
            abort(403)
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
@manager_required
def dashboard():
    db = get_db()
    all_jobs = db.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    statuses = ['deposit_received','design','engineering','permitting','fabrication','installation','completed']
    jobs_by_status = {s: [j for j in all_jobs if j['status'] == s] for s in statuses}
    active_jobs    = [j for j in all_jobs if j['status'] != 'completed']
    pipeline_value = sum(float(j['estimate_total'] or 0) for j in active_jobs)
    contract_total = sum(float(j['contract_value'] or 0) for j in active_jobs)
    balance_owed   = sum(float(j['contract_value'] or 0) - float(j['deposit_paid'] or 0) for j in active_jobs)
    stats = {
        'total':            len(all_jobs),
        'deposit_received': len(jobs_by_status['deposit_received']),
        'design':           len(jobs_by_status['design']),
        'engineering':      len(jobs_by_status['engineering']),
        'permitting':       len(jobs_by_status['permitting']),
        'fabrication':      len(jobs_by_status['fabrication']),
        'installation':     len(jobs_by_status['installation']),
        'completed':        len(jobs_by_status['completed']),
        'pipeline_value':   pipeline_value,
        'contract_total':   contract_total,
        'balance_owed':     balance_owed,
    }
    stat_cards = get_stat_cards_config(db)
    forms = db.execute("SELECT id, name, file_size, uploaded_at FROM forms ORDER BY name").fetchall()
    return render_template('dashboard.html',
                           jobs_by_status=jobs_by_status,
                           stats=stats,
                           stat_cards=stat_cards,
                           forms=forms)


# ─────────────────────────────────────────────────────────────
# JOBS
# ─────────────────────────────────────────────────────────────

@app.route('/jobs')
@manager_required
def jobs():
    db = get_db()
    all_jobs = db.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    return render_template('jobs.html', jobs=all_jobs)

@app.route('/jobs/new', methods=['GET', 'POST'])
@manager_required
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
        trello_url = request.form.get('trello_url', '').strip()
        db.execute(
            "INSERT INTO jobs (name,client,phone,location,status,estimate_total,notes,trello_url,created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name,
             request.form.get('client', ''),
             request.form.get('phone', ''),
             request.form.get('location', ''),
             request.form.get('status', 'deposit_received'),
             est,
             request.form.get('notes', ''),
             trello_url,
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
    is_admin = session.get('role') in ('admin', 'manager')
    docs = db.execute(
        "SELECT * FROM documents WHERE job_id=? ORDER BY uploaded_at DESC", (job_id,)
    ).fetchall()
    if not is_admin:
        docs = [d for d in docs if d['doc_type'] in ('drawing', 'photo')]
    return render_template('job_detail.html', job=job, documents=docs, is_admin=is_admin)


@app.route('/jobs/<int:job_id>/edit', methods=['POST'])
@manager_required
def edit_job(job_id):
    db = get_db()
    if not db.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone():
        abort(404)
    name           = request.form.get('name', '').strip()
    client         = request.form.get('client', '').strip()
    phone          = request.form.get('phone', '').strip()
    location       = request.form.get('location', '').strip()
    notes          = request.form.get('notes', '').strip()
    estimate_total = request.form.get('estimate_total', '').strip()
    try:
        estimate_total = float(estimate_total) if estimate_total else None
    except ValueError:
        estimate_total = None
    db.execute(
        "UPDATE jobs SET name=?, client=?, phone=?, location=?, notes=?, estimate_total=? WHERE id=?",
        (name, client, phone, location, notes, estimate_total, job_id)
    )
    db.commit()
    flash('Job details updated.', 'success')
    return redirect(url_for('job_detail', job_id=job_id))

@app.route('/jobs/<int:job_id>/status', methods=['POST'])
@manager_required
def update_status(job_id):
    status = request.form.get('status')
    if status in ['deposit_received','design','engineering','permitting','fabrication','installation','completed']:
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
    if session.get('role') == 'field':
        return redirect(url_for('field'))
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
@login_required
def delete_doc(doc_id):
    db = get_db()
    doc = db.execute("SELECT job_id, doc_type FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        abort(404)
    # Field staff may only delete photos
    if session.get('role') == 'field' and doc['doc_type'] != 'photo':
        abort(403)
    job_id = doc['job_id']
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db.commit()
    flash('File deleted.', 'success')
    if session.get('role') == 'field':
        return redirect(url_for('field'))
    return redirect(url_for('job_detail', job_id=job_id))


# ─────────────────────────────────────────────────────────────
# FIELD VIEW
# ─────────────────────────────────────────────────────────────

@app.route('/field')
@login_required
def field():
    db = get_db()
    raw_jobs = db.execute(
        "SELECT * FROM jobs WHERE status = 'installation' ORDER BY updated_at DESC"
    ).fetchall()
    jobs = []
    for job in raw_jobs:
        docs = db.execute(
            "SELECT * FROM documents WHERE job_id=? ORDER BY uploaded_at DESC", (job['id'],)
        ).fetchall()
        sa_docs = [d for d in docs if d['original_name'].upper().startswith('SA-')]
        all_photos = [d for d in docs if d['doc_type'] == 'photo']
        jobs.append({
            'id':       job['id'],
            'name':     job['name'],
            'location': job['location'],
            'status':   job['status'],
            'drawings': [d for d in sa_docs if d['doc_type'] == 'drawing'],
            'photos':   all_photos,
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
    # Handle combined HSS size like '4x4 HSS 1/4"'
    for prefix in ['4x4', '4x6', '4x8']:
        if size.startswith(prefix + ' HSS'):
            return pm.get(f'{prefix} HSS', 0)
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
@manager_required
def estimator():
    db = get_db()
    pm = get_pricing_map(db)
    fabric_rate = pm.get('Fabric per Sq Ft', 3.25)
    pipe_sizes      = ['5" SCH40', '6" SCH40', '8" SCH40',
                       '3" OD Galv Tubing', '4" OD Galv Tubing', '5" OD Galv Tubing']
    hss_profiles    = ['4x4', '4x6', '4x8']
    hss_walls       = ['1/4"', '3/16"']
    # OD tubing for hip upper frame ridge/rafters (3/4/5" OD Galv only)
    od_tubing_names = [
        '3" OD Galv Tubing 24ft',
        '4" OD Galv Tubing 24ft',
        '5" OD Galv Tubing 24ft',
    ]
    # Tubing for cantilever upper frames (general tubing)
    tubing_names = ['2 1/2" OD Tubing 24ft', '2 7/8" OD Tubing 24ft',
                    '3 1/2" OD Tubing 24ft', '5" OD Tubing 24ft']
    # Purlin tubing — 1.9" Steel only
    purlin_tubing_names = [
        '1.9" Steel Tubing 16ft',
        '1.9" Steel Tubing 24ft',
    ]
    location_cities = sorted(LOCATION_MILES.keys())
    return render_template('estimator.html',
                           pricing_json=json.dumps(pm),
                           fabric_rate=fabric_rate,
                           pipe_sizes=pipe_sizes,
                           hss_profiles=hss_profiles,
                           hss_walls=hss_walls,
                           tubing_names=tubing_names,
                           od_tubing_names=od_tubing_names,
                           purlin_tubing_names=purlin_tubing_names,
                           location_cities=location_cities,
                           location_miles_json=json.dumps(LOCATION_MILES))


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

def _fmt_ft_in(total_inches):
    """Convert inches to feet-inches-eighths string, e.g. 19' 7 1/2\" """
    from math import gcd
    eighths = round(total_inches * 8)
    feet = eighths // 96
    remain = eighths % 96
    whole_in = remain // 8
    frac8 = remain % 8
    if frac8:
        g = gcd(frac8, 8)
        frac_str = f' {frac8//g}/{8//g}"'
    else:
        frac_str = '"'
    return f"{feet}' {whole_in}{frac_str}"

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
            profile='Square', rafter=rafter, rafter_ft=_fmt_ft_in(rafter),
            to_swage=swage, ridge=ridge, ridge_ft=_fmt_ft_in(ridge),
            ridge_swage=rswage, total=total,
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
            profile='Rectangle', rafter=rafter, rafter_ft=_fmt_ft_in(rafter),
            to_swage=swage, ridge=ridge, ridge_ft=_fmt_ft_in(ridge),
            ridge_swage=rswage, total=total,
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
@manager_required
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
@manager_required
def calculate():
    db = get_db()
    pm = get_pricing_map(db)
    f = request.form

    job_name        = f.get('job_name', '')
    client          = f.get('client', '')
    client_email    = f.get('client_email', '')
    client_phone    = f.get('client_phone', '')
    location        = f.get('location', '')
    quote_num       = f.get('quote_num', '')
    markup_pct      = float(f.get('markup_pct', 50) or 50)
    superior_amount = float(f.get('superior_amount', 0) or 0)
    fabric_rate_input = float(f.get('fabric_rate', pm.get('Fabric per Sq Ft', 3.25)) or 3.25)

    # ── Structures & Fabric ──
    n_structs  = int(f.get('struct_count', 0) or 0)
    structs    = []
    total_sqft = 0.0
    for i in range(n_structs):
        stype = f.get(f'struct_type_{i}', '')
        s1  = float(f.get(f'struct_s1_{i}', 0) or 0)
        s2  = float(f.get(f'struct_s2_{i}', 0) or 0)
        s3  = float(f.get(f'struct_s3_{i}', 0) or 0)
        qty = int(f.get(f'struct_qty_{i}', 1) or 1)
        if not s1:
            continue
        if stype == 'sail' and s2 and s3:
            s = (s1 + s2 + s3) / 2
            area_ea = math.sqrt(max(0, s*(s-s1)*(s-s2)*(s-s3)))
        elif s2:
            area_ea = s1 * s2
        else:
            area_ea = 0
        sqft_total = area_ea * qty
        total_sqft += sqft_total
        structs.append({'type': stype, 's1': s1, 's2': s2, 's3': s3,
                        'qty': qty, 'sqft': round(sqft_total, 1)})
    fabric_cost = total_sqft * fabric_rate_input

    # ── Poles helper ──
    def _poles(prefix, has_attach=False, has_wall=False):
        n = int(f.get(f'{prefix}_count', 1) or 1)
        rows = []
        for i in range(n):
            if has_wall:
                profile = f.get(f'{prefix}_profile_{i}', '')
                wall    = f.get(f'{prefix}_wall_{i}', '1/4"')
                size    = f'{profile} HSS {wall}' if profile else ''
            else:
                size = f.get(f'{prefix}_size_{i}', '')
            length     = float(f.get(f'{prefix}_len_{i}', 0) or 0)
            qty        = int(f.get(f'{prefix}_qty_{i}', 0) or 0)
            attach     = f.get(f'{prefix}_attach_{i}', '') if has_attach else ''
            footer_dia = float(f.get(f'{prefix}_footer_dia_{i}', 0) or 0)
            footer_dep = float(f.get(f'{prefix}_footer_depth_{i}', 0) or 0)
            if size and length and qty:
                cy = math.pi * (footer_dia/2)**2 * footer_dep / 27 if footer_dia and footer_dep else 0
                rows.append({'size': size, 'length': length, 'qty': qty,
                             'attach': attach, 'cy': cy * qty})
        return rows

    sail_poles  = _poles('sail',  has_attach=True)
    hip_poles   = _poles('hip')
    cant_posts  = _poles('cpost', has_wall=True)
    cant_beams  = _poles('cbeam', has_wall=True)

    # Steel & welding
    steel_cost     = 0
    weld_lug_count = 0
    pole_detail    = []
    for section, rows in [('Sail Poles', sail_poles), ('Hip/Canopy', hip_poles),
                           ('Cant. Posts', cant_posts), ('Cant. Beams', cant_beams)]:
        for row in rows:
            cost, unit_cost = pipe_cost_calc(row['size'], row['length'], row['qty'], pm)
            steel_cost += cost
            pole_detail.append({'section': section, 'size': row['size'],
                                'length': row['length'], 'qty': row['qty'],
                                'unit_cost': unit_cost, 'total': cost})
            if row.get('attach') == 'Weld Lug':
                weld_lug_count += row['qty']

    weld_rate    = pm.get('Welding Rate', 95)
    cpost_qty    = sum(r['qty'] for r in cant_posts)
    cbeam_qty    = sum(r['qty'] for r in cant_beams)
    welding_cost = (weld_lug_count + cpost_qty + cbeam_qty) * weld_rate

    # Powder
    powder_cost = 0
    for rows in [sail_poles, hip_poles, cant_posts, cant_beams]:
        for row in rows:
            rate = get_powder_rate(row['size'], pm)
            powder_cost += rate * row['length'] * row['qty']

    # Concrete — regular footers
    all_cy        = sum(r['cy'] for r in sail_poles + hip_poles + cant_posts)
    concrete_rate = pm.get('Price per CY', 200)
    concrete_cost = all_cy * concrete_rate * 1.10

    # Superior Footers
    sup_footer_count = int(f.get('sup_footer_count', 1) or 1)
    sup_footer_cy    = 0.0
    for i in range(sup_footer_count):
        qty   = int(f.get(f'sup_footer_qty_{i}', 0) or 0)
        dia   = float(f.get(f'sup_footer_dia_{i}', 0) or 0)
        depth = float(f.get(f'sup_footer_depth_{i}', 0) or 0)
        if qty and dia and depth:
            sup_footer_cy += math.pi * (dia/2)**2 * depth / 27 * qty
    sup_footer_cost = sup_footer_cy * concrete_rate * 1.10

    # Hardware extras
    wall_mount_qty  = int(f.get('wall_mount_qty', 0) or 0)
    clamp_qty       = int(f.get('clamp_qty', 0) or 0)
    wall_mount_cost = wall_mount_qty * pm.get('Wall Mount', 0)
    clamp_cost      = clamp_qty * pm.get('Clamp', 0)

    # Upper frames — prices come from pricing sheet, not form input
    _fitting_keys = {
        'elbows': 'Elbow', 'ys': 'Y Fitting',
        'adapters': 'Adapter', 'swivel_cross': 'Swivel Cross',
        'post_purlin_adapter': 'Post/Purlin Adapter Slip In',
    }

    def _upper_frames(prefix, fitting_comps, tubing_comps, manual_comps=None):
        manual_comps = manual_comps or []
        n = int(f.get(f'{prefix}_frame_count', 5) or 5)
        total = 0.0
        for i in range(n):
            # For purlin frames, dome_qty multiplies everything (entered per-dome quantities)
            if prefix == 'pf':
                dome_qty   = float(f.get(f'pf_domes_qty_{i}', 1) or 1)
                dome_price = float(f.get(f'pf_domes_price_{i}', 0) or 0)
                per_dome = dome_price  # start with dome unit cost
                for comp in fitting_comps:
                    qty   = float(f.get(f'{prefix}_{comp}_qty_{i}', 0) or 0)
                    price = pm.get(_fitting_keys.get(comp, comp), 0)
                    per_dome += qty * price
                for comp in tubing_comps:
                    size  = f.get(f'{prefix}_{comp}_size_{i}', '')
                    qty   = float(f.get(f'{prefix}_{comp}_qty_{i}', 0) or 0)
                    price = pm.get(size, 0)
                    per_dome += qty * price
                total += dome_qty * per_dome
            else:
                for comp in fitting_comps:
                    qty   = float(f.get(f'{prefix}_{comp}_qty_{i}', 0) or 0)
                    price = pm.get(_fitting_keys.get(comp, comp), 0)
                    total += qty * price
                for comp in tubing_comps:
                    size  = f.get(f'{prefix}_{comp}_size_{i}', '')
                    qty   = float(f.get(f'{prefix}_{comp}_qty_{i}', 0) or 0)
                    price = pm.get(size, 0)
                    total += qty * price
                for comp in manual_comps:
                    qty   = float(f.get(f'{prefix}_{comp}_qty_{i}', 0) or 0)
                    price = float(f.get(f'{prefix}_{comp}_price_{i}', 0) or 0)
                    total += qty * price
        return total

    hip_frames_cost  = _upper_frames('hf',
                           fitting_comps=['elbows', 'ys'],
                           tubing_comps=['ridge', 'rafters'])
    cant_frames_cost = _upper_frames('cf',
                           fitting_comps=['elbows', 'ys', 'adapters', 'swivel_cross'],
                           tubing_comps=['ridge', 'rafters'])
    purlin_cost      = _upper_frames('pf',
                           fitting_comps=['adapters', 'swivel_cross', 'post_purlin_adapter'],
                           tubing_comps=['purlin_len', 'purlin_wid', 'hoops'],
                           manual_comps=['domes'])

    # Travel
    miles       = float(f.get('miles', 0) or 0)
    fuel_rate   = float(f.get('fuel_rate', 0.4) or 0.4)
    round_trips = int(f.get('round_trips', 1) or 1)
    lodging     = float(f.get('lodging', 0) or 0)
    travel_cost = miles * 2 * round_trips * fuel_rate + lodging

    # Crew & Labor
    crew_count  = int(f.get('crew_count', 1) or 1)
    install_days = int(f.get('install_days', 1) or 1)
    daily_crew  = sum(pm.get(f'Rate - Person {i}', 0) for i in range(1, crew_count + 1))
    labor_cost  = daily_crew * install_days

    # Other costs
    hardware    = float(f.get('hardware', 0) or 0)
    supplies    = float(f.get('supplies', 0) or 0)
    galvanizing = float(f.get('galvanizing', 0) or 0)
    equipment   = float(f.get('equipment', 0) or 0)
    permits     = float(f.get('permits', 0) or 0)
    vendor      = float(f.get('vendor', 0) or 0)
    misc        = float(f.get('misc', 0) or 0)

    # Totals
    materials_total = (superior_amount + fabric_cost + steel_cost + concrete_cost
                       + sup_footer_cost
                       + hip_frames_cost + cant_frames_cost + purlin_cost
                       + welding_cost + powder_cost
                       + hardware + supplies + galvanizing
                       + wall_mount_cost + clamp_cost)
    other_total     = equipment + permits + vendor + misc
    base_total      = travel_cost + labor_cost + materials_total + other_total
    markup_amount   = base_total * (markup_pct / 100)
    sell_price      = base_total + markup_amount

    result = {
        'job_name': job_name, 'client': client, 'location': location,
        'quote_num': quote_num, 'client_email': client_email, 'client_phone': client_phone,
        'total_sqft': round(total_sqft, 1), 'structs': structs,
        'fabric_rate': fabric_rate_input,
        'fabric_cost': fabric_cost, 'superior_amount': superior_amount,
        'sup_footer_cy': round(sup_footer_cy, 2), 'sup_footer_cost': sup_footer_cost,
        'steel_cost': steel_cost, 'welding_cost': welding_cost,
        'powder_cost': powder_cost,
        'all_cy': round(all_cy, 2), 'concrete_cost': concrete_cost,
        'hip_frames_cost': hip_frames_cost, 'cant_frames_cost': cant_frames_cost,
        'purlin_cost': purlin_cost,
        'hardware': hardware, 'supplies': supplies, 'galvanizing': galvanizing,
        'wall_mount_cost': wall_mount_cost, 'clamp_cost': clamp_cost,
        'materials_total': materials_total,
        'miles': miles, 'lodging': lodging, 'travel_cost': travel_cost,
        'crew_count': crew_count, 'install_days': install_days,
        'daily_crew': daily_crew, 'labor_cost': labor_cost,
        'equipment': equipment, 'permits': permits, 'vendor': vendor, 'misc': misc,
        'other_total': other_total,
        'base_total': base_total,
        'markup_pct': markup_pct, 'markup_amount': markup_amount,
        'sell_price': sell_price,
        'pole_detail': pole_detail,
    }
    return render_template('estimate_result.html', result=result)


# ─────────────────────────────────────────────────────────────
# PRICING
# ─────────────────────────────────────────────────────────────

@app.route('/pricing')
@manager_required
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
    users = db.execute("SELECT * FROM users ORDER BY role, username").fetchall()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/<int:user_id>/role', methods=['POST'])
@admin_required
def change_user_role(user_id):
    new_role = request.form.get('role', '')
    if new_role not in ('admin', 'manager', 'field'):
        flash('Invalid role.', 'error')
        return redirect(url_for('admin_users'))
    if user_id == session['user_id']:
        flash('You cannot change your own role.', 'error')
        return redirect(url_for('admin_users'))
    db = get_db()
    db.execute("UPDATE users SET role=?  WHERE id=?", (new_role, user_id))
    db.commit()
    flash('Role updated.', 'success')
    return redirect(url_for('admin_users'))


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



@app.route('/admin/users/create', methods=['POST'])
@admin_required
def create_user():
    username = request.form.get('username', '').strip().lower()
    name     = request.form.get('name', '').strip()
    role     = request.form.get('role', 'field')
    password = request.form.get('password', '').strip()
    if not username or not password:
        flash('Username and password are required.', 'error')
        return redirect(url_for('admin_users'))
    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'error')
        return redirect(url_for('admin_users'))
    if role not in ('admin', 'manager', 'field'):
        flash('Invalid role.', 'error')
        return redirect(url_for('admin_users'))
    db = get_db()
    if db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
        flash(f'Username "{username}" is already taken.', 'error')
        return redirect(url_for('admin_users'))
    db.execute(
        "INSERT INTO users (username,password_hash,name,role,must_change_password) VALUES (?,?,?,?,?)",
        (username, generate_password_hash(password), name, role, 1)
    )
    db.commit()
    flash(f'User "{username}" created. They must change password on first login.', 'success')
    return redirect(url_for('admin_users'))



@app.route('/admin/settings')
@admin_required
def admin_settings():
    db    = get_db()
    forms = db.execute("SELECT * FROM forms ORDER BY uploaded_at DESC").fetchall()
    stat_cards = get_stat_cards_config(db)
    db.close()
    return render_template('admin_settings.html', forms=forms, stat_cards=stat_cards)

@app.route('/admin/stat-cards', methods=['POST'])
@admin_required
def save_stat_cards():
    data  = request.get_json(silent=True) or {}
    cards = data.get('cards', [])
    valid_keys = {'total','deposit_received','design','engineering','permitting','fabrication','installation','completed','pipeline_value','contract_total','balance_owed'}
    clean = [
        {'key': c['key'], 'label': c['label'].strip(), 'color': c.get('color','')}
        for c in cards if c.get('key') in valid_keys and c.get('label','').strip()
    ]
    db  = get_db()
    val = json.dumps(clean)
    if db.execute("SELECT key FROM settings WHERE key='stat_cards'").fetchone():
        db.execute("UPDATE settings SET value=? WHERE key='stat_cards'", (val,))
    else:
        db.execute("INSERT INTO settings (key,value) VALUES ('stat_cards',?)", (val,))
    db.commit()
    return jsonify({'ok': True})


# ─────────────────────────────────────────────────────────────
# FORMS (company-wide PDFs for field crew)
# ─────────────────────────────────────────────────────────────

@app.route('/forms')
@login_required
def forms_list():
    db = get_db()
    forms = db.execute("SELECT id, name, file_size, uploaded_at FROM forms ORDER BY name").fetchall()
    return render_template('forms.html', forms=forms)

@app.route('/forms/upload', methods=['POST'])
@admin_required
def forms_upload():
    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('dashboard'))
    if not file.filename.lower().endswith('.pdf'):
        flash('Only PDF files are allowed.', 'error')
        return redirect(url_for('dashboard'))
    file_data = file.read()
    if len(file_data) > MAX_FILE_MB * 1024 * 1024:
        flash(f'File too large (max {MAX_FILE_MB} MB).', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    name = secure_filename(file.filename)
    db.execute(
        "INSERT INTO forms (name, file_data, mime_type, file_size, uploaded_by) VALUES (?,?,?,?,?)",
        (name, _bin(file_data), 'application/pdf', len(file_data), session['user_id'])
    )
    db.commit()
    flash(f'Form "{name}" uploaded.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/forms/<int:form_id>')
@login_required
def serve_form(form_id):
    db = get_db()
    form = db.execute("SELECT * FROM forms WHERE id=?", (form_id,)).fetchone()
    if not form:
        abort(404)
    return send_file(
        io.BytesIO(bytes(form['file_data'])),
        mimetype='application/pdf',
        as_attachment=False,
        download_name=form['name']
    )

@app.route('/forms/<int:form_id>/delete', methods=['POST'])
@admin_required
def forms_delete(form_id):
    db = get_db()
    db.execute("DELETE FROM forms WHERE id=?", (form_id,))
    db.commit()
    flash('Form deleted.', 'success')
    return redirect(url_for('dashboard'))

# Trello response cache (avoids repeated slow API calls)
_trello_cache = {'data': None, 'ts': 0}
_TRELLO_CACHE_TTL = 300  # seconds (5 minutes)

# ─────────────────────────────────────────────────────────────
# TRELLO API PROXY
# ─────────────────────────────────────────────────────────────


@app.route('/api/trello/config')
@login_required
def trello_config():
    api_key = os.environ.get('TRELLO_API_KEY', '')
    token   = os.environ.get('TRELLO_TOKEN', '')
    if not api_key or not token:
        return jsonify({'error': 'not_configured'})
    return jsonify({'api_key': api_key, 'token': token})

@app.route('/api/trello')
@login_required
def trello_data():
    import time as _time
    # Serve from cache if fresh
    if _trello_cache['data'] and (_time.time() - _trello_cache['ts']) < _TRELLO_CACHE_TTL:
        return jsonify(_trello_cache['data'])

    api_key = os.environ.get('TRELLO_API_KEY', '')
    token   = os.environ.get('TRELLO_TOKEN', '')
    if not api_key or not token:
        return jsonify({'error': 'not_configured'})

    target_boards = ['Shade America']

    # Lists to EXCLUDE per board (case-insensitive)
    EXCLUDED_LISTS = {
        'Shade America': [
            'design',
            'card template under construction',
            "estimates & po's",
            'money received/ project done',
        ],
    }
    # Lists to INCLUDE per board — only these shown when defined
    ALLOWED_LISTS = {
        'Installation': [
            'planning',
            'welding',
            'powder coating',
            'galvanizing',
            'add to install schedule',
            'jobs on temp hold',
            'installed needs attention',
        ],
    }

    def _keep_list(board_name, list_name):
        ln = list_name.strip().lower()
        if board_name in ALLOWED_LISTS:
            return ln in [x.lower() for x in ALLOWED_LISTS[board_name]]
        if board_name in EXCLUDED_LISTS:
            return ln not in [x.lower() for x in EXCLUDED_LISTS[board_name]]
        return True

    def _card_name(c):
        n = (c.get('name') or '').strip()
        if n:
            return n
        desc = (c.get('desc') or '').strip()
        return desc[:60] if desc else 'Card ' + c.get('shortLink', '?')

    try:
        # Fetch all boards for the authenticated member
        url = (f'https://api.trello.com/1/members/me/boards'
               f'?key={urllib.parse.quote(api_key)}&token={urllib.parse.quote(token)}'
               f'&fields=name,id,url&filter=open')
        with urllib.request.urlopen(url, timeout=10) as resp:
            all_boards = json.loads(resp.read())

        result = []
        for board in all_boards:
            if board['name'] not in target_boards:
                continue
            # Fetch lists AND all cards in just 2 calls per board (not 1 per list)
            lurl = (f"https://api.trello.com/1/boards/{board['id']}/lists"
                    f"?key={urllib.parse.quote(api_key)}&token={urllib.parse.quote(token)}"
                    f"&filter=open&fields=name,id")
            with urllib.request.urlopen(lurl, timeout=8) as resp:
                lists = json.loads(resp.read())

            # One call for ALL cards on this board
            curl = (f"https://api.trello.com/1/boards/{board['id']}/cards"
                    f"?key={urllib.parse.quote(api_key)}&token={urllib.parse.quote(token)}"
                    f"&fields=name,shortLink,url,due,desc,labels,idList&filter=open")
            with urllib.request.urlopen(curl, timeout=15) as resp:
                all_cards = json.loads(resp.read())

            # Group cards by list id
            cards_by_list = {}
            for c in all_cards:
                lid = c.get('idList', '')
                cards_by_list.setdefault(lid, []).append(c)

            board_data = {'name': board['name'], 'url': board['url'], 'lists': []}
            for lst in lists:
                if not _keep_list(board['name'], lst['name']):
                    continue
                cards = cards_by_list.get(lst['id'], [])
                board_data['lists'].append({
                    'name': lst['name'],
                    'cards': [{'name': _card_name(c), 'url': c['url'],
                               'due': c.get('due'), 'desc': c.get('desc', ''),
                               'labels': [{'color': lb.get('color'), 'name': lb.get('name','')}
                                          for lb in c.get('labels', [])]}
                              for c in cards]
                })
            result.append(board_data)

        # Sort by target board order
        result.sort(key=lambda b: target_boards.index(b['name'])
                    if b['name'] in target_boards else 99)
        payload = {'boards': result}
        _trello_cache['data'] = payload
        _trello_cache['ts']   = _time.time()
        return jsonify(payload)

    except Exception as e:
        return jsonify({'error': str(e), 'detail': repr(e)})





# ─────────────────────────────────────────────────────────────
# CREATE JOB FROM TRELLO CARD (drag-and-drop)
# ─────────────────────────────────────────────────────────────

@app.route('/jobs/from-trello', methods=['POST'])
@manager_required
def job_from_trello():
    import re as _re
    data = request.get_json(force=True) or {}
    trello_url = data.get('trello_url', '').strip()
    status     = data.get('status', 'deposit_received')
    card_name  = data.get('card_name', '').strip()

    if not trello_url:
        return jsonify({'error': 'No Trello URL provided'}), 400

    m = _re.search(r'trello\.com/c/([^/]+)', trello_url)
    if not m:
        return jsonify({'error': 'Invalid Trello URL'}), 400
    short_link = m.group(1)

    api_key = os.environ.get('TRELLO_API_KEY', '')
    token   = os.environ.get('TRELLO_TOKEN', '')
    auth    = f'key={urllib.parse.quote(api_key)}&token={urllib.parse.quote(token)}'

    contract_value = 0.0
    deposit_paid   = 0.0

    try:
        # Fetch card details
        card_url = f'https://api.trello.com/1/cards/{short_link}?{auth}&fields=name,desc,idBoard'
        with urllib.request.urlopen(card_url, timeout=10) as r:
            card = json.loads(r.read())
        job_name   = card.get('name') or card_name or 'New Job'
        board_id   = card.get('idBoard', '')
        notes      = card.get('desc', '')

        # Fetch custom field definitions + values
        if board_id:
            cf_def_url = f'https://api.trello.com/1/boards/{board_id}/customFields?{auth}'
            with urllib.request.urlopen(cf_def_url, timeout=10) as r:
                cf_defs = json.loads(r.read())
            cf_name_map = {cf['id']: cf['name'] for cf in cf_defs}

            cf_val_url = f'https://api.trello.com/1/cards/{short_link}/customFieldItems?{auth}'
            with urllib.request.urlopen(cf_val_url, timeout=10) as r:
                cf_items = json.loads(r.read())

            for item in cf_items:
                fname = cf_name_map.get(item.get('idCustomField'), '').lower()
                val   = item.get('value') or {}
                if 'number' in val:
                    try:
                        num = float(val['number'])
                        if 'contract' in fname:
                            contract_value = num
                        elif 'deposit' in fname:
                            deposit_paid = num
                    except (TypeError, ValueError):
                        pass
    except Exception as e:
        job_name = card_name or 'New Job'
        notes    = ''

    # Create the job
    db = get_db()
    db.execute(
        "INSERT INTO jobs (name,status,trello_url,contract_value,deposit_paid,notes,created_by)"
        " VALUES (?,?,?,?,?,?,?)",
        (job_name, status, trello_url, contract_value, deposit_paid, notes, session['user_id'])
    )
    db.commit()
    job_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()['id'] if not USE_PG else              db.execute("SELECT id FROM jobs WHERE trello_url=? ORDER BY id DESC LIMIT 1", (trello_url,)).fetchone()['id']
    db.close()

    return jsonify({
        'id':             job_id,
        'name':           job_name,
        'status':         status,
        'trello_url':     trello_url,
        'contract_value': contract_value,
        'deposit_paid':   deposit_paid,
        'url':            f'/jobs/{job_id}',
    })


# ─────────────────────────────────────────────────────────────
# TRELLO SYNC ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/jobs/<int:job_id>/trello-link', methods=['POST'])
@manager_required
def trello_link(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        flash('Job not found.', 'error')
        return redirect(url_for('dashboard'))
    trello_url = request.form.get('trello_url', '').strip()
    db.execute("UPDATE jobs SET trello_url=? WHERE id=?", (trello_url, job_id))
    db.commit()
    db.close()
    flash('Trello card linked.', 'success')
    return redirect(url_for('job_detail', job_id=job_id))


@app.route('/jobs/<int:job_id>/trello-sync', methods=['POST'])
@manager_required
def trello_sync(job_id):
    import re as _re
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        flash('Job not found.', 'error')
        return redirect(url_for('dashboard'))

    trello_url = job['trello_url'] or ''
    if not trello_url:
        flash('No Trello card linked to this job.', 'error')
        return redirect(url_for('job_detail', job_id=job_id))

    # Extract short link from URL: https://trello.com/c/{shortLink}/...
    m = _re.search(r'trello\.com/c/([^/]+)', trello_url)
    if not m:
        flash('Invalid Trello card URL.', 'error')
        return redirect(url_for('job_detail', job_id=job_id))
    short_link = m.group(1)

    api_key = os.environ.get('TRELLO_API_KEY', '')
    token   = os.environ.get('TRELLO_TOKEN', '')
    if not api_key or not token:
        flash('Trello API not configured.', 'error')
        return redirect(url_for('job_detail', job_id=job_id))

    auth = f'key={urllib.parse.quote(api_key)}&token={urllib.parse.quote(token)}'

    try:
        # Get card info (board id + custom fields + desc)
        card_url = f'https://api.trello.com/1/cards/{short_link}?{auth}&fields=idBoard,name,desc'
        with urllib.request.urlopen(card_url, timeout=10) as r:
            card = json.loads(r.read())
        board_id = card['idBoard']
        card_desc = (card.get('desc') or '').strip()

        # Get board custom field definitions
        cf_def_url = f'https://api.trello.com/1/boards/{board_id}/customFields?{auth}'
        with urllib.request.urlopen(cf_def_url, timeout=10) as r:
            cf_defs = json.loads(r.read())
        cf_name_map = {cf['id']: cf['name'] for cf in cf_defs}

        # Get card custom field values
        cf_val_url = f'https://api.trello.com/1/cards/{short_link}/customFieldItems?{auth}'
        with urllib.request.urlopen(cf_val_url, timeout=10) as r:
            cf_items = json.loads(r.read())

        contract_value = 0.0
        deposit_paid   = 0.0
        for item in cf_items:
            fname = cf_name_map.get(item.get('idCustomField'), '').lower()
            val   = item.get('value') or {}
            num   = None
            if 'number' in val:
                try:
                    num = float(val['number'])
                except (TypeError, ValueError):
                    pass
            if num is not None:
                if 'contract' in fname:
                    contract_value = num
                elif 'deposit' in fname:
                    deposit_paid = num

        # Fetch attachments, download SA- prefixed ones
        att_url = f'https://api.trello.com/1/cards/{short_link}/attachments?{auth}'
        with urllib.request.urlopen(att_url, timeout=10) as r:
            attachments = json.loads(r.read())

        synced_files = 0
        for att in attachments:
            att_name = att.get('name', '')
            if not att_name.upper().startswith('SA-'):
                continue
            # Check if already uploaded
            existing = db.execute(
                "SELECT id FROM documents WHERE job_id=? AND original_name=?",
                (job_id, att_name)
            ).fetchone()
            if existing:
                continue
            # Download
            try:
                dl_url = att.get('url', '')
                if not dl_url:
                    continue
                req = urllib.request.Request(
                    dl_url,
                    headers={'Authorization': f'OAuth oauth_consumer_key="{api_key}", oauth_token="{token}"'}
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    file_data = r.read()
                mime = att.get('mimeType') or 'application/octet-stream'
                if USE_PG:
                    db.execute(
                        "INSERT INTO documents (job_id,original_name,doc_type,file_data,mime_type,file_size,uploaded_by)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (job_id, att_name, 'drawing', _bin(file_data), mime, len(file_data), session['user_id'])
                    )
                else:
                    db.execute(
                        "INSERT INTO documents (job_id,original_name,doc_type,file_data,mime_type,file_size,uploaded_by)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (job_id, att_name, 'drawing', file_data, mime, len(file_data), session['user_id'])
                    )
                synced_files += 1
            except Exception:
                pass

        # Update job with contract value, deposit, and notes (from card desc)
        if card_desc:
            db.execute(
                "UPDATE jobs SET contract_value=?, deposit_paid=?, notes=? WHERE id=?",
                (contract_value, deposit_paid, card_desc, job_id)
            )
        else:
            db.execute(
                "UPDATE jobs SET contract_value=?, deposit_paid=? WHERE id=?",
                (contract_value, deposit_paid, job_id)
            )
        db.commit()
        db.close()
        flash(f'Synced from Trello: {synced_files} file(s) downloaded, contract ${contract_value:,.2f}, deposit ${deposit_paid:,.2f}.', 'success')

    except Exception as e:
        flash(f'Trello sync error: {str(e)}', 'error')

    return redirect(url_for('job_detail', job_id=job_id))



@app.route('/api/trello/refresh')
@admin_required
def trello_refresh():
    _trello_cache['data'] = None
    _trello_cache['ts']   = 0
    return jsonify({'ok': True})

# ─────────────────────────────────────────────────────────────
# TRELLO DEBUG — list raw board/list names
# ─────────────────────────────────────────────────────────────

@app.route('/api/trello/lists')
@admin_required
def trello_list_names():
    api_key = os.environ.get('TRELLO_API_KEY', '')
    token   = os.environ.get('TRELLO_TOKEN', '')
    if not api_key or not token:
        return jsonify({'error': 'not_configured'})
    try:
        url = (f'https://api.trello.com/1/members/me/boards'
               f'?key={urllib.parse.quote(api_key)}&token={urllib.parse.quote(token)}'
               f'&fields=name,id&filter=open')
        with urllib.request.urlopen(url, timeout=10) as resp:
            all_boards = json.loads(resp.read())
        out = []
        for board in all_boards:
            if board['name'] not in ['Shade America', 'Installation', 'Sewing Shop']:
                continue
            lurl = (f"https://api.trello.com/1/boards/{board['id']}/lists"
                    f"?key={urllib.parse.quote(api_key)}&token={urllib.parse.quote(token)}"
                    f"&filter=open&fields=name")
            with urllib.request.urlopen(lurl, timeout=10) as resp:
                lists = json.loads(resp.read())
            out.append({'board': board['name'], 'lists': [l['name'] for l in lists]})
        return jsonify(out)
    except Exception as e:
        return jsonify({'error': str(e)})

# ─────────────────────────────────────────────────────────────
# FIELD VIEW PREVIEW (admin only)
# ─────────────────────────────────────────────────────────────

@app.route('/field-preview')
@admin_required
def field_preview():
    db = get_db()
    raw_jobs = db.execute(
        "SELECT * FROM jobs WHERE status = 'installation' ORDER BY updated_at DESC"
    ).fetchall()
    jobs = []
    for job in raw_jobs:
        docs = db.execute(
            "SELECT * FROM documents WHERE job_id=? ORDER BY uploaded_at DESC", (job['id'],)
        ).fetchall()
        sa_docs = [d for d in docs if d['original_name'].upper().startswith('SA-')]
        all_photos = [d for d in docs if d['doc_type'] == 'photo']
        jobs.append({
            'id': job['id'], 'name': job['name'],
            'location': job['location'], 'status': job['status'],
            'drawings': [d for d in sa_docs if d['doc_type'] == 'drawing'],
            'photos':   all_photos,
        })
    return render_template('field.html', jobs=jobs, preview_mode=True)


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
# AUTO TRELLO SYNC (background scheduler — runs every 20 min)
# ─────────────────────────────────────────────────────────────

def sync_all_trello_jobs():
    """Download new SA- attachments and refresh contract/deposit for every linked job."""
    import re as _re
    api_key = os.environ.get('TRELLO_API_KEY', '')
    token   = os.environ.get('TRELLO_TOKEN', '')
    if not api_key or not token:
        return
    auth = f'key={urllib.parse.quote(api_key)}&token={urllib.parse.quote(token)}'

    with app.app_context():
        db = get_db()
        jobs = db.execute(
            "SELECT id, trello_url FROM jobs WHERE trello_url IS NOT NULL AND trello_url != ''"
        ).fetchall()

        for job in jobs:
            job_id     = job['id']
            trello_url = job['trello_url']
            m = _re.search(r'trello\.com/c/([^/]+)', trello_url)
            if not m:
                continue
            short_link = m.group(1)

            try:
                # Get board id
                card_url = f'https://api.trello.com/1/cards/{short_link}?{auth}&fields=idBoard'
                with urllib.request.urlopen(card_url, timeout=10) as r:
                    card = json.loads(r.read())
                board_id = card.get('idBoard', '')

                # Custom fields — contract value + deposit
                contract_value = None
                deposit_paid   = None
                if board_id:
                    cf_def_url = f'https://api.trello.com/1/boards/{board_id}/customFields?{auth}'
                    with urllib.request.urlopen(cf_def_url, timeout=10) as r:
                        cf_defs = json.loads(r.read())
                    cf_name_map = {cf['id']: cf['name'] for cf in cf_defs}

                    cf_val_url = f'https://api.trello.com/1/cards/{short_link}/customFieldItems?{auth}'
                    with urllib.request.urlopen(cf_val_url, timeout=10) as r:
                        cf_items = json.loads(r.read())

                    for item in cf_items:
                        fname = cf_name_map.get(item.get('idCustomField'), '').lower()
                        val   = item.get('value') or {}
                        if 'number' in val:
                            try:
                                num = float(val['number'])
                                if 'contract' in fname:
                                    contract_value = num
                                elif 'deposit' in fname:
                                    deposit_paid = num
                            except (TypeError, ValueError):
                                pass

                # Update dollar values if we got them
                if contract_value is not None or deposit_paid is not None:
                    if contract_value is not None and deposit_paid is not None:
                        db.execute(
                            "UPDATE jobs SET contract_value=?, deposit_paid=? WHERE id=?",
                            (contract_value, deposit_paid, job_id)
                        )
                    elif contract_value is not None:
                        db.execute("UPDATE jobs SET contract_value=? WHERE id=?", (contract_value, job_id))
                    else:
                        db.execute("UPDATE jobs SET deposit_paid=? WHERE id=?", (deposit_paid, job_id))

                # Attachments — download new SA- files
                att_url = f'https://api.trello.com/1/cards/{short_link}/attachments?{auth}'
                with urllib.request.urlopen(att_url, timeout=10) as r:
                    attachments = json.loads(r.read())

                for att in attachments:
                    att_name = att.get('name', '')
                    if not att_name.upper().startswith('SA-'):
                        continue
                    existing = db.execute(
                        "SELECT id FROM documents WHERE job_id=? AND original_name=?",
                        (job_id, att_name)
                    ).fetchone()
                    if existing:
                        continue
                    try:
                        dl_url = att.get('url', '')
                        if not dl_url:
                            continue
                        req = urllib.request.Request(
                            dl_url,
                            headers={'Authorization': f'OAuth oauth_consumer_key="{api_key}", oauth_token="{token}"'}
                        )
                        with urllib.request.urlopen(req, timeout=30) as r:
                            file_data = r.read()
                        mime = att.get('mimeType') or 'application/octet-stream'
                        if USE_PG:
                            db.execute(
                                "INSERT INTO documents (job_id,original_name,doc_type,file_data,mime_type,file_size,uploaded_by)"
                                " VALUES (?,?,?,?,?,?,?)",
                                (job_id, att_name, 'drawing', _bin(file_data), mime, len(file_data), 1)
                            )
                        else:
                            db.execute(
                                "INSERT INTO documents (job_id,original_name,doc_type,file_data,mime_type,file_size,uploaded_by)"
                                " VALUES (?,?,?,?,?,?,?)",
                                (job_id, att_name, 'drawing', file_data, mime, len(file_data), 1)
                            )
                    except Exception:
                        pass

                db.commit()

            except Exception:
                pass

        db.close()



# ─────────────────────────────────────────────────────────────
# STATIC ICON ROUTES (Safari looks for these at root)
# ─────────────────────────────────────────────────────────────

@app.route('/apple-touch-icon.png')
@app.route('/apple-touch-icon-precomposed.png')
def apple_touch_icon():
    return app.send_static_file('apple-touch-icon.png')

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('apple-touch-icon.png')

# ─────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────

@app.route('/report')
@manager_required
def report():
    import datetime
    db = get_db()
    all_jobs = db.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    statuses = ['deposit_received','design','engineering','permitting','fabrication','installation','completed']
    status_labels = {
        'deposit_received': 'Deposit Received',
        'design':           'Design',
        'engineering':      'Engineering',
        'permitting':       'Permitting',
        'fabrication':      'Fabrication',
        'installation':     'Installation',
        'completed':        'Completed',
    }
    jobs_by_status = {s: [j for j in all_jobs if j['status'] == s] for s in statuses}
    active_jobs    = [j for j in all_jobs if j['status'] != 'completed']
    pipeline_value = sum(float(j['estimate_total'] or 0) for j in active_jobs)
    contract_total = sum(float(j['contract_value']  or 0) for j in active_jobs)
    balance_owed   = sum(float(j['contract_value']  or 0) - float(j['deposit_paid'] or 0) for j in active_jobs)
    stats = {
        'total':          len(all_jobs),
        'active':         len(active_jobs),
        'pipeline_value': pipeline_value,
        'contract_total': contract_total,
        'balance_owed':   balance_owed,
    }
    report_date = datetime.datetime.now().strftime('%B %d, %Y  %I:%M %p')
    db.close()
    return render_template('report.html',
                           jobs_by_status=jobs_by_status,
                           status_labels=status_labels,
                           statuses=statuses,
                           stats=stats,
                           report_date=report_date)

# ─────────────────────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────────────────────

with app.app_context():
    init_db()

# Start background Trello sync scheduler (every 20 minutes)
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(sync_all_trello_jobs, 'interval', minutes=20, id='trello_sync', next_run_time=None)
    import datetime as _dt
    _scheduler.add_job(sync_all_trello_jobs, 'date', run_date=_dt.datetime.now()+_dt.timedelta(minutes=3), id='trello_sync_first')
    _scheduler.start()
except Exception:
    pass  # APScheduler not available — sync will be manual only

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
