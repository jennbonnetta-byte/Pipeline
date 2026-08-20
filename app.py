from flask import Flask, render_template, request, redirect, url_for, session
import os
import json
import re
import time
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader

app = Flask(__name__)
app.secret_key = os.environ.get('PIPELINE_SECRET_KEY')

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- PASTE YOUR CLOUDINARY KEYS HERE ---
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(DATABASE_URL)


def get_user_by_username(username):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username,)
        )
        row = cur.fetchone()
        cur.close()
        return row
    finally:
        conn.close()


def create_user(username, password_hash):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
            (username, password_hash)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return user_id
    finally:
        conn.close()


def get_user_jobs(user_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, date, hours, notes, destination, materials, photos
               FROM jobs
               WHERE user_id = %s
               ORDER BY id DESC""",
            (user_id,)
        )
        rows = cur.fetchall()
        cur.close()

        return [
            {
                "id": row[0],
                "date": row[1],
                "hours": row[2],
                "notes": row[3],
                "destination": row[4],
                "materials": row[5],
                "photos": row[6] or []
            }
            for row in rows
        ]
    finally:
        conn.close()


def save_job(user_id, job):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO jobs
               (user_id, date, hours, notes, destination, materials, photos)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                user_id,
                job.get("date"),
                job.get("hours"),
                job.get("notes"),
                job.get("destination"),
                job.get("materials"),
                json.dumps(job.get("photos", []))
            )
        )
        job_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return job_id
    finally:
        conn.close()



def upload_to_cloudinary(files_list):
    urls = []
    for f in files_list:
        if f and f.filename and f.filename.strip() != '':
            try:
                temp_filename = f"temp_{int(time.time())}_{f.filename}"
                temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
                f.save(temp_path)
                
                response = cloudinary.uploader.upload(temp_path)
                if 'secure_url' in response:
                    urls.append(response['secure_url'])
                
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception as e:
                print(f"❌ CLOUDINARY UPLOAD ERROR: {e}")
    return urls

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

        if not username or not password:
            error = 'Please enter your username and password.'
        else:
            user = get_user_by_username(username)

            if user and check_password_hash(user[2], password):
                session['user_id'] = user[0]
                session['user'] = user[1]
                return redirect(url_for('home'))

            error = 'Invalid username or password.'

    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not username or not password or not confirm_password:
            error = 'Please fill out all fields.'
        elif len(username) < 3:
            error = 'Username must be at least 3 characters.'
        elif len(password) < 8:
            error = 'Password must be at least 8 characters.'
        elif password != confirm_password:
            error = 'Passwords do not match.'
        elif get_user_by_username(username):
            error = 'Username already exists.'
        else:
            password_hash = generate_password_hash(password)
            user_id = create_user(username, password_hash)

            session['user_id'] = user_id
            session['user'] = username

            return redirect(url_for('home'))

    return render_template('register.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- APP ROUTES (Protected) ---
@app.route('/')
def home():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('home.html')

@app.route('/entry', methods=['GET', 'POST'])
def index():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        photo_urls = upload_to_cloudinary(request.files.getlist('photos'))
        job = {
            'user': session['user'],
            'date': request.form.get('date'),
            'hours': request.form.get('hours'),
            'notes': request.form.get('notes'),
            'destination': request.form.get('destination'),
            'materials': request.form.get('materials'),
            'photos': photo_urls
        }
        save_job(session['user_id'], job)
        return redirect(url_for('report'))
    return render_template('index.html')

def get_job_by_id(user_id, job_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, date, hours, notes, destination, materials, photos
               FROM jobs
               WHERE id = %s AND user_id = %s""",
            (job_id, user_id)
        )
        row = cur.fetchone()
        cur.close()

        if not row:
            return None

        return {
            "id": row[0],
            "date": row[1],
            "hours": row[2],
            "notes": row[3],
            "destination": row[4],
            "materials": row[5],
            "photos": row[6] or []
        }
    finally:
        conn.close()


def update_job(user_id, job_id, job):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE jobs
               SET date = %s,
                   hours = %s,
                   notes = %s,
                   destination = %s,
                   materials = %s,
                   photos = %s
               WHERE id = %s AND user_id = %s""",
            (
                job.get("date"),
                job.get("hours"),
                job.get("notes"),
                job.get("destination"),
                job.get("materials"),
                json.dumps(job.get("photos", [])),
                job_id,
                user_id
            )
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def delete_job_from_db(user_id, job_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM jobs WHERE id = %s AND user_id = %s",
            (job_id, user_id)
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


@app.route('/report')
def report():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    history = get_user_jobs(session['user_id'])
    job = history[0] if history else {}

    return render_template(
        'report.html',
        job=job,
        job_index=0 if history else None
    )


@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_history = get_user_jobs(session['user_id'])

    return render_template(
        'history.html',
        history=user_history
    )


@app.route('/weekly')
def weekly():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    history_data = get_user_jobs(session['user_id'])

    total_hours = sum(
        float(re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0)))[0])
        if re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0)))
        else 0
        for j in history_data
    )

    return render_template(
        'weekly.html',
        history=history_data,
        total_hours=total_hours
    )


@app.route('/weekly-report')
def weekly_report():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    history_data = get_user_jobs(session['user_id'])

    total_hours = sum(
        float(re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0)))[0])
        if re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0)))
        else 0
        for j in history_data
    )

    return render_template(
        'weekly_report.html',
        history=history_data,
        total_hours=total_hours
    )


@app.route('/gallery')
def gallery():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_history = get_user_jobs(session['user_id'])

    return render_template(
        'gallery.html',
        history=user_history
    )


@app.route('/job-photos/<int:job_id>')
def job_photos(job_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    job = get_job_by_id(session['user_id'], job_id)

    if job:
        return render_template(
            'job_photos.html',
            job=job
        )

    return redirect(url_for('history'))


@app.route('/delete/<int:job_id>', methods=['POST'])
def delete_job(job_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    delete_job_from_db(
        session['user_id'],
        job_id
    )

    return redirect(url_for('history'))


@app.route('/edit/<int:job_id>', methods=['GET', 'POST'])
def edit_job(job_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    target_job = get_job_by_id(
        session['user_id'],
        job_id
    )

    if not target_job:
        return redirect(url_for('history'))

    if request.method == 'POST':
        target_job.update({
            k: request.form.get(k)
            for k in [
                'date',
                'hours',
                'destination',
                'notes',
                'materials'
            ]
        })

        new_urls = upload_to_cloudinary(
            request.files.getlist('photos')
        )

        target_job['photos'] = (
            target_job.get('photos', [])
            + new_urls
        )

        update_job(
            session['user_id'],
            job_id,
            target_job
        )

        return redirect(url_for('history'))

    return render_template(
        'edit.html',
        job=target_job
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
