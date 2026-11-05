import hashlib
import json
import os
import secrets
import time

import bcrypt
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf

from family_chat import chat_bp
from family_stories import stories_bp
from family_tree import tree_bp
from profile_routes import profile_bp
from services import (
    BOOKS_DIR,
    DATA_DIR,
    DOCUMENTS_DIR,
    LOCKOUT_PATH,
    MAIN_HTML_FILE,
    PHOTO_DIR,
    ROOT_DIR,
    get_authenticated_user,
    get_books_list,
    get_documents_list,
    load_events,
    load_users,
    save_events,
    save_users,
)

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 6291456
csrf = CSRFProtect(app)

app.register_blueprint(chat_bp)
app.register_blueprint(stories_bp)
app.register_blueprint(tree_bp)
app.register_blueprint(profile_bp)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    return jsonify({'error': error.description}), 400


@app.errorhandler(413)
def handle_request_too_large(_error):
    return jsonify({'error': 'Upload must be no larger than 5 MB.'}), 413


def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def hash_pin(pin):
    return hashlib.sha256(str(pin).encode('utf-8')).hexdigest()


def verify_password(password, stored_hash):
    return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))


def verify_pin(pin, stored_hash):
    return hash_pin(pin) == stored_hash


def load_lockout():
    if not os.path.exists(LOCKOUT_PATH):
        return {}
    try:
        with open(LOCKOUT_PATH, 'r', encoding='utf-8') as file:
            data = json.load(file) or {}
        now = time.time()
        return {
            username: entry
            for username, entry in data.items()
            if entry.get('until', 0) > now
        }
    except (json.JSONDecodeError, OSError):
        return {}


def save_lockout(lockout):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOCKOUT_PATH, 'w', encoding='utf-8') as file:
        json.dump(lockout, file)


def is_locked_out(username):
    lockout = load_lockout()
    entry = lockout.get(username, {})
    until = entry.get('until', 0)
    if not until:
        return False
    if until < time.time():
        lockout.pop(username, None)
        save_lockout(lockout)
        return False
    return True


def record_failed_attempt(username):
    lockout = load_lockout()
    entry = lockout.setdefault(username, {'count': 0, 'until': 0})
    entry['count'] = entry.get('count', 0) + 1
    if entry['count'] >= MAX_FAILED_ATTEMPTS:
        entry['until'] = time.time() + LOCKOUT_SECONDS
    save_lockout(lockout)


def get_lockout_remaining_seconds(username):
    lockout = load_lockout()
    until = lockout.get(username, {}).get('until', 0)
    remaining = int(until - time.time())
    return max(0, remaining)


@app.route('/', methods=['GET'])
def index():
    if get_authenticated_user():
        return redirect('/welcome')
    return send_from_directory(ROOT_DIR, MAIN_HTML_FILE)


@app.route('/index.html', methods=['GET'])
def serve_main_html():
    if get_authenticated_user():
        return redirect('/welcome')
    html_path = os.path.join(ROOT_DIR, MAIN_HTML_FILE)
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as file:
            return file.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    return send_from_directory(ROOT_DIR, MAIN_HTML_FILE)


@app.route('/api/csrf', methods=['GET'])
def csrf_token():
    response = jsonify({'csrf_token': generate_csrf()})
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/welcome', methods=['GET'])
def welcome():
    if not get_authenticated_user():
        return redirect('/')
    return send_from_directory(ROOT_DIR, 'welcome.html')


@app.route('/photos', methods=['GET'])
def photos_page():
    if not get_authenticated_user():
        return redirect('/')
    return render_template('photos.html')


@app.route('/documents', methods=['GET'])
def documents_page():
    if not get_authenticated_user():
        return redirect('/')
    docs = get_documents_list()
    return render_template('documents.html', documents=docs)


@app.route('/book', methods=['GET'])
def book_page():
    if not get_authenticated_user():
        return redirect('/')
    books = get_books_list()
    return render_template('book.html', books=books)


@app.route('/calendar', methods=['GET'])
def calendar_page():
    if not get_authenticated_user():
        return redirect('/')
    return render_template('calendar.html')


@app.route('/api/events', methods=['GET', 'POST'])
def events_endpoint():
    if not get_authenticated_user():
        return jsonify({'error': 'Unauthorized'}), 401
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        if not data.get('title') or not (data.get('date') or data.get('full_date')):
            return jsonify({'error': 'Title and date required'}), 400
        events = load_events()
        events.append(data)
        save_events(events)
        return jsonify({'message': 'Event saved', 'event': data}), 201
    return jsonify({'events': load_events()}), 200


@app.route('/api/books', methods=['GET'])
def list_books():
    if not get_authenticated_user():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'books': get_books_list()}), 200


@app.route('/api/books/<path:filename>', methods=['GET'])
def serve_book(filename):
    if not get_authenticated_user():
        return redirect('/')
    if not os.path.isdir(BOOKS_DIR):
        return jsonify({'error': 'Books directory not found'}), 404
    as_attachment = request.args.get('download') == '1'
    return send_from_directory(
        BOOKS_DIR,
        filename,
        as_attachment=as_attachment,
        download_name=os.path.basename(filename),
    )


@app.route('/api/documents', methods=['GET'])
def list_documents():
    if not get_authenticated_user():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'documents': get_documents_list()}), 200


@app.route('/api/documents/<path:filename>', methods=['GET'])
def serve_document(filename):
    if not get_authenticated_user():
        return redirect('/')
    if not os.path.isdir(DOCUMENTS_DIR):
        return jsonify({'error': 'Documents directory not found'}), 404
    as_attachment = request.args.get('download') == '1'
    return send_from_directory(
        DOCUMENTS_DIR,
        filename,
        as_attachment=as_attachment,
        download_name=os.path.basename(filename),
    )


