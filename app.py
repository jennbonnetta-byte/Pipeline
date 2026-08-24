from flask import Flask, render_template, request, redirect, url_for, session, make_response
import os
import json
import re
import time
import psycopg2
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage
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

# --- PIPELINE_DEV_BANNER ---
@app.after_request
def add_dev_environment_banner(response):
    """Show a clear warning when running the development environment."""
    if os.environ.get("PIPELINE_ENV") != "development":
        return response

    if "text/html" not in response.headers.get("Content-Type", ""):
        return response

    try:
        html = response.get_data(as_text=True)

        banner = """
<style id="pipeline-dev-banner-style">
    #pipeline-dev-banner {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 2147483647;
        background: #b45309;
        color: #ffffff;
        text-align: center;
        padding: 8px 12px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: .3px;
        box-shadow: 0 2px 8px rgba(0,0,0,.3);
    }

    body {
        padding-top: 36px !important;
    }
</style>

<div id="pipeline-dev-banner">
    🛠️ DEVELOPMENT ENVIRONMENT — PIPELINE DEV HUB — PRODUCTION IS NOT AFFECTED
</div>
"""

        closing_body = html.lower().rfind("</body>")

        if closing_body == -1:
            return response

        html = html[:closing_body] + banner + html[closing_body:]
        response.set_data(html)

    except Exception:
        return response

    return response
# --- END PIPELINE_DEV_BANNER ---



@app.context_processor
def inject_appearance():
    """Make appearance settings available to every template."""
    defaults = {
        "theme": "light",
        "accent_color": "blue",
        "layout_density": "comfortable",
        "card_style": "rounded",
        "font_size": "default",
        "animations": True,
        "dashboard_layout": "standard"
    }

    user_id = session.get("user_id")

    if not user_id:
        return {"appearance": defaults}

    conn = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """SELECT
                   theme,
                   accent_color,
                   layout_density,
                   card_style,
                   font_size,
                   animations,
                   dashboard_layout
               FROM appearance_settings
               WHERE user_id = %s""",
            (user_id,)
        )

        row = cur.fetchone()
        cur.close()

        if not row:
            return {"appearance": defaults}

        settings = {
            "theme": row[0] or defaults["theme"],
            "accent_color": row[1] or defaults["accent_color"],
            "layout_density": row[2] or defaults["layout_density"],
            "card_style": row[3] or defaults["card_style"],
            "font_size": row[4] or defaults["font_size"],
            "animations": (
                row[5]
                if row[5] is not None
                else defaults["animations"]
            ),
            "dashboard_layout": (
                row[6]
                or defaults["dashboard_layout"]
            )
        }

        return {"appearance": settings}

    except Exception:
        # Never let appearance preferences break the app.
        return {"appearance": defaults}

    finally:
        if conn:
            conn.close()


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")

    conn = psycopg2.connect(DATABASE_URL)

    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'America/Toronto'")

    return conn


def get_user_by_username(username):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, role FROM users WHERE LOWER(username) = LOWER(%s)",
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
            """
            SELECT
                j.id,
                j.date,
                j.hours,
                j.start_time,
                j.end_time,
                j.notes,
                j.destination,
                j.materials,
                j.photos,
                j.client_id,
                c.name,
                c.contact_person,
                c.phone,
                c.email,
                c.address,
                c.city,
                c.province,
                c.postal_code
            FROM jobs j
            LEFT JOIN clients c
                ON j.client_id = c.id
                AND c.user_id = %s
            WHERE j.user_id = %s
            ORDER BY j.id DESC
            """,
            (user_id, user_id)
        )

        rows = cur.fetchall()
        cur.close()

        return [
            {
                "id": row[0],
                "date": row[1],
                "hours": row[2],
                "start_time": row[3],
                "end_time": row[4],
                "notes": row[5],
                "destination": row[6],
                "materials": row[7],
                "photos": row[8] or [],
                "client_id": row[9],
                "client_name": row[10],
                "client_contact": row[11],
                "client_phone": row[12],
                "client_email": row[13],
                "client_address": row[14],
                "client_city": row[15],
                "client_province": row[16],
                "client_postal_code": row[17]
            }
            for row in rows
        ]

    finally:
        conn.close()



def get_current_week_jobs(user_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, date, hours, notes, destination, materials, photos
               FROM jobs
               WHERE user_id = %s
                 AND date::date >= DATE_TRUNC('week', CURRENT_DATE)::date
                 AND date::date < (DATE_TRUNC('week', CURRENT_DATE) + INTERVAL '7 days')::date
               ORDER BY date DESC, id DESC""",
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


def get_report_period_info(user_id, period):
    from datetime import date, timedelta

    today = date.today()

    if period == "daily":
        return {
            "start": today,
            "end": today,
            "payday": None
        }

    if period == "weekly":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return {
            "start": start,
            "end": end,
            "payday": None
        }

    if period == "monthly":
        start = today.replace(day=1)

        if start.month == 12:
            next_month = start.replace(
                year=start.year + 1,
                month=1,
                day=1
            )
        else:
            next_month = start.replace(
                month=start.month + 1,
                day=1
            )

        end = next_month - timedelta(days=1)

        return {
            "start": start,
            "end": end,
            "payday": None
        }

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            """SELECT payday_anchor_date
               FROM pay_settings
               WHERE user_id = %s""",
            (user_id,)
        )

        row = cur.fetchone()

        anchor = (
            row[0]
            if row and row[0]
            else date(2026, 8, 27)
        )

        # Find the nearest payday on or after today.
        if today <= anchor:
            next_payday = anchor
        else:
            days_since_anchor = (today - anchor).days
            cycles = days_since_anchor // 14
            next_payday = anchor + timedelta(
                days=(cycles + 1) * 14
            )

            if next_payday < today:
                next_payday += timedelta(days=14)

        # The current period ends on the next payday.
        end = next_payday
        start = end - timedelta(days=13)

        return {
            "start": start,
            "end": end,
            "payday": next_payday
        }

    finally:
        conn.close()


def get_report_period_jobs(user_id, period):
    conn = get_db()

    try:
        cur = conn.cursor()

        if period == "daily":
            date_condition = """
                AND j.date::date = CURRENT_DATE
            """
            params = (user_id, user_id)

        elif period == "monthly":
            date_condition = """
                AND j.date::date >= DATE_TRUNC(
                    'month', CURRENT_DATE
                )::date
                AND j.date::date < (
                    DATE_TRUNC(
                        'month', CURRENT_DATE
                    ) + INTERVAL '1 month'
                )::date
            """
            params = (user_id, user_id)

        elif period == "biweekly":
            cur.execute(
                """SELECT payday_anchor_date
                   FROM pay_settings
                   WHERE user_id = %s""",
                (user_id,)
            )

            settings_row = cur.fetchone()

            if settings_row and settings_row[0]:
                anchor = settings_row[0]
            else:
                anchor = "2026-08-27"

            date_condition = """
                AND j.date::date >= (
                    %s::date
                    - (
                        (
                            FLOOR(
                                (
                                    %s::date - CURRENT_DATE
                                ) / 14.0
                            ) + 1
                        ) * 14
                    )::integer
                )
                AND j.date::date < (
                    %s::date
                    - (
                        (
                            FLOOR(
                                (
                                    %s::date - CURRENT_DATE
                                ) / 14.0
                            )
                        ) * 14
                    )::integer
                )
            """

            params = (
                user_id,
                user_id,
                anchor,
                anchor,
                anchor,
                anchor
            )

        else:
            date_condition = """
                AND j.date::date >= DATE_TRUNC(
                    'week', CURRENT_DATE
                )::date
                AND j.date::date < (
                    DATE_TRUNC(
                        'week', CURRENT_DATE
                    ) + INTERVAL '7 days'
                )::date
            """
            params = (user_id, user_id)

        query = f"""
            SELECT
                j.id,
                j.date,
                j.hours,
                j.start_time,
                j.end_time,
                j.notes,
                j.destination,
                j.materials,
                j.photos,
                j.client_id,
                c.name,
                c.contact_person,
                c.phone,
                c.email,
                c.address,
                c.city,
                c.province,
                c.postal_code
            FROM jobs j
            LEFT JOIN clients c
              ON j.client_id = c.id
             AND c.user_id = %s
            WHERE j.user_id = %s
            {date_condition}
            ORDER BY j.date DESC, j.id DESC
        """

        cur.execute(query, params)
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
                "photos": row[6] or [],
                "client_id": row[7],
                "client_name": row[8],
                "client_contact": row[9],
                "client_phone": row[10],
                "client_email": row[11],
                "client_address": row[12],
                "client_city": row[13],
                "client_province": row[14],
                "client_postal_code": row[15]
            }
            for row in rows
        ]

    finally:
        conn.close()

def save_job(user_id, job):
    conn = get_db()
    try:
        cur = conn.cursor()

        start_time = job.get("start_time") or None
        end_time = job.get("end_time") or None

        # Calculate hours on the server so payroll cannot rely
        # on a client-supplied hidden field.
        calculated_hours = job.get("hours")

        if start_time and end_time:
            start_parts = [int(x) for x in start_time.split(":")]
            end_parts = [int(x) for x in end_time.split(":")]

            start_minutes = start_parts[0] * 60 + start_parts[1]
            end_minutes = end_parts[0] * 60 + end_parts[1]

            # Allow an overnight service call.
            if end_minutes < start_minutes:
                end_minutes += 24 * 60

            calculated_hours = f"{(end_minutes - start_minutes) / 60:.2f}"

        cur.execute(
            """INSERT INTO jobs
               (user_id, date, hours, start_time, end_time,
                notes, destination, materials, photos, client_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                user_id,
                job.get("date"),
                calculated_hours,
                start_time,
                end_time,
                job.get("notes"),
                job.get("destination"),
                job.get("materials"),
                json.dumps(job.get("photos", [])),
                job.get("client_id") or None
            )
        )

        job_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return job_id
    finally:
        conn.close()




