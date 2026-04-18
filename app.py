import os, math, json, sqlite3
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, g, send_file, abort)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import io

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'sa-change-this-in-production-2024')

DATABASE = os.environ.get('DATABASE_PATH', 'shade_america.db')
UPLOAD_FOLDER = 'uploads'
MAX_FILE_MB = 50

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.executescript("""
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
            location TEXT,
            status TEXT DEFAULT 'lead',
            estimate_amount REAL DEFAULT 0,
            estimate_data TEXT,
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
            value REAL DEFAULT 0,
            unit TEXT,
            sort_order INTEGER DEFAULT 0
        );
    """)
    db.commit()

    # Seed users
    users = [
        ('james',   'SA-James#1',   'James Rehberg', 'admin', 1),
        ('muller',  'SA-Muller#1',  'Muller',        'admin', 1),
        ('jaco',    'SA-Jaco#1',    'Jaco',          'admin', 1),
        ('carrie',  'SA-Carrie#1',  'Carrie',        'admin', 1),
        ('stefani', 'SA-Stefani#1', 'Stefani',       'admin', 1),
        ('field',   'SunShade24!',  'Field Team',    'field', 0),
    ]
    for uname, pwd, name, role, must_change in users:
        existing = db.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO users (username,password_hash,name,role,must_change_password) VALUES (?,?,?,?,?)",
                (uname, generate_password_hash(pwd), name, role, must_change)
            )

    # Seed pricing
    if not db.execute("SELECT id FROM pricing LIMIT 1").fetchone():
        pricing_data = [
            # SCH40 Pipe  (category, name, value, unit, sort)
            ('pipe','5" SCH40 Galv 21ft',   412,  '$/stick', 1),
            ('pipe','5" SCH40 Galv 24ft',   0,    '$/stick', 2),
            ('pipe','5" SCH40 Black 21ft',  359,  '$/stick', 3),
            ('pipe','5" SCH40 Black 42ft',  718,  '$/stick', 4),
            ('pipe','6" SCH40 Galv 21ft',   536,  '$/stick', 5),
            ('pipe','6" SCH40 Galv 24ft',   0,    '$/stick', 6),
            ('pipe','6" SCH40 Black 21ft',  383,  '$/stick', 7),
            ('pipe','6" SCH40 Black 42ft',  780,  '$/stick', 8),
            ('pipe','8" SCH40 Galv 21ft',   743,  '$/stick', 9),
            ('pipe','8" SCH40 Galv 24ft',   0,    '$/stick',10),
            ('pipe','8" SCH40 Black 21ft',  590,  '$/stick',11),
            ('pipe','8" SCH40 Black 42ft',  1179, '$/stick',12),
            ('pipe','3" OD Galv 24ft',      183,  '$/stick',13),
            ('pipe','4" OD Galv 24ft',      259,  '$/stick',14),
            ('pipe','5" OD Galv 24ft',      321,  '$/stick',15),
            ('pipe','4x4 1/4" 20ft',        237,  '$/stick',16),
            ('pipe','4x4 1/4" 24ft',        317,  '$/stick',17),
            ('pipe','4x4 1/4" 40ft',        528,  '$/stick',18),
            ('pipe','4x4 1/4" 48ft',        633,  '$/stick',19),
            ('pipe','4x4 3/16" 20ft',       204,  '$/stick',20),
            ('pipe','4x4 3/16" 24ft',       244,  '$/stick',21),
            ('pipe','4x6 1/4" 24ft',        405,  '$/stick',22),
            ('pipe','4x6 1/4" 40ft',        675,  '$/stick',23),
            ('pipe','4x6 3/16" 20ft',       259,  '$/stick',24),
            ('pipe','4x6 3/16" 24ft',       311,  '$/stick',25),
            ('pipe','4x6 3/16" 40ft',       576,  '$/stick',26),
            ('pipe','4x6 3/16" 48ft',       621,  '$/stick',27),
            # Concrete
            ('concrete','Price per CY',     200,  '$/CY',    1),
            # Hardware
            ('hardware','Weld Lug',         0,    '$/piece', 1),
            ('hardware','All Thread',       0,    '$/piece', 2),
            ('hardware','Clamp',            0,    '$/piece', 3),
            ('hardware','Wall Mount',       0,    '$/piece', 4),
            ('hardware','Welding Rate',     95,   '$/weld',  5),
            # Powder Coating
            ('powder','5" SCH40',           0,    '$/LF',    1),
            ('powder','6" SCH40',           0,    '$/LF',    2),
            ('powder','8" SCH40',           0,    '$/LF',    3),
            ('powder','3" OD Galv',         0,    '$/LF',    4),
            ('powder','4" OD Galv',         0,    '$/LF',    5),
            ('powder','5" OD Galv',         0,    '$/LF',    6),
            ('powder','4x4 HSS',            0,    '$/LF',    7),
            ('powder','4x6 HSS',            0,    '$/LF',    8),
            ('powder','4x8 HSS',            0,    '$/LF',    9),
            # Fabric
            ('fabric','Cost per Sq Ft',     3.25, '$/sqft',  1),
            # Crew rates
            ('crew','Rate - Person 1',      650,  '$/day',   1),
            ('crew','Rate - Person 2',      550,  '$/day',   2),
            ('crew','Rate - Person 3',      500,  '$/day',   3),
            ('crew','Rate - Person 4',      450,  '$/day',   4),
            ('crew','Rate - Person 5',      400,  '$/day',   5),
            # Travel
            ('travel','Fuel Cost per Mile', 0.40, '$/mile',  1),
        ]
        for row in pricing_data:
            db.execute("INSERT INTO pricing (category,name,value,unit,sort_order) VALUES (?,?,?,?,?)", row)

    db.commit()
    db.close()

