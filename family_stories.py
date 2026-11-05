import mimetypes
import os
import secrets
from datetime import datetime, timezone
from io import BytesIO

from flask import Blueprint, jsonify, redirect, render_template, request, send_file, session
from werkzeug.utils import secure_filename

from services import (
    DATA_DIR,
    FAMILY_STORIES_PATH,
    get_authenticated_user,
    get_profile,
    load_family_data,
    load_profiles,
    load_users,
    save_family_data,
    valid_family_branch,
)


stories_bp = Blueprint('family_stories', __name__)
FAMILY_STORY_AUDIO_DIR = os.path.join(DATA_DIR, 'family_story_audio')
MAX_STORY_AUDIO_SIZE = 5 * 1024 * 1024
STORY_AUDIO_EXTENSIONS = {'.m4a', '.mp3', '.mp4', '.ogg', '.wav', '.webm'}


def _audio_signature_matches(extension, content):
    if extension == '.webm':
        return content.startswith(b'\x1aE\xdf\xa3')
    if extension == '.ogg':
        return content.startswith(b'OggS')
    if extension == '.mp3':
        return content.startswith(b'ID3') or (
            len(content) >= 2 and content[0] == 0xff and content[1] & 0xe0 == 0xe0
        )
    if extension == '.wav':
        return len(content) >= 12 and content.startswith(b'RIFF') and content[8:12] == b'WAVE'
    if extension in {'.m4a', '.mp4'}:
        return len(content) >= 12 and content[4:8] == b'ftyp'
    return False


def _store_audio(uploaded_audio):
    if not uploaded_audio or not uploaded_audio.filename:
        return None, None

    extension = os.path.splitext(secure_filename(uploaded_audio.filename))[1].lower()
    if extension not in STORY_AUDIO_EXTENSIONS:
        return None, 'Use an M4A, MP3, MP4, OGG, WAV, or WebM audio recording.'

    content = uploaded_audio.stream.read(MAX_STORY_AUDIO_SIZE + 1)
    if not content or len(content) > MAX_STORY_AUDIO_SIZE:
        return None, 'Audio recordings must be no larger than 5 MB.'
    if not _audio_signature_matches(extension, content):
        return None, 'The uploaded file does not match a supported audio format.'

    filename = f'{secrets.token_hex(16)}{extension}'
    os.makedirs(FAMILY_STORY_AUDIO_DIR, exist_ok=True)
    with open(os.path.join(FAMILY_STORY_AUDIO_DIR, filename), 'wb') as audio_file:
        audio_file.write(content)
    return filename, None


def _audio_path(filename):
    if not isinstance(filename, str) or not filename or secure_filename(filename) != filename:
        return ''
    return os.path.join(FAMILY_STORY_AUDIO_DIR, filename)


def _delete_audio(filename):
    audio_path = _audio_path(filename)
    if not audio_path:
        return
    if os.path.isfile(audio_path):
        os.remove(audio_path)


def _branch_stories(stories, family):
    entries = stories.get(family, [])
    if not isinstance(entries, list):
        raise ValueError(f'Expected a list of stories for {family}')
    return entries


def _serialize_story(story, users_by_id, profiles, current_user_id, family):
    author_id = story.get('author_id', '')
    author_user = users_by_id.get(author_id, {
        'id': author_id,
        'username': story.get('author', 'Family member'),
    })
    audio_filename = story.get('audio_filename', '')
    audio_path = _audio_path(audio_filename)
    return {
        'id': story.get('id', ''),
        'title': story.get('title', ''),
        'story_type': story.get('story_type', 'memory'),
        'about': story.get('about', ''),
        'text': story.get('text', ''),
        'author': get_profile(profiles, author_user)['display_name'],
        'author_id': author_id,
        'created_at': story.get('created_at', ''),
        'updated_at': story.get('updated_at', ''),
        'audio_url': (
            f'/api/family-stories/{family}/audio/{audio_filename}'
            if audio_filename and os.path.isfile(audio_path)
            else ''
        ),
        'can_edit': bool(current_user_id and author_id == current_user_id),
    }


def _validated_fields(form):
    title = form.get('title', '')
    story_type = form.get('story_type', 'memory')
    about = form.get('about', '')
    story_text = form.get('text', '')
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 100:
        return None, 'Give the story a title between 1 and 100 characters.'
    if story_type not in {'memory', 'history'}:
        return None, 'Choose a memory or family history story.'
    if not isinstance(about, str) or len(about.strip()) > 120:
        return None, 'The family member name must be 120 characters or fewer.'
    if not isinstance(story_text, str) or len(story_text.strip()) > 5000:
        return None, 'Written stories must be 5000 characters or fewer.'
    return {
        'title': title.strip(),
        'story_type': story_type,
        'about': about.strip(),
        'text': story_text.strip(),
    }, None


def _story_error(message, status=400):
    return jsonify({'error': message}), status


@stories_bp.route('/family/<family>/stories', methods=['GET'])
def family_stories_page(family):
    if not get_authenticated_user():
        return redirect('/')
    family = family.lower()
    if not valid_family_branch(family):
        return jsonify({'error': 'Unknown family branch'}), 404
    family_label = 'Cantey/Canty' if family == 'cantey' else 'Thomas'
    other_family = 'thomas' if family == 'cantey' else 'cantey'
    other_family_label = 'Thomas' if family == 'cantey' else 'Cantey/Canty'
    return render_template(
        'family_stories.html',
        family=family,
        family_label=family_label,
        other_family=other_family,
        other_family_label=other_family_label,
    )


