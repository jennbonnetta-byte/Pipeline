from flask import Flask, render_template, request, redirect, url_for
import os
import json
import re
import cloudinary
import cloudinary.uploader

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- PASTE YOUR CLOUDINARY KEYS HERE ---
cloudinary.config(
  cloud_name = "zdcnva6y",,
  api_key = "324287761859815",
  api_secret = "4s2beTrT3cRCVPDiwrWsBQfJhjE"
)

HISTORY_FILE = 'history.json'

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
                # 1. Save locally first to guarantee a stable upload handle
                temp_filename = f"temp_{int(time.time())}_{f.filename}"
                temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
                f.save(temp_path)
                
                # 2. Upload from the safe local path to Cloudinary
                response = cloudinary.uploader.upload(temp_path)
                if 'secure_url' in response:
                    urls.append(response['secure_url'])
                
                # 3. Clean up the temporary local file
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception as e:
                print(f"❌ CLOUDINARY UPLOAD ERROR: {e}")
    return urls

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/entry', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        photo_urls = upload_to_cloudinary(request.files.getlist('photos'))
        job = {
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
    history = load_history()
    job = history[0] if history else {}
    return render_template('report.html', job=job, job_index=0 if history else None)

@app.route('/history')
def history():
    return render_template('history.html', history=load_history())

@app.route('/weekly')
def weekly():
    history_data = load_history()
    total_hours = sum(float(re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0)))[0]) if re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0))) else 0 for j in history_data)
    return render_template('weekly.html', history=history_data, total_hours=total_hours)

@app.route('/weekly-report')
def weekly_report():
    history_data = load_history()
    total_hours = sum(float(re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0)))[0]) if re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0))) else 0 for j in history_data)
    return render_template('weekly_report.html', history=history_data, total_hours=total_hours)

@app.route('/gallery')
def gallery():
    return render_template('gallery.html', history=load_history())

@app.route('/job-photos/<int:index>')
def job_photos(index):
    history = load_history()
    if 0 <= index < len(history):
        return render_template('job_photos.html', job=history[index])
    return redirect(url_for('history'))

@app.route('/delete/<int:index>', methods=['POST'])
def delete_job(index):
    history = load_history()
    if 0 <= index < len(history):
        history.pop(index)
        with open(HISTORY_FILE, 'w') as f: json.dump(history, f)
    return redirect(url_for('history'))

@app.route('/edit/<int:index>', methods=['GET', 'POST'])
def edit_job(index):
    history = load_history()
    if not (0 <= index < len(history)): return redirect(url_for('history'))
    job = history[index]
    if request.method == 'POST':
        job.update({k: request.form.get(k) for k in ['date','hours','destination','notes','materials']})
        new_urls = upload_to_cloudinary(request.files.getlist('photos'))
        job['photos'] = job.get('photos', []) + new_urls
        history[index] = job
        with open(HISTORY_FILE, 'w') as f: json.dump(history, f)
        return redirect(url_for('history'))
    return render_template('edit.html', job=job)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
