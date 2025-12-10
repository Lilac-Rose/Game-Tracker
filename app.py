from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
import os
import requests
from datetime import datetime, date, timedelta
import hashlib
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import time
from datetime import datetime
import traceback
import threading
import schedule

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
    CREATE TABLE IF NOT EXISTS top10_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER UNIQUE,
        position INTEGER NOT NULL,
        why_i_love_it TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
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
    CREATE TABLE IF NOT EXISTS daily_hours_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL UNIQUE,
        total_hours REAL NOT NULL,
        games_played INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS daily_game_hours (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        game_id INTEGER NOT NULL,
        game_title TEXT NOT NULL,
        hours_played REAL NOT NULL,
        cover_url TEXT,
        FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE,
        UNIQUE(date, game_id)
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

def get_total_hours_played():
    """Get total hours played from all games"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT SUM(hours_played) as total_hours FROM games WHERE hours_played IS NOT NULL')
    result = cur.fetchone()
    conn.close()
    return result['total_hours'] or 0

def update_all_steam_hours_sync():
    """Synchronously update all Steam game hours without achievements"""
    if not STEAM_API_KEY or not STEAM_USER_ID:
        print("Steam API not configured, skipping auto-update")
        return False
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get all Steam games
        cur.execute('SELECT id, steam_app_id FROM games WHERE steam_app_id IS NOT NULL')
        steam_games = cur.fetchall()
        
        if not steam_games:
            conn.close()
            return True
        
        print(f"Auto-updating {len(steam_games)} Steam games...")
        
        # Get current Steam library data in ONE API CALL
        games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={STEAM_USER_ID}&include_appinfo=1"
        games_response = steam_api_call_with_rate_limit(games_url)
        
        if games_response.status_code != 200:
            print(f"Steam API returned status {games_response.status_code}")
            conn.close()
            return False
        
        games_data = games_response.json()
        steam_library = {game['appid']: game for game in games_data.get('response', {}).get('games', [])}
        
        updated_count = 0
        for game in steam_games:
            app_id = game['steam_app_id']
            steam_game = steam_library.get(app_id)
            
            if steam_game:
                playtime_minutes = steam_game.get('playtime_forever', 0)
                hours_played = round(playtime_minutes / 60, 1) if playtime_minutes > 0 else 0
                cur.execute('UPDATE games SET hours_played=? WHERE id=?', (hours_played, game['id']))
                updated_count += 1
        
        conn.commit()
        conn.close()
        
        print(f"Auto-updated {updated_count} Steam games")
        return True
    except Exception as e:
        print(f"Error auto-updating Steam hours: {e}")
        return False

def record_daily_hours():
    """Record today's total hours played (with auto-update from Steam first)"""
    try:
        # First, update all Steam game hours
        print("Running daily Steam hours update...")
        update_all_steam_hours_sync()
        
        today = date.today().isoformat()
        total_hours = get_total_hours_played()
        
        conn = get_db()
        cur = conn.cursor()
        
        # Count how many games have hours played
        cur.execute('SELECT COUNT(*) as count FROM games WHERE hours_played IS NOT NULL AND hours_played > 0')
        games_played = cur.fetchone()['count']
        
        # Insert or update today's record
        cur.execute('''
            INSERT OR REPLACE INTO daily_hours_history (date, total_hours, games_played)
            VALUES (?, ?, ?)
        ''', (today, total_hours, games_played))
        
        # Also save per-game snapshots for the day
        cur.execute('''
            SELECT id, title, hours_played, cover_url 
            FROM games 
            WHERE hours_played IS NOT NULL AND hours_played > 0
            ORDER BY hours_played DESC
        ''')
        games = cur.fetchall()
        
        # Clear existing snapshots for today (in case of re-run)
        cur.execute('DELETE FROM daily_game_hours WHERE date = ?', (today,))
        
        # Insert new snapshots
        for game in games:
            cur.execute('''
                INSERT INTO daily_game_hours (date, game_id, game_title, hours_played, cover_url)
                VALUES (?, ?, ?, ?, ?)
            ''', (today, game['id'], game['title'], game['hours_played'], game['cover_url']))
        
        conn.commit()
        conn.close()
        
        print(f"Recorded daily hours: {today} - {total_hours}h across {games_played} games")
        print(f"Saved {len(games)} game snapshots for {today}")
        return True
    except Exception as e:
        print(f"Error recording daily hours: {e}")
        traceback.print_exc()
        return False

def get_daily_hours_history(days=30):
    """Get daily hours history for the last N days"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT date, total_hours, games_played 
            FROM daily_hours_history 
            ORDER BY date DESC 
            LIMIT ?
        ''', (days,))
        
        history = [dict(row) for row in cur.fetchall()]
        conn.close()
        
        # Fill in missing days with last known value
        if history:
            filled_history = []
            current_date = date.today()
            
            for i in range(days):
                check_date = (current_date - timedelta(days=i)).isoformat()
                day_data = next((h for h in history if h['date'] == check_date), None)
                
                if day_data:
                    filled_history.append(day_data)
                elif filled_history:
                    # Use last known value for missing days
                    last_data = filled_history[-1].copy()
                    last_data['date'] = check_date
                    filled_history.append(last_data)
                else:
                    # No data at all, create empty entry
                    filled_history.append({
                        'date': check_date,
                        'total_hours': 0,
                        'games_played': 0
                    })
            
            # Sort chronologically for chart display
            filled_history.sort(key=lambda x: x['date'])
            return filled_history
        
        return []
    except Exception as e:
        print(f"Error getting daily hours history: {e}")
        return []

@app.route('/api/daily-game-hours/<date>')
def api_daily_game_hours(date):
    """Get per-game hours breakdown for a specific day"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get the snapshot for this date
        cur.execute('''
            SELECT game_id, game_title, hours_played, cover_url
            FROM daily_game_hours
            WHERE date = ?
            ORDER BY hours_played DESC
        ''', (date,))
        
        current_snapshot = [dict(r) for r in cur.fetchall()]
        
        if not current_snapshot:
            conn.close()
            return jsonify({'error': 'No data for this date'}), 404
        
        # Get the previous day's snapshot to calculate hours played ON this day
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        prev_date = (date_obj - timedelta(days=1)).strftime('%Y-%m-%d')
        
        cur.execute('''
            SELECT game_id, hours_played
            FROM daily_game_hours
            WHERE date = ?
        ''', (prev_date,))
        
        prev_snapshot = {row['game_id']: row['hours_played'] for row in cur.fetchall()}
        
        # Calculate hours played on this specific day
        result = []
        for game in current_snapshot:
            prev_hours = prev_snapshot.get(game['game_id'], 0)
            hours_this_day = round(game['hours_played'] - prev_hours, 1)
            
            # Only include games where hours increased
            if hours_this_day > 0:
                result.append({
                    'game_id': game['game_id'],
                    'game_title': game['game_title'],
                    'total_hours': game['hours_played'],
                    'hours_this_day': hours_this_day,
                    'cover_url': game['cover_url']
                })
        
        # Sort by hours played on this day (descending)
        result.sort(key=lambda x: x['hours_this_day'], reverse=True)
        
        conn.close()
        return jsonify(result)
        
    except Exception as e:
        print(f"Error fetching daily game hours: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/record-daily-hours-now', methods=['POST'])
def api_record_daily_hours_now():
    """Manually trigger daily hours recording (admin only)"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        success = record_daily_hours()
        if success:
            return jsonify({'success': True, 'message': 'Daily hours recorded successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to record daily hours'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def schedule_daily_tracking():
    """Schedule daily hours tracking at 12 PM EST"""
    try:
        def job():
            print(f"Scheduled daily tracking running at {datetime.now()}")
            record_daily_hours()
        
        # Schedule at 12 PM EST (17:00 UTC)
        schedule.every().day.at("17:00").do(job)
        
        def run_scheduler():
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        
        # Run scheduler in background thread
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        print("Daily hours tracking scheduler started (12 PM EST daily)")
        
        # Run once immediately to initialize today's data
        record_daily_hours()
    except Exception as e:
        print(f"Failed to start daily tracking scheduler: {e}")
        # Still try to record initial data
        record_daily_hours()

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
    import_achievements = False  # Changed default to False to prevent timeout
    
    try:
        if request.is_json:
            data = request.get_json() or {}
            import_achievements = data.get('import_achievements', False)  # Default to False
        else:
            # Handle form data
            import_achievements = request.form.get('import_achievements', 'false').lower() == 'true'
    except Exception as e:
        print(f"Error parsing request data: {e}")
        # Continue with default value (False)
    
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
        
        # Limit to avoid rate limiting and timeout
        MAX_GAMES_TO_IMPORT = 20 if import_achievements else 1000  # Reduced from 50/1000
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
            
            # Reduced rate limiting to prevent timeout
            if import_achievements and i < len(steam_games) - 1:
                time.sleep(1)  # Reduced from 2 to 1 second
        
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

@app.route('/api/top10', methods=['GET', 'POST', 'PUT'])
def api_top10():
    if request.method == 'GET':
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT t.*, g.title, g.platform, g.cover_url, g.steam_app_id, 
                   g.hours_played, g.rating, g.status
            FROM top10_games t
            JOIN games g ON t.game_id = g.id
            ORDER BY t.position ASC
        ''')
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify(rows)
    
    elif request.method == 'POST':
        if not session.get('logged_in'):
            return jsonify({'error': 'Authentication required'}), 401
        
        data = request.json
        conn = get_db()
        cur = conn.cursor()
        
        # Clear existing top 10
        cur.execute('DELETE FROM top10_games')
        
        # Insert new top 10
        for item in data:
            cur.execute(
                'INSERT INTO top10_games (game_id, position, why_i_love_it) VALUES (?,?,?)',
                (item['game_id'], item['position'], item.get('why_i_love_it', ''))
            )
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    
    elif request.method == 'PUT':
        if not session.get('logged_in'):
            return jsonify({'error': 'Authentication required'}), 401
        
        data = request.json
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute(
            'UPDATE top10_games SET position=?, why_i_love_it=? WHERE game_id=?',
            (data.get('position'), data.get('why_i_love_it'), data.get('game_id'))
        )
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})

@app.route('/api/top10/<int:game_id>', methods=['DELETE'])
def api_delete_top10(game_id):
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM top10_games WHERE game_id=?', (game_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

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
               COUNT(a.id) as total_achievements,
               CASE 
                 WHEN COUNT(a.id) > 0 THEN 
                   ROUND((COUNT(CASE WHEN a.unlocked=1 THEN 1 END) * 100.0 / COUNT(a.id)), 1)
                 ELSE 0 
               END as completion_percentage
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
                'total_achievements': game['total_achievements'],
                'completion_percentage': game['completion_percentage']
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

@app.route('/api/steam/update-game/<int:game_id>', methods=['POST'])
def update_game_from_steam(game_id):
    """Update a single game's data from Steam (including achievements)"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    if not STEAM_API_KEY:
        return jsonify({'error': 'Steam API not configured'}), 400
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get the game
        cur.execute('SELECT steam_app_id, title, status FROM games WHERE id=?', (game_id,))
        game = cur.fetchone()
        
        if not game:
            return jsonify({'error': 'Game not found'}), 404
        
        app_id = game['steam_app_id']
        if not app_id:
            return jsonify({'error': 'Game has no Steam App ID'}), 400
        
        print(f"Updating game {game['title']} (AppID: {app_id}) from Steam...")
        
        # Get updated hours played
        hours_played = None
        if STEAM_USER_ID:
            games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={STEAM_USER_ID}&include_appinfo=1"
            games_response = steam_api_call_with_rate_limit(games_url)
            
            if games_response.status_code == 200:
                games_data = games_response.json()
                for steam_game in games_data.get('response', {}).get('games', []):
                    if steam_game.get('appid') == app_id:
                        playtime_minutes = steam_game.get('playtime_forever', 0)
                        hours_played = round(playtime_minutes / 60, 1) if playtime_minutes > 0 else None
                        break
        
        # Update the game
        if hours_played is not None:
            cur.execute('UPDATE games SET hours_played=? WHERE id=?', (hours_played, game_id))
            print(f"  → Updated hours: {hours_played}h")
        
        # Update achievements and check for completion
        achievements_updated = 0
        all_achievements_unlocked = False
        completion_date = None
        latest_achievement_date = None
        
        steam_achievements = get_steam_achievements(app_id)
        if steam_achievements and len(steam_achievements) > 0:
            # Clear existing achievements to avoid duplicates
            cur.execute('DELETE FROM achievements WHERE game_id=?', (game_id,))
            print(f"  → Cleared existing achievements")
            
            # Track achievement dates to find the most recent one
            achievement_dates = []
            
            for ach in steam_achievements:
                unlock_date = ach.get('unlock_date')
                if unlock_date:
                    achievement_dates.append(unlock_date)
                
                cur.execute(
                    'INSERT INTO achievements (game_id, title, description, date, unlocked, icon_url) VALUES (?,?,?,?,?,?)',
                    (game_id, ach.get('name'), ach.get('description'), 
                     unlock_date, ach.get('achieved', 0), ach.get('icon'))
                )
            
            achievements_updated = len(steam_achievements)
            print(f"  → Updated {achievements_updated} achievements")
            
            # Check if all achievements are unlocked
            unlocked_count = sum(1 for ach in steam_achievements if ach.get('achieved', 0))
            if unlocked_count == len(steam_achievements) and len(steam_achievements) > 0:
                all_achievements_unlocked = True
                print(f"  → All {unlocked_count} achievements unlocked!")
                
                # Find the most recent achievement date
                if achievement_dates:
                    # Convert dates to datetime objects for comparison
                    from datetime import datetime
                    try:
                        date_objects = [datetime.strptime(date, '%Y-%m-%d') for date in achievement_dates if date]
                        if date_objects:
                            latest_date = max(date_objects)
                            completion_date = latest_date.strftime('%Y-%m-%d')
                            latest_achievement_date = completion_date
                            print(f"  → Most recent achievement: {completion_date}")
                    except Exception as date_err:
                        print(f"  → Error parsing dates: {date_err}")
                        # Fallback to today's date
                        completion_date = datetime.now().strftime('%Y-%m-%d')
                else:
                    # No dates available, use today
                    from datetime import datetime
                    completion_date = datetime.now().strftime('%Y-%m-%d')
                
                # Update game status and completion date
                cur.execute('UPDATE games SET status=?, completion_date=? WHERE id=?', 
                           ('Completed', completion_date, game_id))
                print(f"  → Set game as completed on {completion_date}")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'hours_updated': hours_played is not None,
            'achievements_updated': achievements_updated,
            'all_achievements_unlocked': all_achievements_unlocked,
            'completion_date': completion_date,
            'message': f'Updated {game["title"]} from Steam'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Update failed: {str(e)}'}), 500

@app.route('/api/steam/update-all-games', methods=['POST'])
def update_all_games_from_steam():
    """Update all Steam games with current data (hours only, no achievements)"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    if not STEAM_API_KEY or not STEAM_USER_ID:
        return jsonify({'error': 'Steam API not configured. Check your .env file.'}), 400
    
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get all Steam games
        cur.execute('SELECT id, title, steam_app_id FROM games WHERE steam_app_id IS NOT NULL')
        steam_games = cur.fetchall()
        
        if not steam_games:
            conn.close()
            return jsonify({'error': 'No Steam games found in your library.'}), 400
        
        print(f"Attempting to update {len(steam_games)} Steam games...")
        
        # Get current Steam library data in ONE API CALL
        games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={STEAM_USER_ID}&include_appinfo=1"
        
        try:
            games_response = steam_api_call_with_rate_limit(games_url)
            
            if games_response.status_code == 401:
                conn.close()
                return jsonify({'error': 'Steam API key invalid or expired. Please check your API key in .env'}), 401
            elif games_response.status_code == 403:
                conn.close()
                return jsonify({'error': 'Access forbidden. Your Steam profile may be private.'}), 403
            elif games_response.status_code != 200:
                conn.close()
                return jsonify({'error': f'Steam API returned status {games_response.status_code}'}), 500
            
            # Parse JSON response
            try:
                games_data = games_response.json()
            except ValueError as e:
                conn.close()
                print(f"Invalid JSON from Steam API: {games_response.text[:200]}")
                return jsonify({'error': f'Invalid response from Steam API. Check your API configuration.'}), 500
            
            # Check if response has expected structure
            response_data = games_data.get('response', {})
            if not response_data.get('games'):
                conn.close()
                if 'games' in response_data:  # It exists but is empty
                    return jsonify({'error': 'No games found in your Steam library.'}), 400
                else:
                    return jsonify({'error': 'Unexpected response format from Steam API.'}), 500
                
            steam_library = {game['appid']: game for game in response_data.get('games', [])}
            
        except requests.exceptions.Timeout:
            if conn:
                conn.close()
            return jsonify({'error': 'Steam API request timed out. Please try again later.'}), 408
        except requests.exceptions.ConnectionError:
            if conn:
                conn.close()
            return jsonify({'error': 'Cannot connect to Steam API. Check your internet connection.'}), 503
        
        updated_count = 0
        hours_updated = 0
        errors = []
        
        # Process all games without delays
        for i, game in enumerate(steam_games):
            app_id = game['steam_app_id']
            steam_game = steam_library.get(app_id)
            
            if not steam_game:
                # Game might not be in current Steam library (could be removed or hidden)
                continue
            
            try:
                # Update hours played only - convert minutes to hours
                playtime_minutes = steam_game.get('playtime_forever', 0)
                hours_played = round(playtime_minutes / 60, 1) if playtime_minutes > 0 else 0
                
                # Update the game
                cur.execute('UPDATE games SET hours_played=? WHERE id=?', (hours_played, game['id']))
                hours_updated += 1
                print(f"Updated {game['title']}: {hours_played}h")
                
                updated_count += 1
                
            except Exception as game_error:
                errors.append(f"{game['title']}: {str(game_error)}")
                print(f"Error updating {game['title']}: {game_error}")
            
            # IMPORTANT: REMOVED time.sleep(0.5) - this was causing timeout!
            # If you need rate limiting, use a much smaller delay (e.g., 0.01)
            # or better yet, implement batch updates
        
        conn.commit()
        
        # Record today's total hours in daily history
        try:
            record_daily_hours()
        except Exception as e:
            print(f"Note: Could not record daily hours: {e}")
        
        response = {
            'success': True,
            'games_updated': updated_count,
            'hours_updated': hours_updated,
            'message': f'Updated hours for {hours_updated} games from Steam'
        }
        
        if errors:
            response['errors'] = errors[:5]  # Limit to 5 errors to avoid huge response
            response['error_count'] = len(errors)
        
        return jsonify(response)
        
    except Exception as e:
        print(f"Unexpected error in update_all_games_from_steam: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()
            
@app.route('/api/random-game')
def api_random_game():
    status_filter = request.args.get('status', 'all')
    platform_filter = request.args.get('platform', 'all')
    max_hours = request.args.get('max_hours', 0, type=int)
    
    conn = get_db()
    cur = conn.cursor()
    
    query = '''
        SELECT g.*, 
               COUNT(CASE WHEN a.unlocked=1 THEN 1 END) as unlocked_achievements,
               COUNT(a.id) as total_achievements
        FROM games g
        LEFT JOIN achievements a ON g.id = a.game_id
        WHERE 1=1
    '''
    params = []
    
    if status_filter != 'all':
        query += ' AND g.status = ?'
        params.append(status_filter)
    
    if platform_filter != 'all':
        query += ' AND g.platform = ?'
        params.append(platform_filter)
    
    if max_hours > 0:
        query += ' AND (g.hours_played <= ? OR g.hours_played IS NULL)'
        params.append(max_hours)
    
    query += ' GROUP BY g.id'
    
    cur.execute(query, params)
    games = [dict(r) for r in cur.fetchall()]
    conn.close()
    
    if not games:
        return jsonify({'error': 'No games match your filters'}), 404
    
    import random
    random_game = random.choice(games)
    
    # Add tags
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT tag FROM tags WHERE game_id=?', (random_game['id'],))
    random_game['tags'] = [r['tag'] for r in cur.fetchall()]
    conn.close()
    
    return jsonify(random_game)

@app.route('/api/batch/update-status', methods=['POST'])
def api_batch_update_status():
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.json
    game_ids = data.get('game_ids', [])
    new_status = data.get('status')
    
    if not game_ids or not new_status:
        return jsonify({'error': 'Missing game_ids or status'}), 400
    
    conn = get_db()
    cur = conn.cursor()
    
    placeholders = ','.join(['?'] * len(game_ids))
    cur.execute(f'UPDATE games SET status=? WHERE id IN ({placeholders})', 
                [new_status] + game_ids)
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'updated': len(game_ids)})

@app.route('/api/batch/delete', methods=['POST'])
def api_batch_delete():
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.json
    game_ids = data.get('game_ids', [])
    
    if not game_ids:
        return jsonify({'error': 'Missing game_ids'}), 400
    
    conn = get_db()
    cur = conn.cursor()
    
    placeholders = ','.join(['?'] * len(game_ids))
    cur.execute(f'DELETE FROM games WHERE id IN ({placeholders})', game_ids)
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'deleted': len(game_ids)})

@app.route('/api/stats')
def api_stats():
    conn = get_db()
    cur = conn.cursor()
    
    # Total games
    cur.execute('SELECT COUNT(*) as total FROM games')
    total = cur.fetchone()['total']
    
    # Completed games
    cur.execute("SELECT COUNT(*) as completed FROM games WHERE status='Completed'")
    completed = cur.fetchone()['completed']
    
    # Total hours played
    cur.execute('SELECT SUM(hours_played) as total_hours FROM games')
    total_hours = cur.fetchone()['total_hours'] or 0
    
    # Achievement stats
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
    
    # Get status breakdown
    cur.execute('''
        SELECT status, COUNT(*) as count FROM games 
        WHERE status IS NOT NULL AND status != ''
        GROUP BY status
        ORDER BY count DESC
    ''')
    status_breakdown = {row['status']: row['count'] for row in cur.fetchall()}
    
    # Get platform breakdown
    cur.execute('''
        SELECT platform, COUNT(*) as count FROM games 
        WHERE platform IS NOT NULL AND platform != ''
        GROUP BY platform
        ORDER BY count DESC
    ''')
    platform_breakdown = {row['platform']: row['count'] for row in cur.fetchall()}
    
    # Get recent completions with hours and rating
    cur.execute('''
        SELECT id, title, cover_url, completion_date, hours_played, rating 
        FROM games 
        WHERE status='Completed' AND completion_date IS NOT NULL
        ORDER BY completion_date DESC
        LIMIT 5
    ''')
    recent_completions = [dict(r) for r in cur.fetchall()]
    
    # Additional stats you might want to add:
    
    # Average rating
    cur.execute('SELECT AVG(rating) as avg_rating FROM games WHERE rating IS NOT NULL')
    avg_rating = cur.fetchone()['avg_rating']
    
    # Most played game
    cur.execute('''
        SELECT title, hours_played 
        FROM games 
        WHERE hours_played IS NOT NULL AND hours_played > 0
        ORDER BY hours_played DESC 
        LIMIT 1
    ''')
    most_played = cur.fetchone()
    
    # Games by rating distribution
    cur.execute('''
        SELECT 
            SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) as five_star,
            SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END) as four_star,
            SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) as three_star,
            SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END) as two_star,
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as one_star,
            SUM(CASE WHEN rating IS NULL THEN 1 ELSE 0 END) as unrated
        FROM games
    ''')
    rating_distribution = dict(cur.fetchone())
    
    # Completion rate
    completion_rate = round((completed / total * 100), 1) if total > 0 else 0
    
    # Average hours per game
    avg_hours_per_game = round(total_hours / total, 1) if total > 0 else 0
    
    conn.close()
    
    return jsonify({
        'total_games': total,
        'completed_games': completed,
        'completion_rate': completion_rate,
        'total_hours': round(total_hours, 1),
        'avg_hours_per_game': avg_hours_per_game,
        'achievements_unlocked': achievements_unlocked,
        'achievements_total': achievements_total,
        'achievement_progress': achievement_progress,
        'status_breakdown': status_breakdown,
        'platform_breakdown': platform_breakdown,
        'recent_completions': recent_completions,
        'avg_rating': round(avg_rating, 1) if avg_rating else 0,
        'most_played': dict(most_played) if most_played else None,
        'rating_distribution': rating_distribution
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

schedule_daily_tracking()

# Run locally for debugging
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