@stories_bp.route('/api/family-stories/<family>', methods=['GET', 'POST'])
def family_stories(family):
    user = get_authenticated_user()
    if not user:
        return _story_error('Unauthorized', 401)
    family = family.lower()
    if not valid_family_branch(family):
        return _story_error('Unknown family branch', 404)

    stories_by_family = load_family_data(FAMILY_STORIES_PATH)
    if request.method == 'GET':
        stories = _branch_stories(stories_by_family, family)
        users = load_users()
        users_by_id = {record.get('id'): record for record in users.values()}
        profiles = load_profiles()
        return jsonify({
            'stories': [
                _serialize_story(story, users_by_id, profiles, user.get('id'), family)
                for story in stories
            ]
        })
    stories = stories_by_family.setdefault(family, [])
    if not isinstance(stories, list):
        raise ValueError(f'Expected a list of stories for {family}')

    fields, error = _validated_fields(request.form)
    if error:
        return _story_error(error)
    uploaded_audio = request.files.get('audio')
    if not fields['text'] and not (uploaded_audio and uploaded_audio.filename):
        return _story_error('Add some written story text or an audio recording.')

    audio_filename, error = _store_audio(uploaded_audio)
    if error:
        return _story_error(error)

    now = datetime.now(timezone.utc).isoformat()
    profile = get_profile(load_profiles(), user)
    story = {
        'id': secrets.token_urlsafe(16),
        **fields,
        'author': profile['display_name'],
        'author_id': session['user_id'],
        'created_at': now,
        'updated_at': now,
        'audio_filename': audio_filename or '',
    }
    stories.append(story)
    try:
        save_family_data(FAMILY_STORIES_PATH, stories_by_family)
    except OSError:
        _delete_audio(audio_filename)
        raise

    users = load_users()
    users_by_id = {record.get('id'): record for record in users.values()}
    return jsonify({
        'story': _serialize_story(story, users_by_id, load_profiles(), user.get('id'), family)
    }), 201


@stories_bp.route('/api/family-stories/<family>/<story_id>', methods=['PUT', 'DELETE'])
def update_or_delete_story(family, story_id):
    user = get_authenticated_user()
    if not user:
        return _story_error('Unauthorized', 401)
    family = family.lower()
    if not valid_family_branch(family):
        return _story_error('Unknown family branch', 404)

    stories_by_family = load_family_data(FAMILY_STORIES_PATH)
    stories = _branch_stories(stories_by_family, family)
    story = next((item for item in stories if item.get('id') == story_id), None)
    if not story:
        return _story_error('Family story not found.', 404)
    if story.get('author_id') != user.get('id'):
        return _story_error('You can only change stories you wrote.', 403)

    old_audio_filename = story.get('audio_filename', '')
    if request.method == 'DELETE':
        stories.remove(story)
        save_family_data(FAMILY_STORIES_PATH, stories_by_family)
        _delete_audio(old_audio_filename)
        return jsonify({'message': 'Story deleted.'})

    fields, error = _validated_fields(request.form)
    if error:
        return _story_error(error)
    uploaded_audio = request.files.get('audio')
    has_new_audio = bool(uploaded_audio and uploaded_audio.filename)
    remove_audio = request.form.get('remove_audio', '').lower() in {'1', 'true', 'yes', 'on'}
    if has_new_audio and remove_audio:
        return _story_error('Choose a new recording or remove the current recording, not both.')

    if remove_audio:
        next_audio_filename = ''
    elif has_new_audio:
        next_audio_filename, error = _store_audio(uploaded_audio)
        if error:
            return _story_error(error)
    else:
        next_audio_filename = old_audio_filename
    if not fields['text'] and not next_audio_filename:
        return _story_error('Add some written story text or an audio recording.')

    story.update(fields)
    story['updated_at'] = datetime.now(timezone.utc).isoformat()
    story['audio_filename'] = next_audio_filename
    try:
        save_family_data(FAMILY_STORIES_PATH, stories_by_family)
    except OSError:
        if has_new_audio:
            _delete_audio(next_audio_filename)
        raise
    if old_audio_filename and old_audio_filename != next_audio_filename:
        _delete_audio(old_audio_filename)

    users = load_users()
    users_by_id = {record.get('id'): record for record in users.values()}
    return jsonify({
        'story': _serialize_story(story, users_by_id, load_profiles(), user.get('id'), family)
    })


@stories_bp.route('/api/family-stories/<family>/audio/<filename>', methods=['GET'])
def family_story_audio(family, filename):
    if not get_authenticated_user():
        return _story_error('Unauthorized', 401)
    family = family.lower()
    if not valid_family_branch(family):
        return _story_error('Unknown family branch', 404)
    stories_by_family = load_family_data(FAMILY_STORIES_PATH)
    stories = _branch_stories(stories_by_family, family)
    if not any(story.get('audio_filename') == filename for story in stories):
        return _story_error('Family story audio not found.', 404)
    audio_path = _audio_path(filename)
    if not audio_path or not os.path.isfile(audio_path):
        return _story_error('Family story audio not found.', 404)
    with open(audio_path, 'rb') as audio_file:
        audio_content = audio_file.read(MAX_STORY_AUDIO_SIZE + 1)
    return send_file(
        BytesIO(audio_content),
        mimetype=mimetypes.guess_type(filename)[0] or 'application/octet-stream',
        download_name=filename,
    )