@app.route('/api/photos/<path:filename>', methods=['GET'])
def serve_photo(filename):
    if not get_authenticated_user():
        return jsonify({'error': 'Unauthorized'}), 401
    if not os.path.isdir(PHOTO_DIR):
        return jsonify({'error': 'Photo directory not found'}), 404
    if request.args.get('download') == '1':
        return send_from_directory(
            PHOTO_DIR,
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename),
        )
    return send_from_directory(PHOTO_DIR, filename)


@app.route('/api/shared-photos', methods=['GET'])
def shared_photos():
    if not get_authenticated_user():
        return jsonify({'error': 'Unauthorized'}), 401
    shared_dir = os.path.join(PHOTO_DIR, 'both')
    if not os.path.isdir(shared_dir):
        return jsonify({'error': 'Shared photo directory not found'}), 404
    image_extensions = {'.png', '.jpeg', '.webp', '.gif', '.jpg'}
    filenames = [
        fname
        for fname in os.listdir(shared_dir)
        if os.path.splitext(fname)[1].lower() in image_extensions
    ]
    return jsonify({'photos': filenames}), 200


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    users = load_users()
    user = users.get(username)
    if not user:
        record_failed_attempt(username)
        return jsonify({'error': 'Invalid credentials'}), 401

    if is_locked_out(username):
        wait_time = get_lockout_remaining_seconds(username)
        return jsonify({'error': f'Account locked. Try again in {wait_time}s.'}), 423

    if not verify_password(password, user.get('password_hash', '')):
        record_failed_attempt(username)
        return jsonify({'error': 'Invalid credentials'}), 401

    # Store pending username in session for the 4-digit PIN verification step
    session['pending_username'] = username

    # Check if PIN was also supplied (backward compatibility)
    pin = str(data.get('pin', '')).strip()
    if pin:
        stored_pin_hash = user.get('pin_hash', '')
        if not verify_pin(pin, stored_pin_hash):
            record_failed_attempt(username)
            return jsonify({'error': 'Invalid PIN'}), 401

        lockout = load_lockout()
        lockout.pop(username, None)
        save_lockout(lockout)

        session.permanent = True
        app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7
        session['user_id'] = user['id']
        session['username'] = username
        session['role'] = user.get('role', 'member')
        session.pop('pending_username', None)
        return jsonify({'message': 'Login successful'}), 200

    return jsonify({'message': 'Password verified', 'username': username}), 200


@app.route('/api/pin', methods=['POST'])
def verify_pin_endpoint():
    data = request.get_json(silent=True) or {}
    pin = str(data.get('pin', '')).strip()

    if not pin or len(pin) != 4:
        return jsonify({'error': 'PIN must be exactly 4 digits'}), 400

    username = session.get('pending_username') or session.get('username')
    if not username:
        return jsonify({'error': 'Session expired. Please log in again.'}), 401

    if is_locked_out(username):
        wait_time = get_lockout_remaining_seconds(username)
        return jsonify({'error': f'Account locked. Try again in {wait_time}s.'}), 423

    users = load_users()
    user = users.get(username)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    stored_pin_hash = user.get('pin_hash', '')
    if not verify_pin(pin, stored_pin_hash):
        record_failed_attempt(username)
        return jsonify({'error': 'Incorrect PIN. Please try again.'}), 401

    # PIN matched! Clear lockout failures and establish full session
    lockout = load_lockout()
    lockout.pop(username, None)
    save_lockout(lockout)

    session.permanent = True
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7
    session['user_id'] = user['id']
    session['username'] = username
    session['role'] = user.get('role', 'member')
    session.pop('pending_username', None)

    return jsonify({'message': 'PIN verified successfully'}), 200


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'}), 200


@app.route('/api/forgot-pin/<username>', methods=['POST'])
def forgot_pin(username):
    users = load_users()
    if username not in users:
        return jsonify({'error': 'User not found'}), 404

    new_pin = str(secrets.randbelow(10000)).zfill(4)
    users[username]['pin_hash'] = hash_pin(new_pin)
    save_users(users)
    return jsonify({'message': f'PIN reset. Your new PIN is: {new_pin}'}), 200


@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')
    pin = str(data.get('pin', '')).zfill(4) if data.get('pin') else ''

    users = load_users()
    if users.get(username):
        return jsonify({'error': 'Username already exists'}), 409

    if not password or len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    if not pin or len(pin) != 4:
        return jsonify({'error': 'PIN must be exactly 4 digits'}), 400

    users[username] = {
        'id': str(len(users) + 1),
        'username': username,
        'password_hash': hash_password(password),
        'pin_hash': hash_pin(pin),
        'role': 'member',
    }
    save_users(users)
    return jsonify({'message': 'User created. Please login with your PIN.'}), 201


@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    user = get_authenticated_user()
    if not user:
        session.clear()
        return jsonify({'error': 'Unauthorized'}), 401

    username = user.get('username')

    posts = []
    posts_path = os.path.join(DATA_DIR, 'posts.json')
    if os.path.exists(posts_path):
        try:
            with open(posts_path, 'r', encoding='utf-8') as file:
                posts = json.load(file) or []
        except (json.JSONDecodeError, OSError):
            posts = []

    events = []
    events_path = os.path.join(DATA_DIR, 'events.json')
    if os.path.exists(events_path):
        try:
            with open(events_path, 'r', encoding='utf-8') as file:
                events = json.load(file) or []
        except (json.JSONDecodeError, OSError):
            events = []

    return jsonify({
        'username': username,
        'posts': posts,
        'events': events,
    }), 200


if __name__ == '__main__':
    app.run(debug=True, port=5000)
