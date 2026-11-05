import hashlib
import json
import os
import secrets
import time

import bcrypt
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf

ROOT_DIR = os.path.abspath('.')
MAIN_HTML_FILE = 'index.html'


app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 6291456

@app.route('/<path:path>', methods=['GET'])
def catch_all(path):
    # Redirect any unmatched path (e.g., /photos, /documents) back to index.html for GitHub Pages navigation
    if not path.startswith('api') and not path.startswith('static'):
        return redirect('/index.html', code=302)
    # Let Flask handle API routes normally
    return app.send_static_file(path)


csrf = CSRFProtect(app)

if __name__ == '__main__':
    app.run()