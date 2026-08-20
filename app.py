from flask import Flask, render_template, request, redirect, url_for
import os
import json

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

HISTORY_FILE = 'history.json'

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_history(job):
    history = load_history()
    history.insert(0, job)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

current_job = {}

@app.route('/', methods=['GET', 'POST'])
def index():
    global current_job
    if request.method == 'POST':
        # Handle multiple photo uploads
        photo_filenames = []
        files = request.files.getlist('photos')
        for file in files:
            if file and file.filename:
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(filepath)
                photo_filenames.append(file.filename)

        current_job = {
            'date': request.form.get('date'),
            'hours': request.form.get('hours'),
            'notes': request.form.get('notes'),
            'start_loc': request.form.get('start_loc', 'Shop HQ'),
            'destination': request.form.get('destination'),
            'materials': request.form.get('materials'),
            'photos': photo_filenames
        }
        
        save_history(current_job)
        return redirect(url_for('report'))
        
    return render_template('index.html')

@app.route('/report')
def report():
    return render_template('report.html', job=current_job)

@app.route('/weekly')
def weekly():
    history = load_history()
    return render_template('weekly.html', history=history)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
