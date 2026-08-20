from flask import Flask, render_template, request, redirect, url_for
import os
import json
import re

app = Flask(__name__)

# Try to import cloudinary, but don't crash if it's missing
try:
    import cloudinary
    import cloudinary.uploader
    CLOUDINARY_AVAILABLE = True
    # Configure your free Cloudinary account here
    cloudinary.config(
      cloud_name = "YOUR_CLOUD_NAME",
      api_key = "YOUR_API_KEY",
      api_secret = "YOUR_API_SECRET"
    )
except ImportError:
    CLOUDINARY_AVAILABLE = False

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
    if not CLOUDINARY_AVAILABLE:
        return urls
    for f in files_list:
        if f and f.filename and f.filename.strip() != '':
            try:
                response = cloudinary.uploader.upload(f)
                if 'secure_url' in response:
                    urls.append(response['secure_url'])
            except Exception as e:
                print(f"Cloud upload failed: {e}")
    return urls

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            all_files = request.files.getlist('photos') + request.files.getlist('photos2')
            photo_urls = upload_to_cloudinary(all_files)
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
        except Exception as e:
            print(f"Error saving job: {e}")
            return "An error occurred saving your job. Please go back and try again.", 500
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
    total_hours = 0
    for j in history_data:
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", str(j.get('hours', 0)))
        if nums:
            total_hours += float(nums[0])
    return render_template('weekly.html', history=history_data, total_hours=total_hours)

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
        new_urls = upload_to_cloudinary(request.files.getlist('photos') + request.files.getlist('photos2'))
        job['photos'] = job.get('photos', []) + new_urls
        history[index] = job
        with open(HISTORY_FILE, 'w') as f: json.dump(history, f)
        return redirect(url_for('history'))
    return render_template('edit.html', job=job)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