# ─────────────────────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────────────────────

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

def current_user():
    if 'user_id' not in session:
        return None
    return {'id': session['user_id'], 'username': session['username'],
            'name': session['name'], 'role': session['role']}

app.jinja_env.globals['current_user'] = current_user

# ─────────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def index():
    if 'user_id' in session:
        if session.get('role') == 'field':
            return redirect(url_for('field'))
        return redirect(url_for('dashboard'))
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
            session['name'] = user['name']
            session['role'] = user['role']
            if user['must_change_password']:
                return redirect(url_for('change_password'))
            if user['role'] == 'field':
                return redirect(url_for('field'))
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        new_pw = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if len(new_pw) < 8:
            flash('Password must be at least 8 characters.', 'error')
        elif new_pw != confirm:
            flash('Passwords do not match.', 'error')
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                       (generate_password_hash(new_pw), session['user_id']))
            db.commit()
            flash('Password updated successfully.', 'success')
            if session.get('role') == 'field':
                return redirect(url_for('field'))
            return redirect(url_for('dashboard'))
    return render_template('change_password.html')

# ─────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────

@app.route('/dashboard')
@admin_required
def dashboard():
    db = get_db()
    jobs = db.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    statuses = ['lead', 'estimated', 'sold', 'progress', 'complete']
    board = {s: [j for j in jobs if j['status'] == s] for s in statuses}
    pipeline_val = sum(j['estimate_amount'] for j in jobs if j['status'] in ('estimated','sold','progress'))
    active = sum(1 for j in jobs if j['status'] in ('sold','progress'))
    in_progress = sum(1 for j in jobs if j['status'] == 'progress')
    completed_mtd = sum(1 for j in jobs if j['status'] == 'complete')
    completed_rev = sum(j['estimate_amount'] for j in jobs if j['status'] == 'complete')
    return render_template('dashboard.html', board=board, statuses=statuses,
                           pipeline_val=pipeline_val, active=active,
                           in_progress=in_progress, completed_mtd=completed_mtd,
                           completed_rev=completed_rev)

# ─────────────────────────────────────────────────────────────
# JOBS
# ─────────────────────────────────────────────────────────────

@app.route('/jobs')
@admin_required
def jobs():
    db = get_db()
    all_jobs = db.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    return render_template('jobs.html', jobs=all_jobs)