def get_appearance_settings(user_id):
    defaults = {
        "theme": "light",
        "accent_color": "blue",
        "layout_density": "comfortable",
        "card_style": "rounded",
        "font_size": "default",
        "animations": True,
        "dashboard_layout": "standard"
    }

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            """SELECT
                   theme,
                   accent_color,
                   layout_density,
                   card_style,
                   font_size,
                   animations,
                   dashboard_layout
               FROM appearance_settings
               WHERE user_id = %s""",
            (user_id,)
        )

        row = cur.fetchone()
        cur.close()

        if not row:
            return defaults

        return {
            "theme": row[0] or defaults["theme"],
            "accent_color": row[1] or defaults["accent_color"],
            "layout_density": row[2] or defaults["layout_density"],
            "card_style": row[3] or defaults["card_style"],
            "font_size": row[4] or defaults["font_size"],
            "animations": row[5] if row[5] is not None else defaults["animations"],
            "dashboard_layout": row[6] or defaults["dashboard_layout"]
        }

    finally:
        conn.close()


def get_email_settings():
    return {
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "username": os.environ.get("SMTP_USERNAME"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "boss_email": os.environ.get("BOSS_EMAIL"),
    }


def cloudinary_jpeg_url(url):
    """
    Convert a Cloudinary image URL to a browser/email-friendly JPEG URL.
    This is especially useful for HEIC uploads.
    """
    if not url:
        return url

    if ".heic" in url.lower():
        return url.replace(
            "/image/upload/",
            "/image/upload/f_jpg/"
        )

    return url


def download_photo(url):
    """
    Download a Cloudinary photo and return:
    (filename, bytes)
    """
    jpeg_url = cloudinary_jpeg_url(url)

    req = urllib.request.Request(
        jpeg_url,
        headers={"User-Agent": "PipeLine/1.0"}
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read()

    return jpeg_url, data


def send_email_with_attachments(
    subject,
    body,
    photo_urls=None,
    recipient=None
):
    settings = get_email_settings()

    if not settings["username"]:
        raise RuntimeError(
            "SMTP_USERNAME is not configured."
        )

    if not settings["password"]:
        raise RuntimeError(
            "SMTP_PASSWORD is not configured."
        )

    if not recipient:
        raise RuntimeError(
            "A recipient email address is required."
        )

    msg = EmailMessage()

    msg["From"] = settings["username"]
    msg["To"] = recipient
    msg["Subject"] = subject

    msg.set_content(body)

    attachment_errors = []
    attached_count = 0

    for number, url in enumerate(photo_urls or [], start=1):
        try:
            jpeg_url, photo_data = download_photo(url)

            filename = f"PipeLine_Photo_{number}.jpg"

            msg.add_attachment(
                photo_data,
                maintype="image",
                subtype="jpeg",
                filename=filename
            )

            attached_count += 1

        except Exception as e:
            error = (
                f"Photo {number} could not be attached: {e}"
            )
            print(f"❌ {error}")
            attachment_errors.append(error)

    if attachment_errors:
        raise RuntimeError(
            "One or more photos could not be attached. "
            "The email was not sent. "
            + " | ".join(attachment_errors)
        )

    context = ssl.create_default_context()

    with smtplib.SMTP(
        settings["host"],
        settings["port"],
        timeout=30
    ) as server:

        server.starttls(context=context)

        server.login(
            settings["username"],
            settings["password"]
        )

        server.send_message(msg)

    return attached_count

def build_daily_email(job):
    photos = job.get("photos") or []

    subject = (
        "PipeLine Daily Report - "
        f"{job.get('date', '')} - "
        f"{job.get('destination', '')}"
    )

    body = f"""PipeLine Daily Report

Date: {job.get('date', '')}
Hours: {job.get('hours', '')}
Job / Destination: {job.get('destination', '')}

WORK PERFORMED
{job.get('notes', '')}

MATERIALS USED
{job.get('materials', '')}

Job Photos: {len(photos)}

Sent from PipeLine
"""

    return subject, body, photos


def build_weekly_email(history, total_hours):
    subject = "PipeLine Weekly Boss Report"

    lines = [
        "PipeLine Weekly Boss Report",
        "",
        f"TOTAL HOURS: {total_hours}",
        "",
        "JOB BREAKDOWN",
        "==============",
        ""
    ]

    all_photos = []

    for number, job in enumerate(history, start=1):

        photos = job.get("photos") or []

        lines.extend([
            f"JOB {number}",
            f"Date: {job.get('date', '')}",
            f"Hours: {job.get('hours', '')}",
            f"Job / Destination: {job.get('destination', '')}",
            "",
            "WORK PERFORMED",
            job.get("notes", "") or "",
            "",
            "MATERIALS USED",
            job.get("materials", "") or "",
            "",
            f"Photos: {len(photos)}",
            "",
            "--------------------",
            ""
        ])

        all_photos.extend(photos)

    lines.append("Sent from PipeLine")

    return subject, "\n".join(lines), all_photos


def upload_to_cloudinary(files_list):
    urls = []
    for f in files_list:
        if f and f.filename and f.filename.strip() != '':
            try:
                temp_filename = f"temp_{int(time.time())}_{f.filename}"
                temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
                f.save(temp_path)
                
                response = cloudinary.uploader.upload(temp_path, format='jpg')
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
                session['role'] = user[3] or 'employee'
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
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Owners use the Owner Hub; employees keep the existing dashboard.
    if session.get('role') == 'owner':
        return redirect(url_for('owner_dashboard'))

    # Respect the user's Dashboard Recent Jobs preference.
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT dashboard_recent_jobs FROM app_settings WHERE user_id = %s",
            (session['user_id'],)
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    recent_job_count = (row[0] if row and row[0] else 3)
    recent_job_count = max(1, min(int(recent_job_count), 10))

    recent_jobs = get_user_jobs(session['user_id'])[:recent_job_count]
    appearance = get_appearance_settings(session['user_id'])

    return render_template(
        'home.html',
        recent_jobs=recent_jobs,
        appearance=appearance
    )

@app.route('/entry', methods=['GET', 'POST'])
def index():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        photo_urls = upload_to_cloudinary(
            request.files.getlist('photos')
        )

        client_id = request.form.get('client_id') or None

        job = {
            'user': session['user'],
            'date': request.form.get('date'),
            'hours': request.form.get('hours'),
            'start_time': request.form.get('start_time'),
            'end_time': request.form.get('end_time'),
            'notes': request.form.get('notes'),
            'destination': request.form.get('destination'),
            'materials': request.form.get('materials'),
            'photos': photo_urls,
            'client_id': client_id
        }

        save_job(session['user_id'], job)

        # Remember job-entry values when enabled.
        conn_pref = get_db()
        try:
            cur_pref = conn_pref.cursor()
            cur_pref.execute(
                "SELECT remember_last_job_values FROM app_settings "
                "WHERE user_id = %s",
                (session['user_id'],)
            )
            pref_row = cur_pref.fetchone()
            cur_pref.close()
        finally:
            conn_pref.close()

        remember_values = (
            pref_row[0]
            if pref_row and pref_row[0] is not None
            else True
        )

        if remember_values:
            session['last_job_values'] = {
                'hours': request.form.get('hours', ''),
                'client_id': request.form.get('client_id', ''),
                'destination': request.form.get('destination', ''),
                'notes': request.form.get('notes', ''),
                'materials': request.form.get('materials', '')
            }
        else:
            session.pop('last_job_values', None)

        return redirect(url_for('report'))

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT id, name, contact_person, phone, email, "
            "address, city, province, postal_code "
            "FROM clients "
            "WHERE user_id = %s "
            "ORDER BY name ASC",
            (session['user_id'],)
        )

        rows = cur.fetchall()
        cur.close()

        clients = [
            {
                'id': row[0],
                'name': row[1],
                'contact_person': row[2],
                'phone': row[3],
                'email': row[4],
                'address': row[5],
                'city': row[6],
                'province': row[7],
                'postal_code': row[8]
            }
            for row in rows
        ]

    finally:
        conn.close()

    last_job_values = session.get('last_job_values', {})

    conn_pref = get_db()
    try:
        cur_pref = conn_pref.cursor()
        cur_pref.execute(
            "SELECT autosave_drafts "
            "FROM app_settings WHERE user_id = %s",
            (session['user_id'],)
        )
        autosave_row = cur_pref.fetchone()
        cur_pref.close()
    finally:
        conn_pref.close()

    autosave_drafts = (
        autosave_row[0]
        if autosave_row and autosave_row[0] is not None
        else True
    )

    return render_template(
        'index.html',
        clients=clients,
        last_job_values=last_job_values,
        settings_autosave_drafts=autosave_drafts
    )

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



@app.route('/send-daily-report/<int:job_id>', methods=['POST'])
def send_daily_report(job_id):

    if 'user_id' not in session:
        return redirect(url_for('login'))

    recipient = request.form.get(
        'recipient_email',
        ''
    ).strip().lower()

    if not recipient:
        return redirect(
            url_for(
                'report',
                job_id=job_id,
                error='recipient'
            )
        )

    if not re.match(
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        recipient
    ):
        return redirect(
            url_for(
                'report',
                job_id=job_id,
                error='recipient'
            )
        )

    job = get_job_by_id(
        session['user_id'],
        job_id
    )

    if not job:
        return redirect(url_for('history'))

    try:

        subject, body, photos = build_daily_email(job)

        attached_count = send_email_with_attachments(
            subject,
            body,
            photos,
            recipient=recipient
        )

        log_sent_report(
            user_id=session['user_id'],
            report_type='daily',
            recipient_email=recipient,
            subject=subject,
            job_ids=[job['id']],
            total_hours=float(
                re.findall(
                    r"[-+]?\d*\.?\d+",
                    str(job.get('hours', 0))
                )[0]
            ) if re.findall(
                r"[-+]?\d*\.?\d+",
                str(job.get('hours', 0))
            ) else 0,
            photo_count=attached_count,
            status='sent'
        )

        return redirect(
            url_for(
                'report',
                sent='daily'
            )
        )

    except Exception as e:

        print(
            f"❌ DAILY EMAIL ERROR: {e}"
        )

        return redirect(
            url_for(
                'report',
                error='email'
            )
        )


def log_sent_report(
    user_id,
    report_type,
    recipient_email,
    subject,
    job_ids,
    total_hours,
    photo_count,
    status="sent"
):
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            """INSERT INTO sent_reports
               (
                   user_id,
                   report_type,
                   recipient_email,
                   subject,
                   job_ids,
                   total_hours,
                   photo_count,
                   status
               )
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                user_id,
                report_type,
                recipient_email,
                subject,
                json.dumps(job_ids),
                total_hours,
                photo_count,
                status
            )
        )

        conn.commit()
        cur.close()

    finally:
        conn.close()


def get_sent_reports(user_id):
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            """SELECT
                   id,
                   report_type,
                   recipient_email,
                   subject,
                   job_ids,
                   total_hours,
                   photo_count,
                   sent_at,
                   status
               FROM sent_reports
               WHERE user_id = %s
               ORDER BY sent_at DESC""",
            (user_id,)
        )

        rows = cur.fetchall()
        cur.close()

        return [
            {
                "id": row[0],
                "report_type": row[1],
                "recipient_email": row[2],
                "subject": row[3],
                "job_ids": row[4] or [],
                "total_hours": row[5] or 0,
                "photo_count": row[6] or 0,
                "sent_at": row[7],
                "status": row[8]
            }
            for row in rows
        ]

    finally:
        conn.close()


@app.route('/sent-reports')
def sent_reports():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    reports = get_sent_reports(
        session['user_id']
    )

    return render_template(
        'sent_reports.html',
        reports=reports
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



def get_pay_settings(user_id):
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            """SELECT
                   regular_rate,
                   overtime_threshold,
                   overtime_multiplier,
                   doubletime_threshold,
                   doubletime_multiplier,
                   vacation_percent,
                   income_tax_type,
                   income_tax_value,
                   cpp_type,
                   cpp_value,
                   ei_type,
                   ei_value,
                   benefits_type,
                   benefits_value,
                   pension_type,
                   pension_value,
                   other_deductions_type,
                   other_deductions_value,
                   biweekly_start_date
               FROM pay_settings
               WHERE user_id = %s""",
            (user_id,)
        )

        row = cur.fetchone()
        cur.close()

        if not row:
            return {
                "regular_rate": 0,
                "overtime_threshold": 44,
                "overtime_multiplier": 1.5,
                "doubletime_threshold": 0,
                "doubletime_multiplier": 2,
                "vacation_percent": 0,
                "income_tax_type": "percent",
                "income_tax_value": 0,
                "cpp_type": "percent",
                "cpp_value": 0,
                "ei_type": "percent",
                "ei_value": 0,
                "benefits_type": "fixed",
                "benefits_value": 0,
                "pension_type": "percent",
                "pension_value": 0,
                "other_deductions_type": "fixed",
                "other_deductions_value": 0
            }

        return {
            "regular_rate": float(row[0] or 0),
            "overtime_threshold": float(row[1] or 44),
            "overtime_multiplier": float(row[2] or 1.5),
            "doubletime_threshold": float(row[3] or 0),
            "doubletime_multiplier": float(row[4] or 2),
            "vacation_percent": float(row[5] or 0),
            "income_tax_type": row[6] or "percent",
            "income_tax_value": float(row[7] or 0),
            "cpp_type": row[8] or "percent",
            "cpp_value": float(row[9] or 0),
            "ei_type": row[10] or "percent",
            "ei_value": float(row[11] or 0),
            "benefits_type": row[12] or "fixed",
            "benefits_value": float(row[13] or 0),
            "pension_type": row[14] or "percent",
            "pension_value": float(row[15] or 0),
            "other_deductions_type": row[16] or "fixed",
            "other_deductions_value": float(row[17] or 0)
        }

    finally:
        conn.close()



def get_payroll_daily_totals(user_id):
    """
    Return the current bi-weekly pay period as daily totals.

    Individual service calls remain separate jobs for Reports.
    Payroll groups all jobs on the same calendar date together.
    """
    from datetime import date, timedelta

    conn = get_db()

    try:
        cur = conn.cursor()

        # Get the configured payday anchor.
        cur.execute(
            """SELECT payday_anchor_date
               FROM pay_settings
               WHERE user_id = %s""",
            (user_id,)
        )

        row = cur.fetchone()

        anchor = row[0] if row and row[0] else date(2026, 8, 27)

        today = date.today()

        # Find the next payday on or after today.
        if today <= anchor:
            next_payday = anchor
        else:
            days_since_anchor = (today - anchor).days
            cycles = days_since_anchor // 14
            next_payday = anchor + timedelta(days=(cycles + 1) * 14)

        period_end = next_payday
        period_start = period_end - timedelta(days=13)

        # Get every service call in the pay period.
        cur.execute(
            """SELECT id, date, start_time, end_time, hours,
                      client_id, destination
               FROM jobs
               WHERE user_id = %s
                 AND date::date >= %s
                 AND date::date <= %s
               ORDER BY date::date ASC, start_time ASC NULLS LAST, id ASC""",
            (user_id, period_start, period_end)
        )

        rows = cur.fetchall()
        cur.close()

        # Create every calendar day in the period, including zero-hour days.
        daily = {}

        current = period_start

        while current <= period_end:
            daily[current] = {
                "date": current,
                "hours": 0.0,
                "jobs": []
            }
            current += timedelta(days=1)

        # Add each individual service call to its calendar day.
        for row in rows:
            job_id = row[0]
            job_date = row[1]

            # Normalize PostgreSQL date values and TEXT dates to datetime.date.
            if hasattr(job_date, "date"):
                job_date = job_date.date()
            elif isinstance(job_date, str):
                from datetime import date
                try:
                    job_date = date.fromisoformat(job_date[:10])
                except ValueError:
                    job_date = None

            if job_date is None:
                continue

            try:
                hours = float(row[4] or 0)
            except (TypeError, ValueError):
                hours = 0.0

            if job_date not in daily:
                daily[job_date] = {
                    "date": job_date,
                    "hours": 0.0,
                    "jobs": []
                }

            daily[job_date]["hours"] += hours
            daily[job_date]["jobs"].append({
                "id": job_id,
                "start_time": row[2],
                "end_time": row[3],
                "hours": hours,
                "client_id": row[5],
                "destination": row[6]
            })

        # Round daily totals to two decimals.
        daily_rows = []

        for day in sorted(daily):
            daily[day]["hours"] = round(daily[day]["hours"], 2)
            daily_rows.append(daily[day])

        total_hours = round(
            sum(day["hours"] for day in daily_rows),
            2
        )

        return {
            "start": period_start,
            "end": period_end,
            "payday": next_payday,
            "days": daily_rows,
            "total_hours": total_hours
        }

    finally:
        conn.close()



def get_daily_payroll(user_id, period):
    """Group individual service calls into daily payroll totals."""

    conn = get_db()

    try:
        cur = conn.cursor()

        if period == "daily":
            condition = """
                AND j.date::date = CURRENT_DATE
            """
            period_params = ()

        elif period == "weekly":
            condition = """
                AND j.date::date >= DATE_TRUNC('week', CURRENT_DATE)::date
                AND j.date::date < (
                    DATE_TRUNC('week', CURRENT_DATE) + INTERVAL '7 days'
                )::date
            """
            period_params = ()

        elif period == "monthly":
            condition = """
                AND j.date::date >= DATE_TRUNC('month', CURRENT_DATE)::date
                AND j.date::date < (
                    DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
                )::date
            """
            period_params = ()

        elif period == "biweekly":
            cur.execute(
                """
                SELECT payday_anchor_date
                FROM pay_settings
                WHERE user_id = %s
                """,
                (user_id,)
            )

            row = cur.fetchone()
            anchor = row[0] if row and row[0] else "2026-08-27"

            condition = """
                AND j.date::date >= (
                    %s::date -
                    (
                        FLOOR(
                            (%s::date - CURRENT_DATE) / 14.0
                        ) + 1
                    )::integer * 14
                )
                AND j.date::date < (
                    %s::date -
                    FLOOR(
                        (%s::date - CURRENT_DATE) / 14.0
                    )::integer * 14
                )
            """

            period_params = (
                anchor,
                anchor,
                anchor,
                anchor,
            )

        else:
            condition = """
                AND j.date::date >= DATE_TRUNC('week', CURRENT_DATE)::date
                AND j.date::date < (
                    DATE_TRUNC('week', CURRENT_DATE) + INTERVAL '7 days'
                )::date
            """
            period_params = ()

        query = f"""
            SELECT
                j.date::date,
                j.id,
                j.start_time,
                j.end_time,
                COALESCE(
                    NULLIF(j.hours, '')::numeric,
                    CASE
                        WHEN j.start_time IS NOT NULL
                         AND j.end_time IS NOT NULL
                        THEN EXTRACT(
                            EPOCH FROM (
                                j.end_time - j.start_time
                            )
                        ) / 3600
                        ELSE 0
                    END
                ) AS calculated_hours,
                j.destination,
                c.name
            FROM jobs j
            LEFT JOIN clients c
                ON j.client_id = c.id
                AND c.user_id = %s
            WHERE j.user_id = %s
            {condition}
            ORDER BY j.date ASC, j.start_time ASC, j.id ASC
        """

        params = (user_id, user_id) + period_params

        cur.execute(query, params)

        rows = cur.fetchall()
        cur.close()

        days = {}

        for row in rows:
            day_date = row[0]
            job_hours = float(row[4] or 0)

            if day_date not in days:
                days[day_date] = {
                    "date": day_date,
                    "hours": 0,
                    "jobs": []
                }

            days[day_date]["hours"] += job_hours

            days[day_date]["jobs"].append({
                "id": row[1],
                "start_time": row[2],
                "end_time": row[3],
                "hours": job_hours,
                "destination": row[5] or "",
                "client_name": row[6] or ""
            })

        day_list = list(days.values())

        total_hours = sum(day["hours"] for day in day_list)

        return {
            "days": day_list,
            "total_hours": total_hours
        }

    finally:
        conn.close()


def calculate_pay(user_id, total_hours):
    settings = get_pay_settings(user_id)

    total_hours = max(float(total_hours or 0), 0)

    regular_threshold = settings["overtime_threshold"]
    doubletime_threshold = settings["doubletime_threshold"]

    if doubletime_threshold > 0 and total_hours > doubletime_threshold:
        doubletime_hours = total_hours - doubletime_threshold
        overtime_hours = max(doubletime_threshold - regular_threshold, 0)
        regular_hours = min(total_hours, regular_threshold)
    elif total_hours > regular_threshold:
        regular_hours = regular_threshold
        overtime_hours = total_hours - regular_threshold
        doubletime_hours = 0
    else:
        regular_hours = total_hours
        overtime_hours = 0
        doubletime_hours = 0

    rate = settings["regular_rate"]

    regular_pay = regular_hours * rate
    overtime_pay = overtime_hours * rate * settings["overtime_multiplier"]
    doubletime_pay = doubletime_hours * rate * settings["doubletime_multiplier"]

    base_gross = regular_pay + overtime_pay + doubletime_pay

    vacation_pay = (
        base_gross * settings["vacation_percent"] / 100
    )

    gross_pay = base_gross + vacation_pay

    def deduction_value(deduction_type, value):
        if deduction_type == "percent":
            return gross_pay * value / 100
        return value

    income_tax = deduction_value(
        settings["income_tax_type"],
        settings["income_tax_value"]
    )

    cpp = deduction_value(
        settings["cpp_type"],
        settings["cpp_value"]
    )

    ei = deduction_value(
        settings["ei_type"],
        settings["ei_value"]
    )

    benefits = deduction_value(
        settings["benefits_type"],
        settings["benefits_value"]
    )

    pension = deduction_value(
        settings["pension_type"],
        settings["pension_value"]
    )

    other_deductions = deduction_value(
        settings["other_deductions_type"],
        settings["other_deductions_value"]
    )

    total_deductions = (
        income_tax
        + cpp
        + ei
        + benefits
        + pension
        + other_deductions
    )

    take_home = gross_pay - total_deductions

    return {
        "total_hours": total_hours,

        "regular_hours": regular_hours,
        "overtime_hours": overtime_hours,
        "doubletime_hours": doubletime_hours,

        "regular_pay": regular_pay,
        "overtime_pay": overtime_pay,
        "doubletime_pay": doubletime_pay,

        "vacation_pay": vacation_pay,
        "gross_pay": gross_pay,

        "income_tax": income_tax,
        "cpp": cpp,
        "ei": ei,
        "benefits": benefits,
        "pension": pension,
        "other_deductions": other_deductions,

        "total_deductions": total_deductions,
        "take_home": take_home,

        "settings": settings
    }

@app.route('/weekly')
def weekly():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    period = request.args.get('period', 'weekly').lower()

    if period not in ('daily', 'weekly', 'biweekly', 'monthly'):
        period = 'weekly'

    history_data = get_report_period_jobs(
        session['user_id'],
        period
    )

    total_hours = sum(
        float(
            re.findall(
                r"[-+]?\d*\.\d+|\d+",
                str(j.get('hours', 0))
            )[0]
        )
        if re.findall(
            r"[-+]?\d*\.\d+|\d+",
            str(j.get('hours', 0))
        )
        else 0
        for j in history_data
    )

    pay = calculate_pay(
        session['user_id'],
        total_hours
    )

    daily_payroll = get_daily_payroll(
        session['user_id'],
        period
    )

    period_labels = {
        'daily': 'Daily',
        'weekly': 'Weekly',
        'biweekly': 'Biweekly Pay Period',
        'monthly': 'Monthly'
    }

    return render_template(
        'weekly.html',
        history=history_data,
        total_hours=total_hours,
        pay_summary=pay,
        daily_payroll=daily_payroll,
        period=period,
        period_label=period_labels[period]
    )


@app.route('/pay-summary')
def pay_summary():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    period = request.args.get('period', 'biweekly').lower()

    if period not in ('daily', 'weekly', 'biweekly', 'monthly'):
        period = 'biweekly'

    user_id = session['user_id']

    # Pay is intentionally independent from Reports.
    # Get only the jobs belonging to the selected payroll period.
    report_jobs = get_report_period_jobs(user_id, period)

    daily_map = {}

    for job in report_jobs:
        job_date = job.get('date')

        if hasattr(job_date, 'date'):
            job_date = job_date.date()
        elif isinstance(job_date, str):
            from datetime import date
            try:
                job_date = date.fromisoformat(job_date[:10])
            except ValueError:
                continue

        try:
            hours = float(job.get('hours') or 0)
        except (TypeError, ValueError):
            hours = 0.0

        if job_date not in daily_map:
            daily_map[job_date] = {
                'date': job_date,
                'hours': 0.0,
                'jobs': []
            }

        # Normalize job data for the Pay page.
        # The database stores hours as TEXT, but the template
        # needs a real number for numeric formatting.
        pay_job = dict(job)
        pay_job['hours'] = hours

        daily_map[job_date]['hours'] += hours
        daily_map[job_date]['jobs'].append(pay_job)

    daily_rows = []

    for day in sorted(daily_map.values(), key=lambda x: x['date']):
        day['hours'] = round(day['hours'], 2)
        daily_rows.append(day)

    total_hours = round(
        sum(day['hours'] for day in daily_rows),
        2
    )

    pay = calculate_pay(user_id, total_hours)

    period_labels = {
        'daily': 'Daily',
        'weekly': 'Weekly',
        'biweekly': 'Biweekly Pay Period',
        'monthly': 'Monthly'
    }

    period_info = get_report_period_info(
        user_id,
        period
    )

    daily_data = {
        'start': daily_rows[0]['date'] if daily_rows else None,
        'end': daily_rows[-1]['date'] if daily_rows else None,
        'payday': period_info.get('payday'),
        'days': daily_rows,
        'total_hours': total_hours
    }

    return render_template(
        'pay_summary.html',
        history=daily_rows,
        daily_payroll=daily_data,
        total_hours=total_hours,
        pay_summary=pay,
        period=period_labels[period],
        period_key=period,
        period_info=period_info
    )


@app.route('/weekly-report')
def weekly_report():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    period = request.args.get('period', 'weekly').lower()

    if period not in ('daily', 'weekly', 'biweekly', 'monthly'):
        period = 'weekly'

    history_data = get_report_period_jobs(
        session['user_id'],
        period
    )

    total_hours = sum(
        float(
            re.findall(
                r"[-+]?\d*\.\d+|\d+",
                str(j.get('hours', 0))
            )[0]
        )
        if re.findall(
            r"[-+]?\d*\.\d+|\d+",
            str(j.get('hours', 0))
        )
        else 0
        for j in history_data
    )

    period_labels = {
        'daily': 'Daily',
        'weekly': 'Weekly',
        'biweekly': 'Biweekly Pay Period',
        'monthly': 'Monthly'
    }

    return render_template(
        'weekly_report.html',
        history=history_data,
        total_hours=total_hours,
        period=period,
        period_label=period_labels[period]
    )


@app.route('/send-weekly-report', methods=['POST'])
def send_weekly_report():


    if 'user_id' not in session:
        return redirect(url_for('login'))

    recipient = request.form.get(
        'recipient_email',
        ''
    ).strip().lower()

    if not recipient:
        return redirect(
            url_for(
                'weekly_report',
                error='recipient'
            )
        )

    if not re.match(
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        recipient
    ):
        return redirect(
            url_for(
                'weekly_report',
                error='recipient'
            )
        )

    history_data = get_current_week_jobs(
        session['user_id']
    )

    total_hours = sum(
        float(
            re.findall(
                r"[-+]?\d*\.?\d+",
                str(j.get('hours', 0))
            )[0]
        )
        if re.findall(
            r"[-+]?\d*\.?\d+",
            str(j.get('hours', 0))
        )
        else 0
        for j in history_data
    )

    try:

        subject, body, photos = build_weekly_email(
            history_data,
            total_hours
        )

        attached_count = send_email_with_attachments(
            subject,
            body,
            photos,
            recipient=recipient
        )

        job_ids = [
            job['id']
            for job in history_data
            if job.get('id')
        ]

        log_sent_report(
            user_id=session['user_id'],
            report_type='weekly',
            recipient_email=recipient,
            subject=subject,
            job_ids=job_ids,
            total_hours=total_hours,
            photo_count=attached_count,
            status='sent'
        )

        return redirect(
            url_for(
                'weekly_report',
                sent='weekly'
            )
        )

    except Exception as e:

        print(
            f"❌ WEEKLY EMAIL ERROR: {e}"
        )

        return redirect(
            url_for(
                'weekly_report',
                error='email'
            )
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



@app.route('/clients')
def clients():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, name, contact_person, phone, email,
                      address, city, province, postal_code, notes
               FROM clients
               WHERE user_id = %s
               ORDER BY name ASC""",
            (session['user_id'],)
        )
        rows = cur.fetchall()
        cur.close()

        client_list = [
            {
                "id": row[0],
                "name": row[1],
                "contact_person": row[2],
                "phone": row[3],
                "email": row[4],
                "address": row[5],
                "city": row[6],
                "province": row[7],
                "postal_code": row[8],
                "notes": row[9]
            }
            for row in rows
        ]

        return render_template(
            'clients.html',
            clients=client_list
        )
    finally:
        conn.close()


