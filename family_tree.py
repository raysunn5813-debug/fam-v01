import json
import os
import secrets
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from services import (
    DATA_DIR,
    FAMILY_TREES_PATH,
    get_authenticated_user,
    load_family_data,
    parse_parent_ids,
    save_family_data,
    valid_family_branch,
)


tree_bp = Blueprint('family_tree', __name__)
FAMILY_TREE_PHOTOS_DIR = os.path.join(DATA_DIR, 'family_tree_photos')
MAX_TREE_PHOTO_SIZE = 5 * 1024 * 1024
TREE_PHOTO_SIGNATURES = {
    '.gif': (b'GIF87a', b'GIF89a'),
    '.jpeg': (b'\xff\xd8\xff',),
    '.jpg': (b'\xff\xd8\xff',),
    '.png': (b'\x89PNG\r\n\x1a\n',),
    '.webp': (b'RIFF',),
}


def _request_data():
    data = request.get_json(silent=True)
    if data is not None:
        return data
    data = request.form.to_dict()
    if 'parent_ids' in data:
        try:
            data['parent_ids'] = json.loads(data['parent_ids'])
        except json.JSONDecodeError:
            return None
    return data


def _store_member_photo(family, uploaded_photo):
    if not uploaded_photo or not uploaded_photo.filename:
        return None, None

    extension = os.path.splitext(secure_filename(uploaded_photo.filename))[1].lower()
    signatures = TREE_PHOTO_SIGNATURES.get(extension)
    if not signatures:
        return None, 'Use a JPG, PNG, GIF, or WebP photo.'

    content = uploaded_photo.stream.read(MAX_TREE_PHOTO_SIZE + 1)
    if not content or len(content) > MAX_TREE_PHOTO_SIZE:
        return None, 'Photo must be no larger than 5 MB.'
    valid_signature = any(content.startswith(signature) for signature in signatures)
    if extension == '.webp':
        valid_signature = len(content) >= 12 and content.startswith(b'RIFF') and content[8:12] == b'WEBP'
    if not valid_signature:
        return None, 'The uploaded file does not match a supported image format.'

    filename = f'{secrets.token_hex(16)}{extension}'
    photo_directory = os.path.join(FAMILY_TREE_PHOTOS_DIR, family)
    os.makedirs(photo_directory, exist_ok=True)
    with open(os.path.join(photo_directory, filename), 'wb') as photo_file:
        photo_file.write(content)
    return filename, None


def _member_with_photo_url(family, member):
    result = dict(member)
    filename = result.get('photo_filename', '')
    photo_path = os.path.join(FAMILY_TREE_PHOTOS_DIR, family, filename)
    result['photo_url'] = (
        f'/api/family-tree/{family}/photos/{filename}'
        if filename and os.path.isfile(photo_path)
        else ''
    )
    return result


def _delete_member_photo(family, filename):
    if not filename:
        return
    photo_path = os.path.join(FAMILY_TREE_PHOTOS_DIR, family, filename)
    if os.path.isfile(photo_path):
        os.remove(photo_path)


@tree_bp.route('/family/<family>/tree', methods=['GET'])
def family_tree_page(family):
    if not get_authenticated_user():
        return redirect('/')
    family = family.lower()
    if not valid_family_branch(family):
        return jsonify({'error': 'Unknown family branch'}), 404
    family_label = 'Cantey/Canty' if family == 'cantey' else 'Thomas'
    return render_template('family_tree.html', family=family, family_label=family_label)


