from flask import Flask, render_template, request, redirect, url_for
import os
import json
import re
import time

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

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

def parse_hours(h_str):
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", str(h_str))
    if numbers:
        return float(numbers[0])
    return 0.0

current_job = {}

@app.route('/', methods=['GET', 'POST'])
def index():
    global current_job
    if request.method == 'POST':
        photos = []
        for f in request.files.getlist('photos'):
            if f and f.filename:
                # Give every image a unique name so mobile cameras don't overwrite each other
                base, ext = os.path.splitext(f.filename)
                unique_name = f"{base}_{int(time.time())}_{os.urandom(2).hex()}{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
                f.save(filepath)
                photos.append(unique_name)
        
        current_job = {
            'date': request.form.get('date'),
            'hours': request.form.get('hours'),
            'notes': request.form.get('notes'),
            'destination': request.form.get('destination'),
            'materials': request.form.get('materials'),
            'photos': photos
        }
        save_history(current_job)
        return redirect(url_for('report'))
    return render_template('index.html')

@app.route('/report')
def report():
    return render_template('report.html', job=current_job)

@app.route('/history')
def history():
    return render_template('history.html', history=load_history())

@app.route('/weekly')
def weekly():
    history_data = load_history()
    total_hours = sum(parse_hours(job.get('hours', 0)) for job in history_data)
    return render_template('weekly.html', history=history_data, total_hours=total_hours)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