@app.route('/clients/new', methods=['GET', 'POST'])
def new_client():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO clients
                   (user_id, name, contact_person, phone, email,
                    address, city, province, postal_code, notes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    session['user_id'],
                    request.form.get('name', '').strip(),
                    request.form.get('contact_person', '').strip(),
                    request.form.get('phone', '').strip(),
                    request.form.get('email', '').strip(),
                    request.form.get('address', '').strip(),
                    request.form.get('city', '').strip(),
                    request.form.get('province', '').strip(),
                    request.form.get('postal_code', '').strip(),
                    request.form.get('notes', '').strip()
                )
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        return redirect(url_for('clients'))

    return render_template('client_form.html', client=None)


@app.route('/clients/<int:client_id>/edit', methods=['GET', 'POST'])
def edit_client(client_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    try:
        cur = conn.cursor()

        if request.method == 'POST':
            cur.execute(
                """UPDATE clients
                   SET name = %s,
                       contact_person = %s,
                       phone = %s,
                       email = %s,
                       address = %s,
                       city = %s,
                       province = %s,
                       postal_code = %s,
                       notes = %s,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = %s AND user_id = %s""",
                (
                    request.form.get('name', '').strip(),
                    request.form.get('contact_person', '').strip(),
                    request.form.get('phone', '').strip(),
                    request.form.get('email', '').strip(),
                    request.form.get('address', '').strip(),
                    request.form.get('city', '').strip(),
                    request.form.get('province', '').strip(),
                    request.form.get('postal_code', '').strip(),
                    request.form.get('notes', '').strip(),
                    client_id,
                    session['user_id']
                )
            )
            conn.commit()
            cur.close()
            return redirect(url_for('clients'))

        cur.execute(
            """SELECT id, name, contact_person, phone, email,
                      address, city, province, postal_code, notes
               FROM clients
               WHERE id = %s AND user_id = %s""",
            (client_id, session['user_id'])
        )
        row = cur.fetchone()
        cur.close()

        if not row:
            return redirect(url_for('clients'))

        client = {
            "id": row[0],
            "name": row[1],
            "contact_person": row[2],
            "phone": row[3],
            "email": row[4],
            "address": row[5],
            "city": row[6],
            "province": row[7],
            "postal_code": row[8],
            "notes": row[9]
        }

        return render_template(
            'client_form.html',
            client=client
        )
    finally:
        conn.close()


@app.route('/clients/<int:client_id>/delete', methods=['POST'])
def delete_client(client_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM clients WHERE id = %s AND user_id = %s",
            (client_id, session['user_id'])
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return redirect(url_for('clients'))


@app.route('/settings')
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    return render_template('settings.html')

@app.route('/settings/appearance', methods=['GET', 'POST'])
def appearance_settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()

    try:
        cur = conn.cursor()

        if request.method == 'POST':
            cur.execute(
                """INSERT INTO appearance_settings (
                       user_id,
                       theme,
                       accent_color,
                       layout_density,
                       card_style,
                       font_size,
                       animations,
                       dashboard_layout,
                       updated_at
                   )
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT (user_id)
                   DO UPDATE SET
                       theme = EXCLUDED.theme,
                       accent_color = EXCLUDED.accent_color,
                       layout_density = EXCLUDED.layout_density,
                       card_style = EXCLUDED.card_style,
                       font_size = EXCLUDED.font_size,
                       animations = EXCLUDED.animations,
                       dashboard_layout = EXCLUDED.dashboard_layout,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    session['user_id'],
                    request.form.get('theme') or 'light',
                    request.form.get('accent_color') or 'blue',
                    request.form.get('layout_density') or 'comfortable',
                    request.form.get('card_style') or 'rounded',
                    request.form.get('font_size') or 'default',
                    'animations' in request.form,
                    request.form.get('dashboard_layout') or 'standard'
                )
            )

            conn.commit()
            cur.close()

            return redirect(url_for('appearance_settings'))

        cur.execute(
            """SELECT
                   theme,
                   accent_color,
                   layout_density,
                   card_style,
                   font_size,
                   animations,
                   dashboard_layout
               FROM appearance_settings
               WHERE user_id = %s""",
            (session['user_id'],)
        )

        row = cur.fetchone()
        cur.close()

        if row:
            settings = {
                'theme': row[0] or 'light',
                'accent_color': row[1] or 'blue',
                'layout_density': row[2] or 'comfortable',
                'card_style': row[3] or 'rounded',
                'font_size': row[4] or 'default',
                'animations': row[5],
                'dashboard_layout': row[6] or 'standard'
            }
        else:
            settings = {
                'theme': 'light',
                'accent_color': 'blue',
                'layout_density': 'comfortable',
                'card_style': 'rounded',
                'font_size': 'default',
                'animations': True,
                'dashboard_layout': 'standard'
            }

        return render_template(
            'appearance_settings.html',
            settings=settings
        )

    finally:
        conn.close()


@app.route('/settings/account')
def account_settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT username FROM users WHERE id = %s",
            (session['user_id'],)
        )

        row = cur.fetchone()
        cur.close()

        username = row[0] if row else ''

        return render_template(
            'account_settings.html',
            username=username,
            user_id=session['user_id']
        )

    finally:
        conn.close()


@app.route('/settings/account/password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if len(new_password) < 8:
        return redirect(
            url_for('account_settings', password_error='length')
        )

    if new_password != confirm_password:
        return redirect(
            url_for('account_settings', password_error='match')
        )

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT password_hash FROM users WHERE id = %s",
            (session['user_id'],)
        )

        row = cur.fetchone()

        if not row:
            cur.close()
            return redirect(
                url_for('account_settings', password_error='account')
            )

        stored_hash = row[0]

        try:
            password_ok = check_password_hash(
                stored_hash,
                current_password
            )
        except Exception:
            password_ok = False

        if not password_ok:
            cur.close()
            return redirect(
                url_for('account_settings', password_error='current')
            )

        new_hash = generate_password_hash(new_password)

        cur.execute(
            """UPDATE users
               SET password_hash = %s
               WHERE id = %s""",
            (new_hash, session['user_id'])
        )

        conn.commit()
        cur.close()

        return redirect(
            url_for('account_settings', password_changed='1')
        )

    finally:
        conn.close()


@app.route('/settings/account/export')
def export_data():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            """SELECT id, date, hours, notes, destination, materials
               FROM jobs
               WHERE user_id = %s
               ORDER BY date DESC, id DESC""",
            (user_id,)
        )

        jobs = cur.fetchall()

        cur.execute(
            """SELECT id, name, contact_person, phone, email,
                      address, city, province, postal_code
               FROM clients
               WHERE user_id = %s
               ORDER BY name""",
            (user_id,)
        )

        clients = cur.fetchall()

        cur.execute(
            """SELECT username
               FROM users
               WHERE id = %s""",
            (user_id,)
        )

        user_row = cur.fetchone()

        cur.close()

        export = {
            "account": {
                "user_id": user_id,
                "username": user_row[0] if user_row else ""
            },
            "jobs": [
                {
                    "id": row[0],
                    "date": str(row[1]),
                    "hours": str(row[2]),
                    "notes": row[3],
                    "destination": row[4],
                    "materials": row[5]
                }
                for row in jobs
            ],
            "clients": [
                {
                    "id": row[0],
                    "name": row[1],
                    "contact_person": row[2],
                    "phone": row[3],
                    "email": row[4],
                    "address": row[5],
                    "city": row[6],
                    "province": row[7],
                    "postal_code": row[8]
                }
                for row in clients
            ]
        }

        response = make_response(
            json.dumps(export, indent=2, default=str)
        )

        response.headers["Content-Type"] = "application/json"
        response.headers[
            "Content-Disposition"
        ] = 'attachment; filename="pipeline-data-export.json"'

        return response

    finally:
        conn.close()


@app.route('/settings/app', methods=['GET', 'POST'])
def app_settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()

    try:
        cur = conn.cursor()

        if request.method == 'POST':
            cur.execute(
                """INSERT INTO app_settings (
                       user_id,
                       business_name,
                       user_display_name,
                       default_landing_page,
                       date_format,
                       time_format,
                       confirm_delete_jobs,
                       confirm_delete_photos,
                       default_job_hours,
                       default_job_status,
                       dashboard_recent_jobs,
                       remember_last_job_values,
                       autosave_drafts,
                       updated_at
                   )
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT (user_id)
                   DO UPDATE SET
                       business_name = EXCLUDED.business_name,
                       user_display_name = EXCLUDED.user_display_name,
                       default_landing_page = EXCLUDED.default_landing_page,
                       date_format = EXCLUDED.date_format,
                       time_format = EXCLUDED.time_format,
                       confirm_delete_jobs = EXCLUDED.confirm_delete_jobs,
                       confirm_delete_photos = EXCLUDED.confirm_delete_photos,
                       default_job_hours = EXCLUDED.default_job_hours,
                       default_job_status = EXCLUDED.default_job_status,
                       dashboard_recent_jobs = EXCLUDED.dashboard_recent_jobs,
                       remember_last_job_values = EXCLUDED.remember_last_job_values,
                       autosave_drafts = EXCLUDED.autosave_drafts,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    session['user_id'],
                    request.form.get('business_name', '').strip(),
                    request.form.get('user_display_name', '').strip(),
                    request.form.get('default_landing_page') or 'home',
                    request.form.get('date_format') or 'YYYY-MM-DD',
                    request.form.get('time_format') or '12',
                    'confirm_delete_jobs' in request.form,
                    'confirm_delete_photos' in request.form,
                    request.form.get('default_job_hours') or 0,
                    request.form.get('default_job_status') or 'completed',
                    request.form.get('dashboard_recent_jobs') or 3,
                    'remember_last_job_values' in request.form,
                    'autosave_drafts' in request.form
                )
            )

            conn.commit()
            cur.close()

            return redirect(url_for('app_settings'))

        cur.execute(
            """SELECT
                   business_name,
                   user_display_name,
                   default_landing_page,
                   date_format,
                   time_format,
                   confirm_delete_jobs,
                   confirm_delete_photos,
                   default_job_hours,
                   default_job_status,
                   dashboard_recent_jobs,
                   remember_last_job_values,
                   autosave_drafts
               FROM app_settings
               WHERE user_id = %s""",
            (session['user_id'],)
        )

        row = cur.fetchone()
        cur.close()

        if row:
            settings = {
                'business_name': row[0] or '',
                'user_display_name': row[1] or '',
                'default_landing_page': row[2] or 'home',
                'date_format': row[3] or 'YYYY-MM-DD',
                'time_format': row[4] or '12',
                'confirm_delete_jobs': row[5],
                'confirm_delete_photos': row[6],
                'default_job_hours': row[7] or 0,
                'default_job_status': row[8] or 'completed',
                'dashboard_recent_jobs': row[9] or 3,
                'remember_last_job_values': row[10] if row[10] is not None else True,
                'autosave_drafts': row[11] if row[11] is not None else True
            }
        else:
            settings = {
                'business_name': '',
                'user_display_name': '',
                'default_landing_page': 'home',
                'date_format': 'YYYY-MM-DD',
                'time_format': '12',
                'confirm_delete_jobs': True,
                'confirm_delete_photos': True,
                'default_job_hours': 0,
                'default_job_status': 'completed',
                'dashboard_recent_jobs': 3,
                'remember_last_job_values': True,
                'autosave_drafts': True
            }

        return render_template(
            'app_settings.html',
            settings=settings
        )

    finally:
        conn.close()


@app.route('/settings/email', methods=['GET', 'POST'])
def email_settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()

    try:
        cur = conn.cursor()

        if request.method == 'POST':
            cur.execute(
                """INSERT INTO email_settings (
                       user_id,
                       default_recipient,
                       email_subject,
                       email_signature,
                       attach_photos,
                       updated_at
                   )
                   VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT (user_id)
                   DO UPDATE SET
                       default_recipient = EXCLUDED.default_recipient,
                       email_subject = EXCLUDED.email_subject,
                       email_signature = EXCLUDED.email_signature,
                       attach_photos = EXCLUDED.attach_photos,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    session['user_id'],
                    request.form.get('default_recipient', '').strip(),
                    request.form.get('email_subject') or 'PipeLine Work Report',
                    request.form.get('email_signature', ''),
                    'attach_photos' in request.form
                )
            )

            conn.commit()
            cur.close()

            return redirect(url_for('email_settings'))

        cur.execute(
            """SELECT
                   default_recipient,
                   email_subject,
                   email_signature,
                   attach_photos
               FROM email_settings
               WHERE user_id = %s""",
            (session['user_id'],)
        )

        row = cur.fetchone()
        cur.close()

        if row:
            settings = {
                'default_recipient': row[0] or '',
                'email_subject': row[1] or 'PipeLine Work Report',
                'email_signature': row[2] or '',
                'attach_photos': row[3]
            }
        else:
            settings = {
                'default_recipient': '',
                'email_subject': 'PipeLine Work Report',
                'email_signature': '',
                'attach_photos': True
            }

        return render_template(
            'email_settings.html',
            settings=settings
        )

    finally:
        conn.close()


@app.route('/settings/reports', methods=['GET', 'POST'])
def report_settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()

    try:
        cur = conn.cursor()

        if request.method == 'POST':
            cur.execute(
                """INSERT INTO report_settings (
                       user_id,
                       default_period,
                       include_photos,
                       include_materials,
                       include_client_info,
                       include_address,
                       recipient_email,
                       updated_at
                   )
                   VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT (user_id)
                   DO UPDATE SET
                       default_period = EXCLUDED.default_period,
                       include_photos = EXCLUDED.include_photos,
                       include_materials = EXCLUDED.include_materials,
                       include_client_info = EXCLUDED.include_client_info,
                       include_address = EXCLUDED.include_address,
                       recipient_email = EXCLUDED.recipient_email,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    session['user_id'],
                    request.form.get('default_period') or 'weekly',
                    'include_photos' in request.form,
                    'include_materials' in request.form,
                    'include_client_info' in request.form,
                    'include_address' in request.form,
                    request.form.get('recipient_email', '').strip()
                )
            )

            conn.commit()
            cur.close()

            return redirect(url_for('report_settings'))

        cur.execute(
            """SELECT
                   default_period,
                   include_photos,
                   include_materials,
                   include_client_info,
                   include_address,
                   recipient_email
               FROM report_settings
               WHERE user_id = %s""",
            (session['user_id'],)
        )

        row = cur.fetchone()
        cur.close()

        if row:
            settings = {
                'default_period': row[0],
                'include_photos': row[1],
                'include_materials': row[2],
                'include_client_info': row[3],
                'include_address': row[4],
                'recipient_email': row[5] or ''
            }
        else:
            settings = {
                'default_period': 'weekly',
                'include_photos': True,
                'include_materials': True,
                'include_client_info': True,
                'include_address': True,
                'recipient_email': ''
            }

        return render_template(
            'report_settings.html',
            settings=settings
        )

    finally:
        conn.close()


