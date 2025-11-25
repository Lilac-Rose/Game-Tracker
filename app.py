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
import time
from datetime import datetime

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
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
STEAM_API_LAST_CALL = 0
STEAM_API_MIN_INTERVAL = 1.2  # 1.2 seconds between calls to stay safe

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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_favorite INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS steam_import_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        steam_app_id INTEGER UNIQUE,
        game_imported INTEGER DEFAULT 0,
        achievements_imported INTEGER DEFAULT 0,
        last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        error_message TEXT,
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

def steam_api_call_with_rate_limit(url):
    """Make Steam API call with rate limiting"""
    global STEAM_API_LAST_CALL
    
    # Calculate time since last call
    time_since_last_call = time.time() - STEAM_API_LAST_CALL
    if time_since_last_call < STEAM_API_MIN_INTERVAL:
        sleep_time = STEAM_API_MIN_INTERVAL - time_since_last_call
        print(f"Rate limiting: waiting {sleep_time:.2f}s before next Steam API call")
        time.sleep(sleep_time)
    
    try:
        response = requests.get(url, timeout=15)
        STEAM_API_LAST_CALL = time.time()
        return response
    except Exception as e:
        STEAM_API_LAST_CALL = time.time()
        raise e

def get_steam_achievements(app_id, steam_id=None):
    """Get achievements for a Steam game with better error handling"""
    if not STEAM_API_KEY:
        return []
    
    try:
        # Get achievement schema for names/descriptions/icons
        schema_url = f"https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={STEAM_API_KEY}&appid={app_id}"
        schema_response = steam_api_call_with_rate_limit(schema_url)
        
        if schema_response.status_code != 200:
            if schema_response.status_code == 429:
                print(f"Rate limited when fetching achievements for app {app_id}")
                return []
            print(f"Schema request failed for app {app_id}: {schema_response.status_code}")
            return []
            
        # Check if response is valid JSON
        try:
            schema_data = schema_response.json()
        except ValueError:
            print(f"Invalid JSON in schema response for app {app_id}")
            return []
            
        schema_achievements = schema_data.get('game', {}).get('availableGameStats', {}).get('achievements', [])
        
        if not schema_achievements:
            return []  # No achievements available for this game
        
        # If we have a Steam user ID, get their personal achievement progress
        user_achievements = {}
        if STEAM_USER_ID:
            try:
                user_url = f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={app_id}&key={STEAM_API_KEY}&steamid={STEAM_USER_ID}"
                user_response = steam_api_call_with_rate_limit(user_url)
                
                if user_response.status_code == 200:
                    try:
                        user_data = user_response.json()
                        if user_data.get('playerstats', {}).get('success'):
                            for ach in user_data.get('playerstats', {}).get('achievements', []):
                                user_achievements[ach['apiname']] = {
                                    'achieved': ach.get('achieved', 0),
                                    'unlocktime': ach.get('unlocktime', 0)
                                }
                    except ValueError:
                        print(f"Invalid JSON in user achievements for app {app_id}")
                elif user_response.status_code == 429:
                    print(f"Rate limited when fetching user achievements for app {app_id}")
                else:
                    print(f"User achievements request failed for app {app_id}: {user_response.status_code}")
            except Exception as user_err:
                print(f"Error fetching user achievements for app {app_id}: {user_err}")
                # Continue with schema achievements only
        
        # Merge schema with user data
        result = []
        for ach in schema_achievements:
            apiname = ach.get('name', '')
            user_data = user_achievements.get(apiname, {})
            
            # Convert Unix timestamp to date
            unlock_date = None
            if user_data.get('unlocktime', 0) > 0:
                try:
                    from datetime import datetime
                    unlock_date = datetime.fromtimestamp(user_data['unlocktime']).strftime('%Y-%m-%d')
                except:
                    unlock_date = None
            
            result.append({
                'name': ach.get('displayName', ach.get('name', 'Unknown')),
                'description': ach.get('description', ''),
                'icon': ach.get('icon', ''),
                'apiname': apiname,
                'achieved': user_data.get('achieved', 0),
                'unlock_date': unlock_date
            })
        
        return result
    except Exception as e:
        print(f"Error fetching Steam achievements for app {app_id}: {e}")
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

