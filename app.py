from flask import Flask, render_template, request, redirect, url_for
import os
import json
import re
import base64

app = Flask(__name__)

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

def process_photos(files_dict):
    photos = []
    for key in ['photo1', 'photo2', 'photo3']:
        f = files_dict.get(key)
        if f and f.filename and f.filename.strip() != '':
            img_bytes = f.read()
            encoded = base64.b64encode(img_bytes).decode('utf-8')
            photos.append(f"data:image/jpeg;base64,{encoded}")
    return photos

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        photos = process_photos(request.files)
        job = {
            'date': request.form.get('date'),
            'hours': request.form.get('hours'),
            'notes': request.form.get('notes'),
            'destination': request.form.get('destination'),
            'materials': request.form.get('materials'),
            'photos': photos
        }
        save_history(job)
        return redirect(url_for('report'))
    return render_template('index.html')

@app.route('/report')
def report():
    history = load_history()
    job = history[0] if history else {}
    return render_template('report.html', job=job)

@app.route('/history')
def history():
    return render_template('history.html', history=load_history())

@app.route('/weekly')
def weekly():
    history_data = load_history()
    total_hours = sum(parse_hours(job.get('hours', 0)) for job in history_data)
    return render_template('weekly.html', history=history_data, total_hours=total_hours)

@app.route('/delete/<int:index>', methods=['POST'])
def delete_job(index):
    history = load_history()
    if 0 <= index < len(history):
        history.pop(index)
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f)
    return redirect(url_for('history'))

@app.route('/edit/<int:index>', methods=['GET', 'POST'])
def edit_job(index):
    history = load_history()
    if not (0 <= index < len(history)):
        return redirect(url_for('history'))
    
    job = history[index]
    if request.method == 'POST':
        job['date'] = request.form.get('date')
        job['hours'] = request.form.get('hours')
        job['destination'] = request.form.get('destination')
        job['notes'] = request.form.get('notes')
        job['materials'] = request.form.get('materials')
        
        new_photos = process_photos(request.files)
        if new_photos:
            job['photos'] = job.get('photos', []) + new_photos
            
        history[index] = job
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f)
        return redirect(url_for('history'))
        
    return render_template('edit.html', job=job, index=index)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