@app.route('/settings/pay', methods=['GET', 'POST'])
def pay_settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()

    try:
        cur = conn.cursor()

        if request.method == 'POST':
            cur.execute(
                """INSERT INTO pay_settings (
                       user_id,
                       regular_rate,
                       overtime_threshold,
                       overtime_multiplier,
                       doubletime_threshold,
                       doubletime_multiplier,
                       vacation_percent,
                       income_tax_type,
                       income_tax_value,
                       cpp_type,
                       cpp_value,
                       ei_type,
                       ei_value,
                       benefits_type,
                       benefits_value,
                       pension_type,
                       pension_value,
                       other_deductions_type,
                       other_deductions_value,
                       biweekly_start_date,
                       updated_at
                   )
                   VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       CURRENT_TIMESTAMP
                   )
                   ON CONFLICT (user_id)
                   DO UPDATE SET
                       regular_rate = EXCLUDED.regular_rate,
                       overtime_threshold = EXCLUDED.overtime_threshold,
                       overtime_multiplier = EXCLUDED.overtime_multiplier,
                       doubletime_threshold = EXCLUDED.doubletime_threshold,
                       doubletime_multiplier = EXCLUDED.doubletime_multiplier,
                       vacation_percent = EXCLUDED.vacation_percent,
                       income_tax_type = EXCLUDED.income_tax_type,
                       income_tax_value = EXCLUDED.income_tax_value,
                       cpp_type = EXCLUDED.cpp_type,
                       cpp_value = EXCLUDED.cpp_value,
                       ei_type = EXCLUDED.ei_type,
                       ei_value = EXCLUDED.ei_value,
                       benefits_type = EXCLUDED.benefits_type,
                       benefits_value = EXCLUDED.benefits_value,
                       pension_type = EXCLUDED.pension_type,
                       pension_value = EXCLUDED.pension_value,
                       other_deductions_type = EXCLUDED.other_deductions_type,
                       other_deductions_value = EXCLUDED.other_deductions_value,
                       biweekly_start_date = EXCLUDED.biweekly_start_date,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    session['user_id'],
                    request.form.get('regular_rate') or 0,
                    request.form.get('overtime_threshold') or 44,
                    request.form.get('overtime_multiplier') or 1.5,
                    request.form.get('doubletime_threshold') or 0,
                    request.form.get('doubletime_multiplier') or 2,
                    request.form.get('vacation_percent') or 0,

                    request.form.get('income_tax_type') or 'percent',
                    request.form.get('income_tax_value') or 0,

                    request.form.get('cpp_type') or 'percent',
                    request.form.get('cpp_value') or 0,

                    request.form.get('ei_type') or 'percent',
                    request.form.get('ei_value') or 0,

                    request.form.get('benefits_type') or 'fixed',
                    request.form.get('benefits_value') or 0,

                    request.form.get('pension_type') or 'percent',
                    request.form.get('pension_value') or 0,

                    request.form.get('other_deductions_type') or 'fixed',
                    request.form.get('other_deductions_value') or 0,
                    request.form.get('biweekly_start_date') or '2026-08-14'
                )
            )

            conn.commit()

            cur.close()

            return redirect(url_for('pay_settings'))

        cur.execute(
            """SELECT
                   regular_rate,
                   overtime_threshold,
                   overtime_multiplier,
                   doubletime_threshold,
                   doubletime_multiplier,
                   vacation_percent,
                   income_tax_type,
                   income_tax_value,
                   cpp_type,
                   cpp_value,
                   ei_type,
                   ei_value,
                   benefits_type,
                   benefits_value,
                   pension_type,
                   pension_value,
                   other_deductions_type,
                   other_deductions_value,
                   biweekly_start_date
               FROM pay_settings
               WHERE user_id = %s""",
            (session['user_id'],)
        )

        row = cur.fetchone()
        cur.close()

        if row:
            settings = {
                'regular_rate': row[0],
                'overtime_threshold': row[1],
                'overtime_multiplier': row[2],
                'doubletime_threshold': row[3],
                'doubletime_multiplier': row[4],
                'vacation_percent': row[5],
                'income_tax_type': row[6],
                'income_tax_value': row[7],
                'cpp_type': row[8],
                'cpp_value': row[9],
                'ei_type': row[10],
                'ei_value': row[11],
                'benefits_type': row[12],
                'benefits_value': row[13],
                'pension_type': row[14],
                'pension_value': row[15],
                'other_deductions_type': row[16],
                'other_deductions_value': row[17],
                'biweekly_start_date': row[18]
            }
        else:
            settings = {
                'regular_rate': 0,
                'overtime_threshold': 44,
                'overtime_multiplier': 1.5,
                'doubletime_threshold': 0,
                'doubletime_multiplier': 2,
                'vacation_percent': 0,
                'income_tax_type': 'percent',
                'income_tax_value': 0,
                'cpp_type': 'percent',
                'cpp_value': 0,
                'ei_type': 'percent',
                'ei_value': 0,
                'benefits_type': 'fixed',
                'benefits_value': 0,
                'pension_type': 'percent',
                'pension_value': 0,
                'other_deductions_type': 'fixed',
                'other_deductions_value': 0,
                'biweekly_start_date': '2026-08-14'
            }

        return render_template(
            'pay_settings.html',
            settings=settings
        )

    finally:
        conn.close()


# --- OWNER HUB ---
from functools import wraps

def owner_required(view):
    """Require an authenticated user with the owner role."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))

        conn = get_db()

        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT role FROM users WHERE id = %s",
                (session['user_id'],)
            )
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()

        if not row or row[0] != 'owner':
            return "Owner access required.", 403

        return view(*args, **kwargs)

    return wrapped