def download_cover_image(url, game_id, steam_app_id):
    """Download a cover image and save it with both game_id and steam_app_id reference"""
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            # Generate filename based on both game_id AND steam_app_id
            ext = url.split('.')[-1].split('?')[0]
            if ext not in ['jpg', 'jpeg', 'png', 'webp']:
                ext = 'jpg'
            
            # Save with steam_app_id in filename for easy debugging
            filename = f"game_{game_id}_{steam_app_id}.{ext}"
            filepath = COVERS_PATH / filename
            
            # Save the image
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            # Return relative URL for the image
            return f"/static/covers/{filename}"
    except Exception as e:
        print(f"Error downloading cover for game {game_id} (Steam App {steam_app_id}): {e}")
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
@app.route('/api/games/<int:game_id>/favorite', methods=['PUT'])
def toggle_favorite(game_id):
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get current favorite status
    cur.execute('SELECT is_favorite FROM games WHERE id=?', (game_id,))
    row = cur.fetchone()
    
    if not row:
        conn.close()
        return jsonify({'error': 'Game not found'}), 404
    
    new_status = 1 - row['is_favorite']
    cur.execute('UPDATE games SET is_favorite=? WHERE id=?', (new_status, game_id))
    conn.commit()
    conn.close()
    
    return jsonify({'is_favorite': new_status})

