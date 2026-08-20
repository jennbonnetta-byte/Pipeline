from flask import Flask, render_template, request, redirect, url_for, session
import os
import json
import re
import time
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader

app = Flask(__name__)
app.secret_key = 'pipeline_secure_app_key_2026'

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- PASTE YOUR CLOUDINARY KEYS HERE ---
cloudinary.config(
  cloud_name = "YOUR_CLOUD_NAME",
  api_key = "YOUR_API_KEY",
  api_secret = "YOUR_API_SECRET"
)

USERS_FILE = 'users.json'
HISTORY_FILE = 'history.json'

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            try: return json.load(f)
            except: return {}
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f)

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try: return json.load(f)
            except: return []
    return []

def save_history(job):
    history = load_history()
    history.insert(0, job)
    with open(HISTORY_FILE, 'w') as f: json.dump(history, f)

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
        username = request.form.get('username').strip().lower()
        password = request.form.get('password')
        users = load_users()
        
        if username in users and check_password_hash(users[username], password):
            session['user'] = username
            return redirect(url_for('home'))
        else:
            error = 'Invalid username or password'
    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form.get('username').strip().lower()
        password = request.form.get('password')
        users = load_users()
        
        if not username or not password:
            error = 'Please fill out all fields.'
        elif username in users:
            error = 'Username already exists.'
        else:
            users[username] = generate_password_hash(password)
            save_users(users)
            session['user'] = username
            return redirect(url_for('home'))
    return render_template('register.html', error=error)

@app.route('/logout')
def logout():
    session.pop('user', None)
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
        save_history(job)
        return redirect(url_for('report'))
    return render_template('index.html')

@app.route('/report')
def report():
    if 'user' not in session: return redirect(url_for('login'))
    history = [j for j in load_history() if j.get('user') == session['user']]
    job = history[0] if history else {}
    return render_template('report.html', job=job, job_index=0 if history else None)

@app.route('/history')
def history():
    if 'user' not in session: return redirect(url_for('login'))
    user_history = [j for j in load_history() if j.get('user') == session['user']]
    return render_template('history.html', history=user_history)

@app.route('/weekly')
def weekly():
    if 'user' not in session: return redirect(url_for('login'))
    history_data = [j for j in load_history() if j.get('user') == session['user']]
    total_hours = sum(float(re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0)))[0]) if re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0))) else 0 for j in history_data)
    return render_template('weekly.html', history=history_data, total_hours=total_hours)

@app.route('/weekly-report')
def weekly_report():
    if 'user' not in session: return redirect(url_for('login'))
    history_data = [j for j in load_history() if j.get('user'] == session['user']]
    total_hours = sum(float(re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0)))[0]) if re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0))) else 0 for j in history_data)
    return render_template('weekly_report.html', history=history_data, total_hours=total_hours)

@app.route('/gallery')
def gallery():
    if 'user' not in session: return redirect(url_for('login'))
    user_history = [j for j in load_history() if j.get('user'] == session['user']]
    return render_template('gallery.html', history=user_history)

@app.route('/job-photos/<int:index>')
def job_photos(index):
    if 'user' not in session: return redirect(url_for('login'))
    full_history = load_history()
    user_history = [j for j in full_history if j.get('user') == session['user']]
    if 0 <= index < len(user_history):
        return render_template('job_photos.html', job=user_history[index])
    return redirect(url_for('history'))

@app.route('/delete/<int:index>', methods=['POST'])
def delete_job(index):
    if 'user' not in session: return redirect(url_for('login'))
    full_history = load_history()
    # Find the specific user's job to delete
    user_jobs = [j for j in full_history if j.get('user') == session['user']]
    if 0 <= index < len(user_jobs):
        target = user_jobs[index]
        if target in full_history:
            full_history.remove(target)
            with open(HISTORY_FILE, 'w') as f: json.dump(full_history, f)
    return redirect(url_for('history'))

@app.route('/edit/<int:index>', methods=['GET', 'POST'])
def edit_job(index):
    if 'user' not in session: return redirect(url_for('login'))
    full_history = load_history()
    user_jobs = [j for j in full_history if j.get('user') == session['user']]
    if not (0 <= index < len(user_jobs)): return redirect(url_for('history'))
    
    target_job = user_jobs[index]
    global_index = full_history.index(target_job)
    
    if request.method == 'POST':
        target_job.update({k: request.form.get(k) for k in ['date','hours','destination','notes','materials']})
        new_urls = upload_to_cloudinary(request.files.getlist('photos'))
        target_job['photos'] = target_job.get('photos', []) + new_urls
        full_history[global_index] = target_job
        with open(HISTORY_FILE, 'w') as f: json.dump(full_history, f)
        return redirect(url_for('history'))
    return render_template('edit.html', job=target_job)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