@app.route('/owner')
@owner_required
def owner_dashboard():
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT username FROM users WHERE id = %s",
            (session['user_id'],)
        )
        user_row = cur.fetchone()
        username = user_row[0] if user_row else 'Owner'

        cur.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE role = 'employee'
        """)
        employee_count = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM clients
        """)
        client_count = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM jobs
            WHERE COALESCE(hours, '') = ''
               OR COALESCE(hours, '0')::numeric = 0
        """)
        open_jobs = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM notifications
            WHERE user_id = %s
              AND is_read = FALSE
        """, (session['user_id'],))
        unread_notifications = cur.fetchone()[0]

        cur.execute("""
            SELECT
                j.id,
                j.destination,
                j.date,
                j.notes,
                u.username AS employee_name
            FROM jobs j
            LEFT JOIN job_assignments ja
                ON ja.job_id = j.id
            LEFT JOIN users u
                ON u.id = ja.employee_id
            WHERE j.date = CURRENT_DATE::text
            ORDER BY j.id DESC
        """)
        rows = cur.fetchall()

        todays_jobs = []

        for row in rows:
            todays_jobs.append({
                'id': row[0],
                'destination': row[1],
                'date': row[2],
                'notes': row[3],
                'employee_name': row[4]
            })

        cur.close()

        return render_template(
            'owner_dashboard.html',
            username=username,
            employee_count=employee_count,
            client_count=client_count,
            open_jobs=open_jobs,
            unread_notifications=unread_notifications,
            todays_jobs=todays_jobs
        )

    finally:
        conn.close()

