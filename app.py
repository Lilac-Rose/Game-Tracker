from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
import os
import requests
from datetime import datetime
import hashlib
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables
load_dotenv()

# Paths and constants
DB_PATH = Path(__file__).parent / "data" / "gametracker.db"
DB_PATH.parent.mkdir(exist_ok=True)
COVERS_PATH = Path(__file__).parent / "static" / "covers"
COVERS_PATH.mkdir(exist_ok=True)
SECRET_KEY = os.getenv("SECRET_KEY", "fallback_dev_key")
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")
STEAM_USER_ID = os.getenv("STEAM_USER_ID", "")  # Your 64-bit Steam ID
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")  # Change this in .env!

# Database helpers
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        platform TEXT,
        status TEXT,
        notes TEXT,
        rating INTEGER,
        hours_played REAL,
        steam_app_id INTEGER,
        cover_url TEXT,
        completion_date TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        title TEXT NOT NULL,
        description TEXT,
        date TEXT,
        unlocked INTEGER DEFAULT 1,
        icon_url TEXT,
        FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS completionist_achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        title TEXT NOT NULL,
        description TEXT,
        difficulty INTEGER,
        time_to_complete TEXT,
        completion_date TEXT,
        notes TEXT,
        completed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        tag TEXT NOT NULL,
        FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        start_time TEXT,
        end_time TEXT,
        duration_minutes INTEGER,
        FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
    );
    ''')
    conn.commit()
    conn.close()

# Flask app
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 30  # 30 days

# Initialize DB before serving requests
init_db()

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Steam API helpers
def search_steam_games(query):
    """Search for games on Steam"""
    try:
        # Use Steam's storefront search API
        url = f"https://store.steampowered.com/api/storesearch/?term={query}&l=english&cc=US"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            items = data.get('items', [])[:5]
            # Add capsule image URL for each game
            for item in items:
                app_id = item.get('id')
                # Steam capsule image URL format: https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg
                item['capsule_image'] = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
            return items
    except:
        pass
    return []

def get_steam_achievements(app_id, steam_id=None):
    """Get achievements for a Steam game"""
    if not STEAM_API_KEY:
        return []
    
    try:
        # Get achievement schema for names/descriptions/icons
        schema_url = f"https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={STEAM_API_KEY}&appid={app_id}"
        schema_response = requests.get(schema_url, timeout=5)
        
        if schema_response.status_code != 200:
            return []
            
        schema_data = schema_response.json()
        schema_achievements = schema_data.get('game', {}).get('availableGameStats', {}).get('achievements', [])
        
        # If we have a Steam user ID, get their personal achievement progress
        user_achievements = {}
        if STEAM_USER_ID:
            user_url = f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={app_id}&key={STEAM_API_KEY}&steamid={STEAM_USER_ID}"
            user_response = requests.get(user_url, timeout=5)
            
            if user_response.status_code == 200:
                user_data = user_response.json()
                if user_data.get('playerstats', {}).get('success'):
                    for ach in user_data.get('playerstats', {}).get('achievements', []):
                        user_achievements[ach['apiname']] = {
                            'achieved': ach.get('achieved', 0),
                            'unlocktime': ach.get('unlocktime', 0)
                        }
        
        # Merge schema with user data
        result = []
        for ach in schema_achievements:
            apiname = ach.get('name', '')
            user_data = user_achievements.get(apiname, {})
            
            # Convert Unix timestamp to date
            unlock_date = None
            if user_data.get('unlocktime', 0) > 0:
                from datetime import datetime
                unlock_date = datetime.fromtimestamp(user_data['unlocktime']).strftime('%Y-%m-%d')
            
            result.append({
                'name': ach.get('displayName', ach.get('name')),
                'description': ach.get('description', ''),
                'icon': ach.get('icon', ''),
                'apiname': apiname,
                'achieved': user_data.get('achieved', 0),
                'unlock_date': unlock_date
            })
        
        return result
    except Exception as e:
        print(f"Error fetching Steam achievements: {e}")
        return []

def get_steam_game_details(app_id):
    """Get game details including hours played and tags"""
    details = {
        'hours_played': None,
        'tags': []
    }
    
    try:
        # Get hours played from user's library
        if STEAM_API_KEY and STEAM_USER_ID:
            games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={STEAM_USER_ID}&include_appinfo=1&include_played_free_games=1"
            games_response = requests.get(games_url, timeout=5)
            
            if games_response.status_code == 200:
                games_data = games_response.json()
                for game in games_data.get('response', {}).get('games', []):
                    if game.get('appid') == app_id:
                        playtime_minutes = game.get('playtime_forever', 0)
                        details['hours_played'] = round(playtime_minutes / 60, 1) if playtime_minutes > 0 else None
                        break
        
        # Get tags from Steam store page
        store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
        store_response = requests.get(store_url, timeout=5)
        
        if store_response.status_code == 200:
            store_data = store_response.json()
            app_data = store_data.get(str(app_id), {})
            if app_data.get('success'):
                game_data = app_data.get('data', {})
                # Get genres as tags
                genres = game_data.get('genres', [])
                details['tags'] = [g['description'] for g in genres[:5]]  # Limit to 5 tags
                
                # Also try to get categories
                categories = game_data.get('categories', [])
                category_names = [c['description'] for c in categories[:3]]
                details['tags'].extend(category_names)
                
                # Remove duplicates
                details['tags'] = list(dict.fromkeys(details['tags']))[:5]
    
    except Exception as e:
        print(f"Error fetching Steam game details: {e}")
    
    return details

def download_cover_image(url, game_id):
    """Download a cover image and save it locally"""
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            # Generate filename based on game_id
            ext = url.split('.')[-1].split('?')[0]  # Get extension from URL
            if ext not in ['jpg', 'jpeg', 'png', 'webp']:
                ext = 'jpg'
            filename = f"game_{game_id}.{ext}"
            filepath = COVERS_PATH / filename
            
            # Save the image
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            # Return relative URL for the image
            return f"/static/covers/{filename}"
    except Exception as e:
        print(f"Error downloading cover: {e}")
    return None

# Routes
@app.route('/')
def index():
    return render_template('index.html', logged_in=session.get('logged_in', False))

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    password = data.get('password')
    
    if password == ADMIN_PASSWORD:
        session['logged_in'] = True
        session.permanent = True
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Invalid password'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return jsonify({'success': True})

@app.route('/api/auth/check')
def check_auth():
    return jsonify({'logged_in': session.get('logged_in', False)})

# API endpoints
@app.route('/api/games', methods=['GET', 'POST'])
def api_games():
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        # Require authentication for POST
        if not session.get('logged_in'):
            return jsonify({'error': 'Authentication required'}), 401
        
        data = request.json
        
        # Download cover image if URL is provided and it's an external URL
        cover_url = data.get('cover_url')
        if cover_url and (cover_url.startswith('http://') or cover_url.startswith('https://')):
            # First insert to get the game ID
            cur.execute(
                """INSERT INTO games (title, platform, status, notes, rating, hours_played, 
                   steam_app_id, cover_url, completion_date) 
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (data.get('title'), data.get('platform'), data.get('status'), 
                 data.get('notes'), data.get('rating'), data.get('hours_played'),
                 data.get('steam_app_id'), None, data.get('completion_date'))
            )
            conn.commit()
            new_id = cur.lastrowid
            
            # Download the cover image
            local_cover = download_cover_image(cover_url, new_id)
            if local_cover:
                # Update with local path
                cur.execute('UPDATE games SET cover_url=? WHERE id=?', (local_cover, new_id))
                conn.commit()
        else:
            cur.execute(
                """INSERT INTO games (title, platform, status, notes, rating, hours_played, 
                   steam_app_id, cover_url, completion_date) 
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (data.get('title'), data.get('platform'), data.get('status'), 
                 data.get('notes'), data.get('rating'), data.get('hours_played'),
                 data.get('steam_app_id'), cover_url, data.get('completion_date'))
            )
            conn.commit()
            new_id = cur.lastrowid
        
        # Add tags if provided
        if data.get('tags'):
            for tag in data.get('tags', []):
                cur.execute('INSERT INTO tags (game_id, tag) VALUES (?,?)', (new_id, tag))
            conn.commit()
        
        conn.close()
        return jsonify({'id': new_id}), 201
    else:
        # Get all games with their tags
        cur.execute('SELECT * FROM games ORDER BY created_at DESC')
        rows = [dict(r) for r in cur.fetchall()]
        
        # Add tags to each game
        for game in rows:
            cur.execute('SELECT tag FROM tags WHERE game_id=?', (game['id'],))
            game['tags'] = [r['tag'] for r in cur.fetchall()]
        
        conn.close()
        return jsonify(rows)

@app.route('/api/games/<int:game_id>', methods=['GET', 'PUT', 'DELETE'])
def api_game(game_id):
    # Require authentication for PUT and DELETE
    if request.method in ['PUT', 'DELETE'] and not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'GET':
        cur.execute('SELECT * FROM games WHERE id=?', (game_id,))
        row = cur.fetchone()
        if row:
            game = dict(row)
            cur.execute('SELECT tag FROM tags WHERE game_id=?', (game_id,))
            game['tags'] = [r['tag'] for r in cur.fetchall()]
            conn.close()
            return jsonify(game)
        conn.close()
        return ('', 404)
    
    elif request.method == 'PUT':
        data = request.json
        
        # Handle cover image update
        cover_url = data.get('cover_url')
        existing_cover = None
        
        # Get existing cover to check if we need to download a new one
        cur.execute('SELECT cover_url FROM games WHERE id=?', (game_id,))
        row = cur.fetchone()
        if row:
            existing_cover = row['cover_url']
        
        # Download new cover if it's a different external URL
        if cover_url and (cover_url.startswith('http://') or cover_url.startswith('https://')) and cover_url != existing_cover:
            local_cover = download_cover_image(cover_url, game_id)
            if local_cover:
                cover_url = local_cover
        
        cur.execute(
            """UPDATE games SET title=?, platform=?, status=?, notes=?, rating=?, 
               hours_played=?, steam_app_id=?, cover_url=?, completion_date=? WHERE id=?""",
            (data.get('title'), data.get('platform'), data.get('status'), 
             data.get('notes'), data.get('rating'), data.get('hours_played'),
             data.get('steam_app_id'), cover_url, 
             data.get('completion_date'), game_id)
        )
        
        # Update tags
        cur.execute('DELETE FROM tags WHERE game_id=?', (game_id,))
        for tag in data.get('tags', []):
            cur.execute('INSERT INTO tags (game_id, tag) VALUES (?,?)', (game_id, tag))
        
        conn.commit()
        conn.close()
        return ('', 204)
    
    else:  # DELETE
        cur.execute('DELETE FROM games WHERE id=?', (game_id,))
        conn.commit()
        conn.close()
        return ('', 204)

@app.route('/api/games/<int:game_id>/achievements', methods=['GET', 'POST'])
def api_achievements(game_id):
    # Require authentication for POST
    if request.method == 'POST' and not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        data = request.json
        cur.execute(
            'INSERT INTO achievements (game_id, title, description, date, unlocked, icon_url) VALUES (?,?,?,?,?,?)',
            (game_id, data.get('title'), data.get('description'), 
             data.get('date'), data.get('unlocked', 1), data.get('icon_url'))
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return jsonify({'id': new_id}), 201
    else:
        cur.execute('SELECT * FROM achievements WHERE game_id=? ORDER BY date DESC, id DESC', (game_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify(rows)

@app.route('/api/games/<int:game_id>/achievements/<int:ach_id>', methods=['PUT', 'DELETE'])
def api_achievement(game_id, ach_id):
    # Require authentication for PUT and DELETE
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'PUT':
        data = request.json
        cur.execute(
            'UPDATE achievements SET unlocked=? WHERE id=? AND game_id=?',
            (data.get('unlocked', 1), ach_id, game_id)
        )
        conn.commit()
        conn.close()
        return ('', 204)
    else:  # DELETE
        cur.execute('DELETE FROM achievements WHERE id=? AND game_id=?', (ach_id, game_id))
        conn.commit()
        conn.close()
        return ('', 204)

@app.route('/api/steam/search')
def steam_search():
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    results = search_steam_games(query)
    return jsonify(results)

@app.route('/api/steam/achievements/<int:app_id>')
def steam_achievements(app_id):
    achievements = get_steam_achievements(app_id)
    return jsonify(achievements)

@app.route('/api/steam/game-details/<int:app_id>')
def steam_game_details(app_id):
    details = get_steam_game_details(app_id)
    return jsonify(details)

@app.route('/api/stats')
def api_stats():
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT COUNT(*) as total FROM games')
    total = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as completed FROM games WHERE status='Completed'")
    completed = cur.fetchone()['completed']
    
    cur.execute('SELECT SUM(hours_played) as total_hours FROM games')
    total_hours = cur.fetchone()['total_hours'] or 0
    
    cur.execute('SELECT COUNT(*) as total_achievements FROM achievements WHERE unlocked=1')
    achievements_unlocked = cur.fetchone()['total_achievements']
    
    cur.execute('SELECT COUNT(*) as total_achievements FROM achievements')
    achievements_total = cur.fetchone()['total_achievements']
    
    # Get achievement progress per game
    cur.execute('''
        SELECT g.id, g.title, 
               COUNT(CASE WHEN a.unlocked=1 THEN 1 END) as unlocked_achievements,
               COUNT(a.id) as total_achievements
        FROM games g
        LEFT JOIN achievements a ON g.id = a.game_id
        GROUP BY g.id
        HAVING total_achievements > 0
        ORDER BY g.created_at DESC
    ''')
    achievement_progress = [dict(r) for r in cur.fetchall()]
    
    # Get status breakdown
    cur.execute('''
        SELECT status, COUNT(*) as count FROM games 
        WHERE status IS NOT NULL AND status != ''
        GROUP BY status
    ''')
    status_breakdown = {row['status']: row['count'] for row in cur.fetchall()}
    
    # Get platform breakdown
    cur.execute('''
        SELECT platform, COUNT(*) as count FROM games 
        WHERE platform IS NOT NULL AND platform != ''
        GROUP BY platform
    ''')
    platform_breakdown = {row['platform']: row['count'] for row in cur.fetchall()}
    
    # Get recent completions
    cur.execute('''
        SELECT id, title, cover_url, completion_date FROM games 
        WHERE status='Completed' AND completion_date IS NOT NULL
        ORDER BY completion_date DESC
        LIMIT 5
    ''')
    recent_completions = [dict(r) for r in cur.fetchall()]
    
    conn.close()
    
    return jsonify({
        'total_games': total,
        'completed_games': completed,
        'total_hours': round(total_hours, 1),
        'achievements_unlocked': achievements_unlocked,
        'achievements_total': achievements_total,
        'achievement_progress': achievement_progress,
        'status_breakdown': status_breakdown,
        'platform_breakdown': platform_breakdown,
        'recent_completions': recent_completions
    })

@app.route('/api/games/<int:game_id>/completionist', methods=['GET', 'POST'])
def api_completionist_achievements(game_id):
    # Require authentication for POST
    if request.method == 'POST' and not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        data = request.json
        cur.execute(
            '''INSERT INTO completionist_achievements 
               (game_id, title, description, difficulty, time_to_complete, completion_date, notes, completed) 
               VALUES (?,?,?,?,?,?,?,?)''',
            (game_id, data.get('title'), data.get('description'), 
             data.get('difficulty'), data.get('time_to_complete'), 
             data.get('completion_date'), data.get('notes'), data.get('completed', 0))
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return jsonify({'id': new_id}), 201
    else:
        # Get sort parameter
        sort_by = request.args.get('sort', 'date')
        
        if sort_by == 'difficulty':
            order = 'difficulty DESC'
        else:
            order = 'created_at DESC'
        
        cur.execute(f'SELECT * FROM completionist_achievements WHERE game_id=? ORDER BY {order}', (game_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify(rows)

@app.route('/api/games/<int:game_id>/completionist/<int:comp_id>', methods=['PUT', 'DELETE'])
def api_completionist_achievement(game_id, comp_id):
    # Require authentication
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'PUT':
        data = request.json
        cur.execute(
            '''UPDATE completionist_achievements 
               SET title=?, description=?, difficulty=?, time_to_complete=?, completion_date=?, notes=?, completed=?
               WHERE id=? AND game_id=?''',
            (data.get('title'), data.get('description'), data.get('difficulty'),
             data.get('time_to_complete'), data.get('completion_date'), 
             data.get('notes'), data.get('completed', 0), comp_id, game_id)
        )
        conn.commit()
        conn.close()
        return ('', 204)
    else:  # DELETE
        cur.execute('DELETE FROM completionist_achievements WHERE id=? AND game_id=?', (comp_id, game_id))
        conn.commit()
        conn.close()
        return ('', 204)

@app.route('/api/completionist/all')
def api_all_completionist():
    conn = get_db()
    cur = conn.cursor()
    
    sort_by = request.args.get('sort', 'date')
    filter_status = request.args.get('status', 'all')  # 'all', 'completed', 'in_progress'
    
    if sort_by == 'difficulty':
        order = 'ca.difficulty DESC'
    elif sort_by == 'date':
        order = 'ca.created_at DESC'
    else:
        order = 'ca.created_at DESC'
    
    if filter_status == 'completed':
        cur.execute(f'''
            SELECT ca.*, g.title as game_title, g.id as game_id FROM completionist_achievements ca
            JOIN games g ON ca.game_id = g.id
            WHERE ca.completed = 1
            ORDER BY {order}
        ''')
    elif filter_status == 'in_progress':
        cur.execute(f'''
            SELECT ca.*, g.title as game_title, g.id as game_id FROM completionist_achievements ca
            JOIN games g ON ca.game_id = g.id
            WHERE ca.completed = 0
            ORDER BY {order}
        ''')
    else:
        cur.execute(f'''
            SELECT ca.*, g.title as game_title, g.id as game_id FROM completionist_achievements ca
            JOIN games g ON ca.game_id = g.id
            ORDER BY {order}
        ''')
    
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)

# Run locally for debugging
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)