@tree_bp.route('/api/family-tree/<family>', methods=['GET', 'POST'])
def family_tree(family):
    if not get_authenticated_user():
        return jsonify({'error': 'Unauthorized'}), 401
    family = family.lower()
    if not valid_family_branch(family):
        return jsonify({'error': 'Unknown family branch'}), 404

    trees = load_family_data(FAMILY_TREES_PATH)
    members = trees.setdefault(family, {})
    if request.method == 'GET':
        return jsonify({
            'members': [_member_with_photo_url(family, member) for member in members.values()]
        })

    data = _request_data()
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid family member details.'}), 400
    name = data.get('name', '')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        return jsonify({'error': 'Name must be between 1 and 120 characters'}), 400
    parent_ids = parse_parent_ids(data, members)
    if parent_ids is None:
        return jsonify({'error': 'Choose valid parents from this family tree'}), 400

    birth_year = data.get('birth_year', '')
    if birth_year and (not str(birth_year).isdigit() or not 1000 <= int(birth_year) <= datetime.now().year):
        return jsonify({'error': 'Enter a valid birth year'}), 400
    notes = data.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 500:
        return jsonify({'error': 'Notes must be 500 characters or fewer'}), 400

    photo_filename, photo_error = _store_member_photo(family, request.files.get('photo'))
    if photo_error:
        return jsonify({'error': photo_error}), 400
    member = {
        'id': secrets.token_urlsafe(12),
        'name': name.strip(),
        'parent_ids': parent_ids,
        'birth_year': str(birth_year) if birth_year else '',
        'notes': notes.strip(),
        'photo_filename': photo_filename or '',
    }
    members[member['id']] = member
    save_family_data(FAMILY_TREES_PATH, trees)
    return jsonify({'member': _member_with_photo_url(family, member)}), 201


@tree_bp.route('/api/family-tree/<family>/photos/<filename>', methods=['GET'])
def family_tree_photo(family, filename):
    if not get_authenticated_user():
        return jsonify({'error': 'Unauthorized'}), 401
    family = family.lower()
    if not valid_family_branch(family):
        return jsonify({'error': 'Unknown family branch'}), 404

    trees = load_family_data(FAMILY_TREES_PATH)
    is_member_photo = any(
        member.get('photo_filename') == filename
        for member in trees.get(family, {}).values()
    )
    if not is_member_photo:
        return jsonify({'error': 'Family member photo not found.'}), 404
    return send_from_directory(os.path.join(FAMILY_TREE_PHOTOS_DIR, family), filename)


@tree_bp.route('/api/family-tree/<family>/<person_id>', methods=['PUT'])
def update_family_member(family, person_id):
    if not get_authenticated_user():
        return jsonify({'error': 'Unauthorized'}), 401
    family = family.lower()
    if not valid_family_branch(family):
        return jsonify({'error': 'Unknown family branch'}), 404

    trees = load_family_data(FAMILY_TREES_PATH)
    members = trees.setdefault(family, {})
    member = members.get(person_id)
    if not member:
        return jsonify({'error': 'Family member not found'}), 404

    data = _request_data()
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid family member details.'}), 400
    name = data.get('name', '')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        return jsonify({'error': 'Name must be between 1 and 120 characters'}), 400
    parent_ids = parse_parent_ids(data, members, person_id)
    if parent_ids is None:
        return jsonify({'error': 'Choose valid parents without creating a family-tree cycle'}), 400

    birth_year = data.get('birth_year', '')
    if birth_year and (not str(birth_year).isdigit() or not 1000 <= int(birth_year) <= datetime.now().year):
        return jsonify({'error': 'Enter a valid birth year'}), 400
    notes = data.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 500:
        return jsonify({'error': 'Notes must be 500 characters or fewer'}), 400

    old_photo_filename = member.get('photo_filename', '')
    remove_photo = data.get('remove_photo') in (True, 'true', '1')
    if remove_photo and request.files.get('photo') and request.files['photo'].filename:
        return jsonify({'error': 'Choose a new photo or remove the current photo, not both.'}), 400
    photo_filename, photo_error = _store_member_photo(family, request.files.get('photo'))
    if photo_error:
        return jsonify({'error': photo_error}), 400
    if remove_photo:
        photo_filename = ''
    elif not photo_filename:
        photo_filename = old_photo_filename

    member.update({
        'name': name.strip(),
        'parent_ids': parent_ids,
        'birth_year': str(birth_year) if birth_year else '',
        'notes': notes.strip(),
        'photo_filename': photo_filename,
    })
    save_family_data(FAMILY_TREES_PATH, trees)
    if old_photo_filename != photo_filename:
        _delete_member_photo(family, old_photo_filename)
    return jsonify({'member': _member_with_photo_url(family, member)})
