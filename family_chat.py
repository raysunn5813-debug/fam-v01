import secrets
from datetime import datetime, timezone

from flask import Blueprint, jsonify, redirect, render_template, request, session

from services import (
    CHATS_PATH,
    get_authenticated_user,
    get_profile,
    load_family_data,
    load_profiles,
    load_users,
    save_family_data,
    valid_family_branch,
)


chat_bp = Blueprint('family_chat', __name__)


@chat_bp.route('/family/<family>/chat', methods=['GET'])
def family_chat_page(family):
    if not get_authenticated_user():
        return redirect('/')
    family = family.lower()
    if not valid_family_branch(family):
        return jsonify({'error': 'Unknown family branch'}), 404
    family_label = 'Cantey/Canty' if family == 'cantey' else 'Thomas'
    return render_template('family_chat.html', family=family, family_label=family_label)


@chat_bp.route('/api/chat/<family>', methods=['GET', 'POST'])
def family_chat(family):
    user = get_authenticated_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    family = family.lower()
    if not valid_family_branch(family):
        return jsonify({'error': 'Unknown family branch'}), 404

    chats = load_family_data(CHATS_PATH)
    messages = chats.setdefault(family, [])
    if request.method == 'GET':
        users = load_users()
        users_by_id = {user_record.get('id'): user_record for user_record in users.values()}
        profiles = load_profiles()
        serialized_messages = []
        for message in messages:
            serialized = dict(message)
            username = message.get('author', '')
            author_id = message.get('author_id', '')
            author_user = users_by_id.get(author_id) or users.get(username, {})
            author_id = author_id or author_user.get('id', '')
            author_profile = get_profile(profiles, author_user) if author_user else {}
            if author_profile:
                serialized['author'] = author_profile['display_name']
            avatar_filename = author_profile.get('avatar_filename', '')
            if avatar_filename and avatar_filename in {
                photo['filename'] for photo in author_profile['photos']
            }:
                serialized['avatar_url'] = f'/api/profile/avatar/{author_id}'
            else:
                serialized['avatar_url'] = ''
            serialized_messages.append(serialized)
        return jsonify({'messages': serialized_messages})

    data = request.get_json(silent=True) or {}
    message_text = data.get('message', '')
    if not isinstance(message_text, str):
        return jsonify({'error': 'Message must be text'}), 400
    message_text = message_text.strip()
    if not message_text or len(message_text) > 2000:
        return jsonify({'error': 'Message must be between 1 and 2000 characters'}), 400

    profile = get_profile(load_profiles(), user)
    messages.append({
        'id': secrets.token_urlsafe(12),
        'author': profile['display_name'],
        'author_id': session['user_id'],
        'text': message_text,
        'created_at': datetime.now(timezone.utc).isoformat(),
    })
    save_family_data(CHATS_PATH, chats)
    return jsonify({'message': messages[-1]}), 201