@app.route('/jobs/<int:job_id>')
@login_required
def job_detail(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        abort(404)
    is_admin = session.get('role') == 'admin'
    docs = db.execute(
        "SELECT d.*, u.name as uploader_name FROM documents d "
        "LEFT JOIN users u ON d.uploaded_by=u.id WHERE d.job_id=? ORDER BY d.uploaded_at DESC",
        (job_id,)
    ).fetchall()
    drawings = [d for d in docs if d['doc_type'] == 'drawing']
    financials = [d for d in docs if d['doc_type'] == 'financial'] if is_admin else []
    photos = [d for d in docs if d['doc_type'] == 'photo']
    other = [d for d in docs if d['doc_type'] == 'other'] if is_admin else []
    return render_template('job_detail.html', job=job, drawings=drawings,
                           financials=financials, photos=photos, other=other,
                           is_admin=is_admin)

@app.route('/jobs/new', methods=['GET', 'POST'])
@admin_required
def new_job():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Job name is required.', 'error')
            return redirect(url_for('new_job'))
        db = get_db()
        db.execute(
            "INSERT INTO jobs (name,client,location,status,notes,created_by) VALUES (?,?,?,?,?,?)",
            (name, request.form.get('client',''), request.form.get('location',''),
             request.form.get('status','lead'), request.form.get('notes',''),
             session['user_id'])
        )
        db.commit()
        flash('Job created.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('new_job.html')

@app.route('/jobs/<int:job_id>/status', methods=['POST'])
@admin_required
def update_status(job_id):
    status = request.form.get('status')
    valid = ['lead','estimated','sold','progress','complete']
    if status in valid:
        db = get_db()
        db.execute("UPDATE jobs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, job_id))
        db.commit()
    return redirect(request.referrer or url_for('dashboard'))

# ─────────────────────────────────────────────────────────────
# DOCUMENTS / PHOTOS
# ─────────────────────────────────────────────────────────────

@app.route('/jobs/<int:job_id>/upload', methods=['POST'])
@login_required
def upload_doc(job_id):
    db = get_db()
    job = db.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        abort(404)
    is_admin = session.get('role') == 'admin'
    doc_type = request.form.get('doc_type', 'photo')
    if doc_type != 'photo' and not is_admin:
        abort(403)
    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('job_detail', job_id=job_id))
    original_name = secure_filename(file.filename)
    file_data = file.read()
    if len(file_data) > MAX_FILE_MB * 1024 * 1024:
        flash(f'File too large (max {MAX_FILE_MB}MB).', 'error')
        return redirect(url_for('job_detail', job_id=job_id))
    mime = file.content_type or 'application/octet-stream'
    db.execute(
        "INSERT INTO documents (job_id,original_name,doc_type,file_data,mime_type,file_size,uploaded_by) "
        "VALUES (?,?,?,?,?,?,?)",
        (job_id, original_name, doc_type, file_data, mime, len(file_data), session['user_id'])
    )
    db.commit()
    flash('File uploaded successfully.', 'success')
    return redirect(url_for('job_detail', job_id=job_id))

@app.route('/docs/<int:doc_id>')
@login_required
def download_doc(doc_id):
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        abort(404)
    is_admin = session.get('role') == 'admin'
    if doc['doc_type'] in ('financial','other') and not is_admin:
        abort(403)
    return send_file(
        io.BytesIO(doc['file_data']),
        mimetype=doc['mime_type'],
        as_attachment=False,
        download_name=doc['original_name']
    )

@app.route('/docs/<int:doc_id>/delete', methods=['POST'])
@admin_required
def delete_doc(doc_id):
    db = get_db()
    doc = db.execute("SELECT job_id FROM documents WHERE id=?", (doc_id,)).fetchone()
    if doc:
        job_id = doc['job_id']
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        db.commit()
        flash('File deleted.', 'success')
        return redirect(url_for('job_detail', job_id=job_id))
    abort(404)

# ─────────────────────────────────────────────────────────────
# FIELD VIEW
# ─────────────────────────────────────────────────────────────

@app.route('/field')
@login_required
def field():
    db = get_db()
    jobs = db.execute(
        "SELECT * FROM jobs WHERE status IN ('sold','progress') ORDER BY updated_at DESC"
    ).fetchall()
    return render_template('field.html', jobs=jobs)

# ─────────────────────────────────────────────────────────────
# ESTIMATOR
# ─────────────────────────────────────────────────────────────

def get_pricing_map(db):
    rows = db.execute("SELECT name, value FROM pricing").fetchall()
    return {r['name']: r['value'] for r in rows}

def pipe_cost(size, material, length_ft, qty, pm):
    """Calculate pipe cost for a pole given size, material, length, qty."""
    if not size or not length_ft or not qty:
        return 0
    length_ft = float(length_ft)
    qty = int(qty)
    # Find best stock lengths for this pipe type
    options = []
    if '4x' in size:
        wall = material  # wall thickness stored in material field for square tubing
        prefix = size + ' ' + wall + ' '
        for stick_len in [20, 24, 40, 48]:
            key = prefix + str(stick_len) + 'ft'
            if key in pm and pm[key] > 0:
                options.append((stick_len, pm[key]))
    elif 'OD Galv' in size:
        key = size + ' 24ft'
        if key in pm and pm[key] > 0:
            options.append((24, pm[key]))
    else:
        mat_label = 'Galv' if material == 'Galvanized' else 'Black'
        for stick_len in [21, 24, 40, 42, 48]:
            key = size + ' ' + mat_label + ' ' + str(stick_len) + 'ft'
            if key in pm and pm[key] > 0:
                options.append((stick_len, pm[key]))
    if not options:
        return 0
    # Choose most cost-efficient stock length
    best_cost = None
    for stick_len, price in options:
        sticks_per_pole = math.ceil(length_ft / stick_len)
        cost_per_pole = sticks_per_pole * price
        if best_cost is None or cost_per_pole < best_cost:
            best_cost = cost_per_pole
    return (best_cost or 0) * qty

def powder_cost_for_poles(poles, pm):
    total = 0
    powder_map = {
        '5" SCH40': pm.get('5" SCH40', 0),
        '6" SCH40': pm.get('6" SCH40', 0),
        '8" SCH40': pm.get('8" SCH40', 0),
        '3" OD Galv Tubing': pm.get('3" OD Galv', 0),
        '4" OD Galv Tubing': pm.get('4" OD Galv', 0),
        '5" OD Galv Tubing': pm.get('5" OD Galv', 0),
        '4x4': pm.get('4x4 HSS', 0),
        '4x6': pm.get('4x6 HSS', 0),
        '4x8': pm.get('4x8 HSS', 0),
    }
    for p in poles:
        size = p.get('size', '')
        length = float(p.get('length', 0) or 0)
        qty = int(p.get('qty', 0) or 0)
        rate = powder_map.get(size, 0)
        total += rate * length * qty
    return total

@app.route('/estimator', methods=['GET'])
@admin_required
def estimator():
    db = get_db()
    pm = get_pricing_map(db)
    return render_template('estimator.html', pm=pm)

@app.route('/estimator/calculate', methods=['POST'])
@admin_required
def calculate():
    db = get_db()
    pm = get_pricing_map(db)
    f = request.form

    # ── Job Info ──
    job_name     = f.get('job_name', '')
    client       = f.get('client', '')
    location     = f.get('location', '')
    sq_quote_amt = float(f.get('sq_quote_amount', 0) or 0)

    # ── Fabric ──
    total_sqft = float(f.get('total_sqft', 0) or 0)
    fabric_rate = pm.get('Cost per Sq Ft', 3.25)
    fabric_cost = total_sqft * fabric_rate

    # ── Sail Poles ──
    sail_sizes    = f.getlist('sail_size[]')
    sail_mats     = f.getlist('sail_material[]')
    sail_lengths  = f.getlist('sail_length[]')
    sail_qtys     = f.getlist('sail_qty[]')
    sail_attaches = f.getlist('sail_attach[]')
    sail_poles = []
    sail_pipe_cost = 0
    weld_lug_count = 0
    all_thread_count = 0
    for i in range(len(sail_sizes)):
        sz = sail_sizes[i] if i < len(sail_sizes) else ''
        mat = sail_mats[i] if i < len(sail_mats) else ''
        ln = sail_lengths[i] if i < len(sail_lengths) else 0
        qt = sail_qtys[i] if i < len(sail_qtys) else 0
        at = sail_attaches[i] if i < len(sail_attaches) else ''
        c = pipe_cost(sz, mat, ln, qt, pm)
        sail_pipe_cost += c
        sail_poles.append({'size': sz, 'length': ln, 'qty': qt})
        if at == 'Weld Lug':
            weld_lug_count += int(qt or 0)
        elif at == 'All Thread':
            all_thread_count += int(qt or 0)

    # Attach hardware costs
    weld_lug_unit = pm.get('Weld Lug', 0)
    all_thread_unit = pm.get('All Thread', 0)
    attach_cost = (weld_lug_count * weld_lug_unit) + (all_thread_count * all_thread_unit)

    # Welding cost (sail weld lugs)
    welding_rate = pm.get('Welding Rate', 95)
    welding_cost = weld_lug_count * welding_rate

    # ── Hip Poles ──
    hip_sizes   = f.getlist('hip_size[]')
    hip_mats    = f.getlist('hip_material[]')
    hip_lengths = f.getlist('hip_length[]')
    hip_qtys    = f.getlist('hip_qty[]')
    hip_poles = []
    hip_pipe_cost = 0
    for i in range(len(hip_sizes)):
        sz = hip_sizes[i] if i < len(hip_sizes) else ''
        mat = hip_mats[i] if i < len(hip_mats) else ''
        ln = hip_lengths[i] if i < len(hip_lengths) else 0
        qt = hip_qtys[i] if i < len(hip_qtys) else 0
        c = pipe_cost(sz, mat, ln, qt, pm)
        hip_pipe_cost += c
        hip_poles.append({'size': sz, 'length': ln, 'qty': qt})

    # ── Cantilever Posts ──
    cp_sizes   = f.getlist('cp_size[]')
    cp_walls   = f.getlist('cp_wall[]')
    cp_lengths = f.getlist('cp_length[]')
    cp_qtys    = f.getlist('cp_qty[]')
    cp_poles = []
    cp_pipe_cost = 0
    cant_post_qty_total = 0
    for i in range(len(cp_sizes)):
        sz = cp_sizes[i] if i < len(cp_sizes) else ''
        wl = cp_walls[i] if i < len(cp_walls) else ''
        ln = cp_lengths[i] if i < len(cp_lengths) else 0
        qt = cp_qtys[i] if i < len(cp_qtys) else 0
        c = pipe_cost(sz, wl, ln, qt, pm)
        cp_pipe_cost += c
        cp_poles.append({'size': sz, 'length': ln, 'qty': qt})
        cant_post_qty_total += int(qt or 0)

    # ── Cantilever Beams ──
    cb_sizes   = f.getlist('cb_size[]')
    cb_walls   = f.getlist('cb_wall[]')
    cb_lengths = f.getlist('cb_length[]')
    cb_qtys    = f.getlist('cb_qty[]')
    cb_poles = []
    cb_pipe_cost = 0
    cant_beam_qty_total = 0
    for i in range(len(cb_sizes)):
        sz = cb_sizes[i] if i < len(cb_sizes) else ''
        wl = cb_walls[i] if i < len(cb_walls) else ''
        ln = cb_lengths[i] if i < len(cb_lengths) else 0
        qt = cb_qtys[i] if i < len(cb_qtys) else 0
        c = pipe_cost(sz, wl, ln, qt, pm)
        cb_pipe_cost += c
        cb_poles.append({'size': sz, 'length': ln, 'qty': qt})
        cant_beam_qty_total += int(qt or 0)

    # Welding cost for cantilever posts + beams
    welding_cost += (cant_post_qty_total + cant_beam_qty_total) * welding_rate

    # ── Hardware ──
    wall_mount_qty = int(f.get('wall_mount_qty', 0) or 0)
    clamp_qty      = int(f.get('clamp_qty', 0) or 0)
    wall_mount_cost = wall_mount_qty * pm.get('Wall Mount', 0)
    clamp_cost      = clamp_qty * pm.get('Clamp', 0)

    # ── Steel/Pipe Total ──
    steel_total = sail_pipe_cost + hip_pipe_cost + cp_pipe_cost + cb_pipe_cost + wall_mount_cost + clamp_cost + attach_cost

    # ── Powder Coating ──
    all_poles = sail_poles + hip_poles + cp_poles + cb_poles
    powder_total = powder_cost_for_poles(all_poles, pm)

    # ── Concrete ──
    concrete_cy = float(f.get('concrete_cy', 0) or 0)
    concrete_cost = concrete_cy * pm.get('Price per CY', 200) * 1.1

    # ── Labor ──
    crew_size = int(f.get('crew_size', 1) or 1)
    install_days = float(f.get('install_days', 1) or 1)
    daily_cost = 0
    for i in range(1, crew_size + 1):
        key = f'Rate - Person {i}'
        daily_cost += pm.get(key, 400)
    labor_cost = daily_cost * install_days

    # ── Travel ──
    miles = float(f.get('miles', 0) or 0)
    trips = int(f.get('trips', 1) or 1)
    fuel_rate = pm.get('Fuel Cost per Mile', 0.40)
    fuel_cost = miles * 2 * fuel_rate * trips
    lodging = float(f.get('lodging', 0) or 0)
    travel_total = fuel_cost + lodging

    # ── Other Costs ──
    equipment = float(f.get('equipment', 0) or 0)
    permit    = float(f.get('permit', 0) or 0)
    vendor    = float(f.get('vendor', 0) or 0)
    misc      = float(f.get('misc', 0) or 0)
    other_total = equipment + permit + vendor + misc

    # ── Materials Total ──
    materials_total = (sq_quote_amt + fabric_cost + concrete_cost +
                       steel_total + welding_cost + powder_total +
                       float(f.get('hardware_misc', 0) or 0) +
                       float(f.get('job_supplies', 0) or 0) +
                       float(f.get('galvanizing', 0) or 0))

    # ── Grand Total ──
    total_cost = materials_total + labor_cost + travel_total + other_total
    markup_pct = float(f.get('markup_pct', 50) or 50)
    markup_amt = total_cost * (markup_pct / 100)
    sell_price = total_cost + markup_amt

    estimate = {
        'job_name': job_name, 'client': client, 'location': location,
        'sq_quote_amt': sq_quote_amt,
        'fabric_cost': fabric_cost, 'concrete_cost': concrete_cost,
        'steel_total': steel_total, 'welding_cost': welding_cost,
        'powder_total': powder_total,
        'materials_total': materials_total,
        'labor_cost': labor_cost, 'travel_total': travel_total,
        'fuel_cost': fuel_cost, 'lodging': lodging,
        'other_total': other_total,
        'equipment': equipment, 'permit': permit, 'vendor': vendor, 'misc': misc,
        'total_cost': total_cost,
        'markup_pct': markup_pct, 'markup_amt': markup_amt,
        'sell_price': sell_price,
        'hardware_misc': float(f.get('hardware_misc', 0) or 0),
        'job_supplies': float(f.get('job_supplies', 0) or 0),
        'galvanizing': float(f.get('galvanizing', 0) or 0),
    }

    save_as_job = f.get('save_as_job')
    if save_as_job and job_name:
        db.execute(
            "INSERT INTO jobs (name,client,location,status,estimate_amount,estimate_data,created_by) "
            "VALUES (?,?,?,?,?,?,?)",
            (job_name, client, location, 'estimated', sell_price,
             json.dumps(dict(f)), session['user_id'])
        )
        db.commit()
        flash(f'Job "{job_name}" saved to the job board.', 'success')

    return render_template('estimate_result.html', e=estimate)

# ─────────────────────────────────────────────────────────────
# PRICING ADMIN
# ─────────────────────────────────────────────────────────────

@app.route('/pricing')
@admin_required
def pricing():
    db = get_db()
    rows = db.execute("SELECT * FROM pricing ORDER BY category, sort_order").fetchall()
    categories = {}
    for r in rows:
        categories.setdefault(r['category'], []).append(r)
    return render_template('pricing.html', categories=categories)

@app.route('/pricing/update', methods=['POST'])
@admin_required
def update_pricing():
    db = get_db()
    for key, val in request.form.items():
        if key.startswith('price_'):
            pid = int(key.split('_')[1])
            try:
                db.execute("UPDATE pricing SET value=? WHERE id=?", (float(val), pid))
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
    users = db.execute("SELECT id,username,name,role,must_change_password FROM users ORDER BY role,name").fetchall()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/<int:uid>/reset', methods=['POST'])
@admin_required
def reset_password(uid):
    new_pw = request.form.get('new_password', '')
    if len(new_pw) < 6:
        flash('Password must be at least 6 characters.', 'error')
        return redirect(url_for('admin_users'))
    db = get_db()
    db.execute("UPDATE users SET password_hash=?, must_change_password=1 WHERE id=?",
               (generate_password_hash(new_pw), uid))
    db.commit()
    flash('Password reset.', 'success')
    return redirect(url_for('admin_users'))

# ─────────────────────────────────────────────────────────────
# ERROR PAGES
# ─────────────────────────────────────────────────────────────

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, msg="You don't have permission to view this page."), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, msg="Page not found."), 404

# ─────────────────────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────────────────────

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