@app.route('/api/steam/import-library', methods=['POST'])
def import_steam_library():
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    if not STEAM_API_KEY or not STEAM_USER_ID:
        return jsonify({'error': 'Steam API not configured. Please check your .env file.'}), 400
    
    # Robust JSON/Form data handling
    import_achievements = True  # Default value
    
    try:
        if request.is_json:
            data = request.get_json() or {}
            import_achievements = data.get('import_achievements', True)
        else:
            # Handle form data
            import_achievements = request.form.get('import_achievements', 'true').lower() == 'true'
    except Exception as e:
        print(f"Error parsing request data: {e}")
        # Continue with default value
    
    try:
        print("Starting Steam library import...")
        print(f"Import achievements: {import_achievements}")
        
        # Get user's owned games
        games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={STEAM_USER_ID}&include_appinfo=1&include_played_free_games=1"
        print(f"Fetching Steam library from: {games_url}")
        
        games_response = steam_api_call_with_rate_limit(games_url)
        
        if games_response.status_code != 200:
            error_msg = f"Steam API returned status {games_response.status_code}"
            if games_response.status_code == 429:
                error_msg = "Steam API rate limit exceeded. Please wait a few minutes and try again."
            elif games_response.status_code == 401:
                error_msg = "Steam API key invalid or expired. Please check your API key."
            elif games_response.status_code == 403:
                error_msg = "Access forbidden. Your Steam profile may be private or the API key doesn't have required permissions."
            return jsonify({'error': error_msg}), 400
        
        # Check if response is valid JSON
        try:
            games_data = games_response.json()
        except ValueError as e:
            print(f"Invalid JSON from Steam API: {games_response.text[:200]}")
            return jsonify({'error': f'Invalid response from Steam API: {str(e)}'}), 400
        
        steam_games = games_data.get('response', {}).get('games', [])
        
        if not steam_games:
            return jsonify({'error': 'No games found in your Steam library.'}), 400
        
        conn = get_db()
        cur = conn.cursor()
        
        # Get import status for all Steam App IDs
        cur.execute('SELECT steam_app_id, game_imported, achievements_imported FROM steam_import_status')
        import_status = {row['steam_app_id']: row for row in cur.fetchall()}
        
        # Get existing games
        cur.execute('SELECT steam_app_id FROM games WHERE steam_app_id IS NOT NULL')
        existing_app_ids = set(row['steam_app_id'] for row in cur.fetchall())
        
        imported_count = 0
        skipped_count = 0
        resumed_count = 0
        achievements_imported = 0
        achievements_failed = 0
        games_with_achievements = 0
        
        # Sort by playtime (most played first)
        steam_games.sort(key=lambda x: x.get('playtime_forever', 0), reverse=True)
        
        # Limit to avoid rate limiting
        MAX_GAMES_TO_IMPORT = 50 if import_achievements else 1000
        if len(steam_games) > MAX_GAMES_TO_IMPORT:
            print(f"Limiting import to first {MAX_GAMES_TO_IMPORT} games (most played)")
            steam_games = steam_games[:MAX_GAMES_TO_IMPORT]
        
        for i, game in enumerate(steam_games):
            app_id = game.get('appid')
            title = game.get('name', f'App {app_id}')
            
            # Check import status
            status = import_status.get(app_id)
            
            # Skip if fully imported
            if status and status['game_imported'] == 1 and (not import_achievements or status['achievements_imported'] == 1):
                skipped_count += 1
                print(f"Skipping {title} - already fully imported")
                continue
            
            # Skip if already in games table (legacy check)
            if app_id in existing_app_ids and (not status or status['game_imported'] == 0):
                cur.execute(
                    'INSERT OR REPLACE INTO steam_import_status (steam_app_id, game_imported, achievements_imported) VALUES (?, 1, ?)',
                    (app_id, 1 if not import_achievements else 0)
                )
                skipped_count += 1
                print(f"Skipping {title} - already in library")
                continue
            
            print(f"[{i+1}/{len(steam_games)}] Importing {title} (AppID: {app_id})...")
            
            # Import game if not already imported
            if not status or status['game_imported'] == 0:
                hours_played = round(game.get('playtime_forever', 0) / 60, 1) if game.get('playtime_forever', 0) > 0 else None
                
                # Use Steam CDN URL directly - no downloading!
                cover_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
                
                cur.execute(
                    """INSERT INTO games (title, platform, status, hours_played, steam_app_id, cover_url, rating, completion_date) 
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (title, 'PC', 'Playing', hours_played, app_id, cover_url, None, None)
                )
                game_id = cur.lastrowid
                
                # Mark game as imported
                achievements_status = 1 if not import_achievements else 0
                cur.execute(
                    'INSERT OR REPLACE INTO steam_import_status (steam_app_id, game_imported, achievements_imported) VALUES (?, 1, ?)',
                    (app_id, achievements_status)
                )
                imported_count += 1
            else:
                # Game was imported but achievements failed - resume only if we're importing achievements
                game_id = cur.execute('SELECT id FROM games WHERE steam_app_id = ?', (app_id,)).fetchone()['id']
                if import_achievements:
                    resumed_count += 1
                    print(f"  → Resuming achievements import for previously imported game")
            
            # Import achievements if requested and not already done
            if import_achievements and app_id and (not status or status['achievements_imported'] == 0):
                try:
                    steam_achievements = get_steam_achievements(app_id)
                    if steam_achievements and len(steam_achievements) > 0:
                        print(f"  → Importing {len(steam_achievements)} achievements")
                        games_with_achievements += 1
                        
                        # Clear existing achievements for this game (in case of partial import)
                        cur.execute('DELETE FROM achievements WHERE game_id = ?', (game_id,))
                        
                        for ach in steam_achievements:
                            try:
                                cur.execute(
                                    'INSERT INTO achievements (game_id, title, description, date, unlocked, icon_url) VALUES (?,?,?,?,?,?)',
                                    (game_id, ach.get('name'), ach.get('description'), 
                                     ach.get('unlock_date'), ach.get('achieved', 0), ach.get('icon'))
                                )
                            except Exception as ach_error:
                                print(f"    Error inserting achievement: {ach_error}")
                                continue
                        
                        achievements_imported += len(steam_achievements)
                        # Mark achievements as imported
                        cur.execute(
                            'UPDATE steam_import_status SET achievements_imported = 1 WHERE steam_app_id = ?',
                            (app_id,)
                        )
                    else:
                        achievements_failed += 1
                        print(f"  → No achievements found")
                        # Mark as attempted but no achievements
                        cur.execute(
                            'UPDATE steam_import_status SET achievements_imported = 1 WHERE steam_app_id = ?',
                            (app_id,)
                        )
                except Exception as e:
                    achievements_failed += 1
                    print(f"  → Error fetching achievements: {e}")
                    # Record the error but don't mark as imported
                    cur.execute(
                        'UPDATE steam_import_status SET error_message = ? WHERE steam_app_id = ?',
                        (str(e), app_id)
                    )
            elif not import_achievements:
                # If we're not importing achievements, mark them as "done" for this import
                cur.execute(
                    'UPDATE steam_import_status SET achievements_imported = 1 WHERE steam_app_id = ?',
                    (app_id,)
                )
            
            conn.commit()
            
            # Rate limiting - only when importing achievements
            if import_achievements and i < len(steam_games) - 1:
                time.sleep(2)
        
        conn.close()
        
        message = f'Import completed: {imported_count} new games'
        if resumed_count > 0:
            message += f', {resumed_count} resumed'
        if skipped_count > 0:
            message += f', {skipped_count} skipped'
        if import_achievements and achievements_imported > 0:
            message += f' - {achievements_imported} achievements from {games_with_achievements} games'
        if import_achievements and achievements_failed > 0:
            message += f' - {achievements_failed} games had no achievements'
        
        print(message)
        return jsonify({
            'success': True,
            'imported': imported_count,
            'resumed': resumed_count,
            'skipped': skipped_count,
            'achievements_imported': achievements_imported,
            'achievements_failed': achievements_failed,
            'imported_achievements': import_achievements,
            'message': message
        })
    
    except requests.exceptions.Timeout:
        print("Steam API request timed out")
        return jsonify({'error': 'Steam API request timed out. Please try again later.'}), 408
    except requests.exceptions.ConnectionError:
        print("Cannot connect to Steam API")
        return jsonify({'error': 'Cannot connect to Steam API. Please check your internet connection.'}), 503
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

@app.route('/api/fix-image-associations', methods=['POST'])
def fix_image_associations():
    """Fix incorrect image associations between games and covers"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get all games with Steam App IDs
        cur.execute('SELECT id, title, steam_app_id, cover_url FROM games WHERE steam_app_id IS NOT NULL')
        games = cur.fetchall()
        
        fixed_count = 0
        errors = []
        
        for game in games:
            game_id = game['id']
            steam_app_id = game['steam_app_id']
            current_cover = game['cover_url']
            
            # Check if the current cover URL contains the correct steam_app_id
            if current_cover and f"_{steam_app_id}." not in current_cover:
                print(f"Fixing cover for {game['title']} (Game ID: {game_id}, Steam App: {steam_app_id})")
                
                # Download correct cover
                cover_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_app_id}/header.jpg"
                new_cover = download_cover_image(cover_url, game_id, steam_app_id)
                
                if new_cover:
                    # Update the game with correct cover
                    cur.execute('UPDATE games SET cover_url=? WHERE id=?', (new_cover, game_id))
                    fixed_count += 1
                    print(f"  → Fixed: {new_cover}")
                else:
                    errors.append(f"Failed to download cover for {game['title']}")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'fixed_count': fixed_count,
            'errors': errors,
            'message': f'Fixed {fixed_count} image associations'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup-orphaned-images', methods=['POST'])