# --- END OWNER HUB ---


# --- OWNER HUB TOOLS ---

@app.route('/owner/employees')
@owner_required
def owner_employees():
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT id, username, created_at
            FROM users
            WHERE role = 'employee'
            ORDER BY username
        """)

        employees = cur.fetchall()
        cur.close()

    finally:
        conn.close()

    return render_template(
        'owner_employees.html',
        employees=employees,
        username=session.get('user')
    )


@app.route('/owner/employees/<int:employee_id>')
@owner_required
def owner_employee_profile(employee_id):
    conn = get_db()

    try:
        cur = conn.cursor()

        # Employee account.
        cur.execute(
            """
            SELECT id, username, created_at, role
            FROM users
            WHERE id = %s
              AND role = 'employee'
            """,
            (employee_id,)
        )

        employee = cur.fetchone()

        if not employee:
            cur.close()
            return "Employee not found.", 404

        # Assigned jobs.
        cur.execute(
            """
            SELECT
                j.id,
                j.date,
                j.start_time,
                j.end_time,
                j.destination,
                j.notes,
                ja.status,
                c.name AS client_name
            FROM jobs j
            INNER JOIN job_assignments ja
                ON ja.job_id = j.id
            LEFT JOIN clients c
                ON c.id = j.client_id
            WHERE ja.employee_id = %s
            ORDER BY j.date DESC, j.id DESC
            LIMIT 100
            """,
            (employee_id,)
        )

        job_rows = cur.fetchall()

        jobs = []

        for row in job_rows:
            jobs.append({
                'id': row[0],
                'date': str(row[1]) if row[1] else '',
                'start_time': str(row[2])[:5] if row[2] else '',
                'end_time': str(row[3])[:5] if row[3] else '',
                'destination': row[4] or '',
                'notes': row[5] or '',
                'status': row[6] or 'assigned',
                'client': row[7] or ''
            })

        # Hours this week.
        cur.execute(
            """
            SELECT COALESCE(SUM(
                CASE
                    WHEN hours IS NULL OR hours = '' THEN 0
                    ELSE hours::numeric
                END
            ), 0)
            FROM jobs j
            INNER JOIN job_assignments ja
                ON ja.job_id = j.id
            WHERE ja.employee_id = %s
              AND j.date::date >= date_trunc('week', CURRENT_DATE)::date
              AND j.date::date < (date_trunc('week', CURRENT_DATE) + INTERVAL '7 days')::date
            """,
            (employee_id,)
        )

        week_hours = float(cur.fetchone()[0] or 0)

        # Hours this pay period.
        cur.execute(
            """
            SELECT COALESCE(SUM(
                CASE
                    WHEN hours IS NULL OR hours = '' THEN 0
                    ELSE hours::numeric
                END
            ), 0)
            FROM jobs j
            INNER JOIN job_assignments ja
                ON ja.job_id = j.id
            WHERE ja.employee_id = %s
              AND j.date::date >= CURRENT_DATE - INTERVAL '13 days'
              AND j.date::date <= CURRENT_DATE
            """,
            (employee_id,)
        )

        pay_period_hours = float(cur.fetchone()[0] or 0)

        # Current/upcoming assignment.
        cur.execute(
            """
            SELECT
                j.id,
                j.date,
                j.destination,
                j.start_time,
                j.end_time,
                ja.status
            FROM jobs j
            INNER JOIN job_assignments ja
                ON ja.job_id = j.id
            WHERE ja.employee_id = %s
              AND j.date::date >= CURRENT_DATE
              AND COALESCE(ja.status, 'assigned') NOT IN ('completed', 'cancelled')
            ORDER BY j.date::date, j.start_time NULLS LAST, j.id
            LIMIT 1
            """,
            (employee_id,)
        )

        current_job_row = cur.fetchone()

        current_job = None

        if current_job_row:
            current_job = {
                'id': current_job_row[0],
                'date': str(current_job_row[1]),
                'destination': current_job_row[2] or '',
                'start_time': str(current_job_row[3])[:5] if current_job_row[3] else '',
                'end_time': str(current_job_row[4])[:5] if current_job_row[4] else '',
                'status': current_job_row[5] or 'assigned'
            }

        # Recent notifications for this employee.
        cur.execute(
            """
            SELECT
                title,
                message,
                created_at,
                is_read
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (employee_id,)
        )

        notification_rows = cur.fetchall()

        notifications = []

        for row in notification_rows:
            notifications.append({
                'title': row[0],
                'message': row[1],
                'created_at': row[2],
                'is_read': row[3]
            })

        cur.close()

        return render_template(
            'owner_employee_profile.html',
            employee=employee,
            jobs=jobs,
            week_hours=week_hours,
            pay_period_hours=pay_period_hours,
            current_job=current_job,
            notifications=notifications
        )

    finally:
        conn.close()


