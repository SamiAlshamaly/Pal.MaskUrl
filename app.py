from flask import Flask, request, render_template, redirect, jsonify, session, url_for, send_file
import sqlite3
import json
import uuid
import requests
import datetime
import os
import hashlib
import secrets
import qrcode
from io import BytesIO
import base64

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # مفتاح سري للجلسات

# بيانات المستخدم (في الإنتاج يجب تخزينها في قاعدة البيانات)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = hashlib.sha256("admin123".encode()).hexdigest()  # تشفير كلمة المرور

# إنشاء قاعدة البيانات إذا لم تكن موجودة
def init_db():
    conn = sqlite3.connect('tracking.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tracking_data (
        id TEXT PRIMARY KEY,
        ip TEXT,
        user_agent TEXT,
        screen_resolution TEXT,
        language TEXT,
        os TEXT,
        browser TEXT,
        location TEXT,
        timestamp TEXT,
        fingerprint TEXT,
        referrer TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS links (
        id TEXT PRIMARY KEY,
        original_url TEXT,
        short_code TEXT,
        created_at TEXT
    )
    ''')
    conn.commit()
    conn.close()

# تأكد من وجود مجلد للقوالب
if not os.path.exists('templates'):
    os.makedirs('templates')

# التحقق من تسجيل الدخول
def is_logged_in():
    return session.get('logged_in', False)

# صفحة تسجيل الدخول
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # تشفير كلمة المرور المدخلة للمقارنة
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        if username == ADMIN_USERNAME and hashed_password == ADMIN_PASSWORD:
            session['logged_in'] = True
            session['username'] = username
            return redirect('/dashboard')
        else:
            return redirect('/login?error=1')
    
    return render_template('login.html')

# تسجيل الخروج
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect('/')

# إنشاء رابط مختصر
@app.route('/create_link', methods=['POST'])
def create_link():
    data = request.get_json()
    original_url = data.get('url')
    
    if not original_url:
        return jsonify({'error': 'URL is required'}), 400
    
    link_id = str(uuid.uuid4())[:8]
    short_code = link_id
    
    # يمكن استخدام خدمة Bitly هنا بدلاً من ذلك
    # لكننا سنستخدم نظام مخصص للتبسيط
    
    conn = sqlite3.connect('tracking.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO links (id, original_url, short_code, created_at) VALUES (?, ?, ?, ?)',
        (link_id, original_url, short_code, datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    
    tracking_url = request.host_url + 't/' + short_code
    
    # إنشاء رمز QR للرابط المختصر
    qr_image = generate_qr_code(tracking_url)
    qr_base64 = base64.b64encode(qr_image.getvalue()).decode('utf-8')
    
    return jsonify({
        'original_url': original_url,
        'tracking_url': tracking_url,
        'short_code': short_code,
        'qr_code': qr_base64
    })

# دالة لإنشاء رمز QR
def generate_qr_code(url):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # حفظ الصورة في ذاكرة مؤقتة
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    return buffer

# إنشاء رمز QR للرابط المختصر (كصورة)
@app.route('/qrcode/<short_code>')
def get_qrcode(short_code):
    conn = sqlite3.connect('tracking.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM links WHERE short_code = ?', (short_code,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return "رابط غير صالح", 404
    
    tracking_url = request.host_url + 't/' + short_code
    
    # إنشاء رمز QR
    buffer = generate_qr_code(tracking_url)
    
    # إرسال الصورة كاستجابة
    return send_file(buffer, mimetype='image/png')

# صفحة الهبوط التي تجمع البيانات
@app.route('/t/<short_code>')
def track_link(short_code):
    conn = sqlite3.connect('tracking.db')
    cursor = conn.cursor()
    cursor.execute('SELECT original_url FROM links WHERE short_code = ?', (short_code,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return "رابط غير صالح", 404
    
    original_url = result[0]
    
    return render_template('landing.html', 
                          original_url=original_url, 
                          short_code=short_code)

# استقبال بيانات التتبع
@app.route('/api/track', methods=['POST'])
def receive_tracking_data():
    data = request.get_json()
    
    tracking_id = str(uuid.uuid4())
    
    conn = sqlite3.connect('tracking.db')
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO tracking_data 
           (id, ip, user_agent, screen_resolution, language, os, browser, location, 
            timestamp, fingerprint, referrer) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            tracking_id,
            request.remote_addr,
            data.get('userAgent'),
            data.get('screenResolution'),
            data.get('language'),
            data.get('os'),
            data.get('browser'),
            data.get('location'),
            datetime.datetime.now().isoformat(),
            data.get('fingerprint'),
            data.get('referrer')
        )
    )
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'redirect': data.get('originalUrl')})

# صفحة لعرض البيانات المجمعة (محمية بكلمة مرور)
@app.route('/dashboard')
def dashboard():
    # التحقق من تسجيل الدخول
    if not is_logged_in():
        return redirect('/login')
    
    conn = sqlite3.connect('tracking.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tracking_data ORDER BY timestamp DESC')
    tracking_data = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template('dashboard.html', 
                          tracking_data=tracking_data, 
                          username=session.get('username'))

# الصفحة الرئيسية
@app.route('/')
def index():
    return render_template('index.html')

# حذف سجل تتبع محدد
@app.route('/api/tracking/<tracking_id>', methods=['DELETE'])
def delete_tracking_record(tracking_id):
    # التحقق من تسجيل الدخول
    if not is_logged_in():
        return jsonify({'error': 'غير مصرح لك بالوصول'}), 403
    
    try:
        conn = sqlite3.connect('tracking.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM tracking_data WHERE id = ?', (tracking_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'تم حذف السجل بنجاح'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# حذف جميع سجلات التتبع
@app.route('/api/tracking', methods=['DELETE'])
def delete_all_tracking_records():
    # التحقق من تسجيل الدخول
    if not is_logged_in():
        return jsonify({'error': 'غير مصرح لك بالوصول'}), 403
    
    try:
        conn = sqlite3.connect('tracking.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM tracking_data')
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'تم حذف جميع السجلات بنجاح'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)