def cleanup_orphaned_images():
    """Remove image files that don't correspond to any game"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get all cover URLs currently in use
        cur.execute('SELECT cover_url FROM games WHERE cover_url IS NOT NULL')
        used_covers = set(row['cover_url'] for row in cur.fetchall())
        
        # Get all image files in covers directory
        image_files = list(COVERS_PATH.glob("game_*.*"))
        
        removed_count = 0
        for image_file in image_files:
            # Convert to URL path
            image_url = f"/static/covers/{image_file.name}"
            
            # Remove if not used by any game
            if image_url not in used_covers:
                try:
                    image_file.unlink()
                    removed_count += 1
                    print(f"Removed orphaned image: {image_file.name}")
                except Exception as e:
                    print(f"Error removing {image_file.name}: {e}")
        
        conn.close()
        
        return jsonify({
            'success': True,
            'removed_count': removed_count,
            'message': f'Removed {removed_count} orphaned images'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/steam/import-achievements', methods=['POST'])
def import_achievements_only():
    """Import achievements for existing Steam games"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    if not STEAM_API_KEY:
        return jsonify({'error': 'Steam API not configured'}), 400
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get games that have Steam App IDs but no imported achievements
        cur.execute('''
            SELECT g.id, g.title, g.steam_app_id 
            FROM games g 
            LEFT JOIN steam_import_status s ON g.steam_app_id = s.steam_app_id 
            WHERE g.steam_app_id IS NOT NULL 
            AND (s.achievements_imported = 0 OR s.achievements_imported IS NULL)
            LIMIT 50
        ''')
        games = cur.fetchall()
        
        if not games:
            return jsonify({'success': True, 'message': 'No games need achievement import'})
        
        achievements_imported = 0
        games_processed = 0
        games_failed = 0
        
        for i, game in enumerate(games):
            game_id = game['id']
            title = game['title']
            app_id = game['steam_app_id']
            
            print(f"[{i+1}/{len(games)}] Importing achievements for {title}...")
            
            try:
                steam_achievements = get_steam_achievements(app_id)
                if steam_achievements and len(steam_achievements) > 0:
                    print(f"  → Importing {len(steam_achievements)} achievements")
                    
                    # Clear existing achievements
                    cur.execute('DELETE FROM achievements WHERE game_id = ?', (game_id,))
                    
                    for ach in steam_achievements:
                        cur.execute(
                            'INSERT INTO achievements (game_id, title, description, date, unlocked, icon_url) VALUES (?,?,?,?,?,?)',
                            (game_id, ach.get('name'), ach.get('description'), 
                             ach.get('unlock_date'), ach.get('achieved', 0), ach.get('icon'))
                        )
                    
                    achievements_imported += len(steam_achievements)
                    games_processed += 1
                    
                    # Update import status
                    cur.execute(
                        'INSERT OR REPLACE INTO steam_import_status (steam_app_id, game_imported, achievements_imported) VALUES (?, 1, 1)',
                        (app_id,)
                    )
                else:
                    games_failed += 1
                    print(f"  → No achievements found")
                    cur.execute(
                        'INSERT OR REPLACE INTO steam_import_status (steam_app_id, game_imported, achievements_imported) VALUES (?, 1, 1)',
                        (app_id,)
                    )
            except Exception as e:
                games_failed += 1
                print(f"  → Error: {e}")
                cur.execute(
                    'INSERT OR REPLACE INTO steam_import_status (steam_app_id, game_imported, achievements_imported, error_message) VALUES (?, 1, 0, ?)',
                    (app_id, str(e))
                )
            
            conn.commit()
            
            # Rate limiting
            if i < len(games) - 1:
                time.sleep(2)
        
        conn.close()
        
        message = f'Imported {achievements_imported} achievements for {games_processed} games'
        if games_failed > 0:
            message += f' ({games_failed} games failed)'
        
        return jsonify({
            'success': True,
            'achievements_imported': achievements_imported,
            'games_processed': games_processed,
            'games_failed': games_failed,
            'message': message
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/steam/import-status')
def get_steam_import_status():
    """Check current import status"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('''
        SELECT 
            COUNT(*) as total_games,
            SUM(game_imported) as games_imported,
            SUM(achievements_imported) as achievements_imported,
            COUNT(*) - SUM(game_imported) as games_pending,
            COUNT(*) - SUM(achievements_imported) as achievements_pending
        FROM steam_import_status
    ''')
    status = dict(cur.fetchone())
    
    conn.close()
    return jsonify(status)

@app.route('/api/steam/reset-import', methods=['POST'])
def reset_steam_import():
    """Reset import status for retry"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    # Reset achievements import status but keep games
    cur.execute('UPDATE steam_import_status SET achievements_imported = 0, error_message = NULL')
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Import status reset. You can now retry achievement imports.'})
    
@app.route('/api/games')
def api_games():
    conn = get_db()
    cur = conn.cursor()
    
    # Get all games with their tags AND achievement counts
    cur.execute('''
        SELECT g.*, 
               COUNT(CASE WHEN a.unlocked=1 THEN 1 END) as unlocked_achievements,
               COUNT(a.id) as total_achievements
        FROM games g
        LEFT JOIN achievements a ON g.id = a.game_id
        GROUP BY g.id
        ORDER BY g.is_favorite DESC, g.created_at DESC
    ''')
    rows = [dict(r) for r in cur.fetchall()]
    
    # Add tags to each game
    for game in rows:
        cur.execute('SELECT tag FROM tags WHERE game_id=?', (game['id'],))
        game['tags'] = [r['tag'] for r in cur.fetchall()]
        
        # Add achievement progress data
        if game['total_achievements'] > 0:
            game['achievement_progress'] = {
                'unlocked_achievements': game['unlocked_achievements'],
                'total_achievements': game['total_achievements']
            }
        else:
            game['achievement_progress'] = None
    
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
    
    # Get achievement progress per game - SORTED BY PERCENTAGE
    cur.execute('''
        SELECT g.id, g.title, 
               COUNT(CASE WHEN a.unlocked=1 THEN 1 END) as unlocked_achievements,
               COUNT(a.id) as total_achievements,
               CASE 
                 WHEN COUNT(a.id) > 0 THEN 
                   ROUND((COUNT(CASE WHEN a.unlocked=1 THEN 1 END) * 100.0 / COUNT(a.id)), 1)
                 ELSE 0 
               END as completion_percentage
        FROM games g
        LEFT JOIN achievements a ON g.id = a.game_id
        GROUP BY g.id
        HAVING total_achievements > 0
        ORDER BY completion_percentage DESC, total_achievements DESC
    ''')
    achievement_progress = [dict(r) for r in cur.fetchall()]
    
    # Rest of your stats code remains the same...
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