@app.route('/owner/clients')
@owner_required
def owner_clients():
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                id,
                name,
                contact_person,
                phone,
                email,
                address,
                city,
                province,
                postal_code,
                notes
            FROM clients
            ORDER BY name
        """)

        clients = cur.fetchall()
        cur.close()

    finally:
        conn.close()

    return render_template(
        'owner_clients.html',
        clients=clients,
        username=session.get('user')
    )


@app.route('/owner/notifications')
@owner_required
def owner_notifications():
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                id,
                title,
                message,
                is_read,
                created_at
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 100
            """,
            (session['user_id'],)
        )

        notifications = cur.fetchall()

        cur.execute(
            """
            UPDATE notifications
            SET is_read = TRUE
            WHERE user_id = %s
              AND is_read = FALSE
            """,
            (session['user_id'],)
        )

        conn.commit()
        cur.close()

        return render_template(
            'owner_notifications.html',
            notifications=notifications,
            username=session.get('user')
        )

    finally:
        conn.close()


@app.route('/owner/schedule', methods=['GET', 'POST'])
@owner_required
def owner_schedule():
    conn = get_db()

    try:
        cur = conn.cursor()

        # Owner's private calendar.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS owner_calendar_events (
                id SERIAL PRIMARY KEY,
                owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                event_type VARCHAR(30) NOT NULL,
                event_date DATE NOT NULL,
                title VARCHAR(200) NOT NULL,
                start_time TIME,
                end_time TIME,
                notes TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)

        if request.method == 'POST':

            action = request.form.get('action', 'job')

            if action == 'personal':

                event_type = request.form.get('event_type', 'appointment')
                event_date = request.form.get('event_date')
                title = request.form.get('title', '').strip()
                start_time = request.form.get('start_time') or None
                end_time = request.form.get('end_time') or None
                notes = request.form.get('event_notes', '').strip()

                if event_date and title:
                    cur.execute(
                        """
                        INSERT INTO owner_calendar_events (
                            owner_id,
                            event_type,
                            event_date,
                            title,
                            start_time,
                            end_time,
                            notes
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            session['user_id'],
                            event_type,
                            event_date,
                            title,
                            start_time,
                            end_time,
                            notes
                        )
                    )

                    conn.commit()

                cur.close()

                return redirect(url_for('owner_schedule'))

            # Normal company job scheduling.
            client_id = request.form.get('client_id') or None
            employee_id = request.form.get('employee_id')
            date = request.form.get('date')
            start_time = request.form.get('start_time') or None
            end_time = request.form.get('end_time') or None
            destination = request.form.get('destination', '').strip()
            notes = request.form.get('notes', '').strip()
            materials = request.form.get('materials', '').strip()

            if not employee_id or not date or not destination:
                cur.close()
                return redirect(url_for('owner_schedule'))

            calculated_hours = None

            if start_time and end_time:
                start_parts = [int(x) for x in start_time.split(':')]
                end_parts = [int(x) for x in end_time.split(':')]

                start_minutes = start_parts[0] * 60 + start_parts[1]
                end_minutes = end_parts[0] * 60 + end_parts[1]

                if end_minutes < start_minutes:
                    end_minutes += 24 * 60

                calculated_hours = f"{(end_minutes - start_minutes) / 60:.2f}"

            cur.execute(
                """
                INSERT INTO jobs (
                    user_id,
                    date,
                    hours,
                    start_time,
                    end_time,
                    notes,
                    destination,
                    materials,
                    photos,
                    client_id
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    session['user_id'],
                    date,
                    calculated_hours,
                    start_time,
                    end_time,
                    notes,
                    destination,
                    materials,
                    json.dumps([]),
                    client_id
                )
            )

            job_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO job_assignments (
                    job_id,
                    employee_id,
                    assigned_by,
                    assigned_at,
                    status
                )
                VALUES (
                    %s, %s, %s, CURRENT_TIMESTAMP, 'assigned'
                )
                """,
                (
                    job_id,
                    employee_id,
                    session['user_id']
                )
            )

            cur.execute(
                """
                INSERT INTO notifications (
                    user_id,
                    job_id,
                    type,
                    title,
                    message,
                    is_read,
                    created_at
                )
                VALUES (
                    %s,
                    %s,
                    'job_assigned',
                    %s,
                    %s,
                    FALSE,
                    CURRENT_TIMESTAMP
                )
                """,
                (
                    employee_id,
                    job_id,
                    'New job assigned',
                    f'A new job has been assigned to you for {date} at {destination}.'
                )
            )

            conn.commit()

            cur.close()

            return redirect(url_for('owner_schedule'))

        # Clients.
        cur.execute(
            """
            SELECT id, name
            FROM clients
            ORDER BY name
            """
        )
        clients = cur.fetchall()

        # Employees.
        cur.execute(
            """
            SELECT id, username
            FROM users
            WHERE role = 'employee'
            ORDER BY username
            """
        )
        employees = cur.fetchall()

        # ALL company jobs.
        cur.execute(
            """
            SELECT
                j.id,
                j.date,
                j.start_time,
                j.end_time,
                j.destination,
                j.notes,
                c.name AS client_name,
                u.username AS employee_name,
                ja.status
            FROM jobs j
            LEFT JOIN clients c
                ON c.id = j.client_id
            LEFT JOIN job_assignments ja
                ON ja.job_id = j.id
            LEFT JOIN users u
                ON u.id = ja.employee_id
            ORDER BY j.id DESC
            LIMIT 500
            """
        )

        job_rows = cur.fetchall()

        # Owner's personal calendar.
        cur.execute(
            """
            SELECT
                id,
                event_type,
                event_date,
                title,
                start_time,
                end_time,
                notes
            FROM owner_calendar_events
            WHERE owner_id = %s
            ORDER BY event_date, start_time NULLS LAST, id
            """,
            (session['user_id'],)
        )

        personal_rows = cur.fetchall()

        cur.close()

        jobs = []

        for row in job_rows:
            jobs.append({
                'id': row[0],
                'date': str(row[1]) if row[1] else '',
                'start_time': str(row[2])[:5] if row[2] else '',
                'end_time': str(row[3])[:5] if row[3] else '',
                'destination': row[4] or '',
                'notes': row[5] or '',
                'client': row[6] or '',
                'employee': row[7] or 'Unassigned',
                'status': row[8] or 'scheduled'
            })

        personal_events = []

        for row in personal_rows:
            personal_events.append({
                'id': row[0],
                'type': row[1],
                'date': str(row[2]),
                'title': row[3],
                'start_time': str(row[4])[:5] if row[4] else '',
                'end_time': str(row[5])[:5] if row[5] else '',
                'notes': row[6] or ''
            })

        return render_template(
            'owner_schedule.html',
            jobs=jobs,
            personal_events=personal_events,
            clients=clients,
            employees=employees,
            username=session.get('user')
        )

    finally:
        conn.close()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
