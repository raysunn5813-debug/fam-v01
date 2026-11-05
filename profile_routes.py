import os
import secrets
from datetime import datetime, timezone

from flask import Blueprint, jsonify, redirect, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from services import (
    PROFILE_PHOTOS_DIR,
    get_authenticated_user,
    get_profile,
    load_profiles,
    load_users,
    save_profiles,
)


profile_bp = Blueprint('profile', __name__)
MAX_PROFILE_PHOTOS = 20
MAX_PROFILE_PHOTO_SIZE = 5 * 1024 * 1024
IMAGE_SIGNATURES = {
    '.gif': (b'GIF87a', b'GIF89a'),
    '.jpeg': (b'\xff\xd8\xff',),
    '.jpg': (b'\xff\xd8\xff',),
    '.png': (b'\x89PNG\r\n\x1a\n',),
    '.webp': (b'RIFF',),
}


@profile_bp.route('/profile', methods=['GET'])
def profile_page():
    if not get_authenticated_user():
        return redirect('/')
    return render_template('profile.html')


@profile_bp.route('/api/profile', methods=['GET', 'PUT'])
def profile_api():
    user = get_authenticated_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    profiles = load_profiles()
    profile = get_profile(profiles, user)
    if request.method == 'GET':
        profile['photos'] = [
            {
                **photo,
                'url': f"/api/profile/photos/{photo['filename']}",
            }
            for photo in profile['photos']
        ]
        if profile['avatar_filename']:
            profile['avatar_url'] = f"/api/profile/avatar/{user['id']}"
        else:
            profile['avatar_url'] = ''
        return jsonify({'profile': profile})

    data = request.get_json(silent=True) or {}
    display_name = data.get('display_name', profile['display_name'])
    bio = data.get('bio', profile['bio'])
    avatar_filename = data.get('avatar_filename', profile['avatar_filename'])
    if not isinstance(display_name, str) or not display_name.strip() or len(display_name.strip()) > 80:
        return jsonify({'error': 'Display name must be between 1 and 80 characters.'}), 400
    if not isinstance(bio, str) or len(bio.strip()) > 240:
        return jsonify({'error': 'Bio must be 240 characters or fewer.'}), 400
    if not isinstance(avatar_filename, str) or (
        avatar_filename and avatar_filename not in {photo['filename'] for photo in profile['photos']}
    ):
        return jsonify({'error': 'Choose a photo from your profile gallery.'}), 400

    profile.update({
        'display_name': display_name.strip(),
        'bio': bio.strip(),
        'avatar_filename': avatar_filename,
    })
    profiles[user['id']] = profile
    save_profiles(profiles)
    return jsonify({'profile': profile})


@profile_bp.route('/api/profile/photos', methods=['POST'])
def upload_profile_photo():
    user = get_authenticated_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    photo = request.files.get('photo')
    if not photo or not photo.filename:
        return jsonify({'error': 'Choose a photo to upload.'}), 400

    filename = secure_filename(photo.filename)
    extension = os.path.splitext(filename)[1].lower()
    signatures = IMAGE_SIGNATURES.get(extension)
    if not signatures:
        return jsonify({'error': 'Use a JPG, PNG, GIF, or WebP image.'}), 400

    content = photo.stream.read(MAX_PROFILE_PHOTO_SIZE + 1)
    if not content or len(content) > MAX_PROFILE_PHOTO_SIZE:
        return jsonify({'error': 'Photo must be no larger than 5 MB.'}), 400
    valid_signature = any(content.startswith(signature) for signature in signatures)
    if extension == '.webp':
        valid_signature = len(content) >= 12 and content.startswith(b'RIFF') and content[8:12] == b'WEBP'
    if not valid_signature:
        return jsonify({'error': 'The uploaded file does not match a supported image format.'}), 400

    profiles = load_profiles()
    profile = get_profile(profiles, user)
    if len(profile['photos']) >= MAX_PROFILE_PHOTOS:
        return jsonify({'error': f'You can store up to {MAX_PROFILE_PHOTOS} profile photos.'}), 400

    stored_filename = f'{secrets.token_hex(16)}{extension}'
    user_photo_dir = os.path.join(PROFILE_PHOTOS_DIR, secure_filename(str(user['id'])))
    os.makedirs(user_photo_dir, exist_ok=True)
    photo_path = os.path.join(user_photo_dir, stored_filename)
    with open(photo_path, 'wb') as uploaded_file:
        uploaded_file.write(content)

    profile['photos'].append({
        'filename': stored_filename,
        'uploaded_at': datetime.now(timezone.utc).isoformat(),
    })
    if not profile['avatar_filename']:
        profile['avatar_filename'] = stored_filename
    profiles[user['id']] = profile
    save_profiles(profiles)
    return jsonify({'message': 'Photo uploaded.', 'filename': stored_filename}), 201


@profile_bp.route('/api/profile/photos/<filename>', methods=['GET', 'DELETE'])
def profile_photo(filename):
    user = get_authenticated_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    profiles = load_profiles()
    profile = get_profile(profiles, user)
    photo = next((item for item in profile['photos'] if item['filename'] == filename), None)
    if not photo:
        return jsonify({'error': 'Profile photo not found.'}), 404

    user_photo_dir = os.path.join(PROFILE_PHOTOS_DIR, secure_filename(str(user['id'])))
    if request.method == 'GET':
        return send_from_directory(user_photo_dir, filename)

    profile['photos'].remove(photo)
    if profile['avatar_filename'] == filename:
        profile['avatar_filename'] = ''
    profiles[user['id']] = profile
    photo_path = os.path.join(user_photo_dir, filename)
    if os.path.isfile(photo_path):
        os.remove(photo_path)
    save_profiles(profiles)
    return jsonify({'message': 'Photo deleted.'})


@profile_bp.route('/api/profile/avatar/<user_id>', methods=['GET'])
def profile_avatar(user_id):
    if not get_authenticated_user():
        return jsonify({'error': 'Unauthorized'}), 401

    owner = next((item for item in load_users().values() if item.get('id') == user_id), None)
    if not owner:
        return jsonify({'error': 'Profile not found.'}), 404
    profile = get_profile(load_profiles(), owner)
    filename = profile['avatar_filename']
    if not filename or filename not in {photo['filename'] for photo in profile['photos']}:
        return jsonify({'error': 'No profile photo selected.'}), 404
    user_photo_dir = os.path.join(PROFILE_PHOTOS_DIR, secure_filename(str(owner['id'])))
    response = send_from_directory(user_photo_dir, filename)
    response.headers['Cache-Control'] = 'no-cache'
    return response
