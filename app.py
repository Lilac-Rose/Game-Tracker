from flask import Flask, render_template, request, jsonify, session
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
import os
import requests
from datetime import datetime, date, timedelta
import time
import traceback
import threading
import schedule
import pytz
import logging
import threading

# Load environment variables
load_dotenv()

# Paths and constants
DB_PATH = Path(__file__).parent / "data" / "gametracker.db"
DB_PATH.parent.mkdir(exist_ok=True)
COVERS_PATH = Path(__file__).parent / "static" / "covers"
COVERS_PATH.mkdir(exist_ok=True)
SECRET_KEY = os.getenv("SECRET_KEY", "fallback_dev_key")
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")
STEAM_USER_ID = os.getenv("STEAM_USER_ID", "") 
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
STEAM_API_LAST_CALL = 0
STEAM_API_MIN_INTERVAL = 1.2
_record_lock = threading.Lock()
_scheduler_initialized = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('daily_tracker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
    CREATE TABLE IF NOT EXISTS daily_tracker_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        date_recorded TEXT,
        success INTEGER DEFAULT 0,
        error_message TEXT,
        games_updated INTEGER DEFAULT 0,
        hours_recorded REAL DEFAULT 0
    );
    ''')
    conn.commit()
    conn.close()

# Flask app
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 30

init_db()

# Authentication decorator
from functools import wraps
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
        url = f"https://store.steampowered.com/api/storesearch/?term={query}&l=english&cc=US"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            items = data.get('items', [])[:5]
            for item in items:
                app_id = item.get('id')
                item['capsule_image'] = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
            return items
    except:
        pass
    return []

def steam_api_call_with_rate_limit(url):
    """Make Steam API call with rate limiting"""
    global STEAM_API_LAST_CALL
    
    time_since_last_call = time.time() - STEAM_API_LAST_CALL
    if time_since_last_call < STEAM_API_MIN_INTERVAL:
        sleep_time = STEAM_API_MIN_INTERVAL - time_since_last_call
        logger.info(f"Rate limiting: waiting {sleep_time:.2f}s before next Steam API call")
        time.sleep(sleep_time)
    
    try:
        response = requests.get(url, timeout=15)
        STEAM_API_LAST_CALL = time.time()
        return response
    except Exception as e:
        STEAM_API_LAST_CALL = time.time()
        raise e

def get_steam_achievements(app_id, steam_id=None):
    """Get achievements for a Steam game"""
    if not STEAM_API_KEY:
        return []
    
    try:
        schema_url = f"https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={STEAM_API_KEY}&appid={app_id}"
        schema_response = steam_api_call_with_rate_limit(schema_url)
        
        if schema_response.status_code != 200:
            if schema_response.status_code == 429:
                logger.info(f"Rate limited when fetching achievements for app {app_id}")
            return []
            
        try:
            schema_data = schema_response.json()
        except ValueError:
            logger.info(f"Invalid JSON in schema response for app {app_id}")
            return []
            
        schema_achievements = schema_data.get('game', {}).get('availableGameStats', {}).get('achievements', [])
        
        if not schema_achievements:
            return []
        
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
                        logger.info(f"Invalid JSON in user achievements for app {app_id}")
            except Exception as user_err:
                logger.error(f"Error fetching user achievements for app {app_id}: {user_err}")
        
        result = []
        for ach in schema_achievements:
            apiname = ach.get('name', '')
            user_data = user_achievements.get(apiname, {})
            
            unlock_date = None
            if user_data.get('unlocktime', 0) > 0:
                try:
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
        logger.error(f"Error fetching Steam achievements for app {app_id}: {e}")
        return []
    
def get_steam_game_details(app_id):
    """Get game details including hours played and tags"""
    details = {
        'hours_played': None,
        'tags': []
    }
    
    try:
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
        
        store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
        store_response = requests.get(store_url, timeout=5)
        
        if store_response.status_code == 200:
            store_data = store_response.json()
            app_data = store_data.get(str(app_id), {})
            if app_data.get('success'):
                game_data = app_data.get('data', {})
                genres = game_data.get('genres', [])
                details['tags'] = [g['description'] for g in genres[:5]]
                
                categories = game_data.get('categories', [])
                category_names = [c['description'] for c in categories[:3]]
                details['tags'].extend(category_names)
                
                details['tags'] = list(dict.fromkeys(details['tags']))[:5]
    
    except Exception as e:
        logger.error(f"Error fetching Steam game details: {e}")
    
    return details

def get_total_hours_played():
    """Get total hours played from all games"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT SUM(hours_played) as total_hours FROM games WHERE hours_played IS NOT NULL')
    result = cur.fetchone()
    conn.close()
    return result['total_hours'] or 0

def update_all_steam_hours_sync():
    """Synchronously update all Steam game hours"""
    if not STEAM_API_KEY or not STEAM_USER_ID:
        logger.info("Steam API not configured, skipping auto-update")
        return False
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('SELECT id, steam_app_id FROM games WHERE steam_app_id IS NOT NULL')
        steam_games = cur.fetchall()
        
        if not steam_games:
            conn.close()
            return True
        
        logger.info(f"Auto-updating {len(steam_games)} Steam games...")
        
        games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={STEAM_USER_ID}&include_appinfo=1"
        games_response = steam_api_call_with_rate_limit(games_url)
        
        if games_response.status_code != 200:
            logger.info(f"Steam API returned status {games_response.status_code}")
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
        
        logger.info(f"Auto-updated {updated_count} Steam games")
        return True
    except Exception as e:
        logger.error(f"Error auto-updating Steam hours: {e}")
        return False

def record_daily_hours():
    """Record today's total hours played and sync achievements for recently played games"""
    
    # Acquire lock to prevent simultaneous execution
    if not _record_lock.acquire(blocking=False):
        logger.warning("record_daily_hours already running, skipping this call")
        return False
    
    conn = None
    try:
        # Use EST timezone consistently
        est = pytz.timezone('US/Eastern')
        now_est = datetime.now(est)
        today = now_est.date().isoformat()
        
        logger.info(f"=" * 60)
        logger.info(f"Starting daily Steam hours update for {today}")
        logger.info(f"EST time: {now_est}")
        logger.info(f"=" * 60)
        
        # STEP 1: Import any NEW games from Steam library
        if STEAM_API_KEY and STEAM_USER_ID:
            try:
                logger.info("Checking for new Steam games...")
                games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={STEAM_USER_ID}&include_appinfo=1"
                games_response = steam_api_call_with_rate_limit(games_url)
                
                if games_response.status_code == 200:
                    games_data = games_response.json()
                    steam_games = games_data.get('response', {}).get('games', [])
                    
                    conn = get_db()
                    cur = conn.cursor()
                    
                    cur.execute('SELECT steam_app_id FROM games WHERE steam_app_id IS NOT NULL')
                    existing_app_ids = set(row['steam_app_id'] for row in cur.fetchall())
                    
                    cur.execute('SELECT steam_app_id FROM steam_import_status WHERE error_message = "User excluded this game"')
                    excluded_app_ids = set(row['steam_app_id'] for row in cur.fetchall())
                    
                    new_games_count = 0
                    for game in steam_games:
                        app_id = game.get('appid')
                        if app_id not in existing_app_ids and app_id not in excluded_app_ids:
                            title = game.get('name', f'App {app_id}')
                            hours_played = round(game.get('playtime_forever', 0) / 60, 1) if game.get('playtime_forever', 0) > 0 else None
                            cover_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
                            
                            cur.execute(
                                """INSERT INTO games (title, platform, status, hours_played, steam_app_id, cover_url, rating, completion_date) 
                                   VALUES (?,?,?,?,?,?,?,?)""",
                                (title, 'PC', 'Playing', hours_played, app_id, cover_url, None, None)
                            )
                            
                            cur.execute(
                                'INSERT OR REPLACE INTO steam_import_status (steam_app_id, game_imported, achievements_imported) VALUES (?, 1, 1)',
                                (app_id,)
                            )
                            new_games_count += 1
                    
                    conn.commit()
                    
                    if new_games_count > 0:
                        logger.info(f"✓ Imported {new_games_count} new Steam games")
                    else:
                        logger.info("No new games to import")
                    
                    conn.close()
                    conn = None
            except Exception as e:
                logger.error(f"Error importing new Steam games: {e}")
        
        # STEP 2: Update hours for ALL existing Steam games
        logger.info("Updating hours for existing Steam games...")
        update_all_steam_hours_sync()
        
        # STEP 3: Record the daily snapshot
        total_hours = get_total_hours_played()
        logger.info(f"Total hours played: {total_hours}")
        
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('SELECT COUNT(*) as count FROM games WHERE hours_played IS NOT NULL AND hours_played > 0')
        games_played = cur.fetchone()['count']
        logger.info(f"Games with hours: {games_played}")
        
        # FIX: Use atomic INSERT OR REPLACE instead of check-then-act
        logger.info(f"Recording daily hours for {today} (using atomic INSERT OR REPLACE)")
        cur.execute('''
            INSERT OR REPLACE INTO daily_hours_history (date, total_hours, games_played, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (today, total_hours, games_played))
        
        # Get games with hours to snapshot
        cur.execute('''
            SELECT id, title, hours_played, cover_url, steam_app_id
            FROM games 
            WHERE hours_played IS NOT NULL AND hours_played > 0
            ORDER BY hours_played DESC
        ''')
        games = cur.fetchall()
        logger.info(f"Snapshotting {len(games)} games")
        
        # Get yesterday's snapshot
        yesterday = (now_est.date() - timedelta(days=1)).isoformat()
        cur.execute('SELECT game_id, hours_played FROM daily_game_hours WHERE date = ?', (yesterday,))
        yesterday_hours = {row['game_id']: row['hours_played'] for row in cur.fetchall()}
        
        # Delete today's existing snapshot
        cur.execute('DELETE FROM daily_game_hours WHERE date = ?', (today,))
        
        games_played_today = []
        
        for game in games:
            cur.execute('''
                INSERT INTO daily_game_hours (date, game_id, game_title, hours_played, cover_url)
                VALUES (?, ?, ?, ?, ?)
            ''', (today, game['id'], game['title'], game['hours_played'], game['cover_url']))
            
            prev_hours = yesterday_hours.get(game['id'], 0)
            if game['hours_played'] > prev_hours and game['steam_app_id']:
                games_played_today.append(game)
        
        conn.commit()
        
        # Sync achievements for games played today
        achievements_synced = 0
        if games_played_today and STEAM_API_KEY:
            logger.info(f"Syncing achievements for {len(games_played_today)} games played today...")
            for game in games_played_today:
                try:
                    logger.info(f"  Syncing achievements for {game['title']}...")
                    achievements = get_steam_achievements(game['steam_app_id'])
                    
                    if achievements and len(achievements) > 0:
                        cur.execute('DELETE FROM achievements WHERE game_id = ?', (game['id'],))
                        
                        for ach in achievements:
                            cur.execute(
                                'INSERT INTO achievements (game_id, title, description, date, unlocked, icon_url) VALUES (?,?,?,?,?,?)',
                                (game['id'], ach.get('name'), ach.get('description'), 
                                 ach.get('unlock_date'), ach.get('achieved', 0), ach.get('icon'))
                            )
                        
                        conn.commit()
                        achievements_synced += len(achievements)
                        logger.info(f"  ✓ Synced {len(achievements)} achievements")
                except Exception as e:
                    logger.error(f"  ✗ Failed to sync achievements: {e}")
        
        # Log success
        cur.execute('''
            INSERT INTO daily_tracker_log (date_recorded, success, games_updated, hours_recorded)
            VALUES (?, 1, ?, ?)
        ''', (today, len(games), total_hours))
        
        conn.commit()
        conn.close()
        conn = None
        
        logger.info(f"=" * 60)
        logger.info(f"✓ SUCCESS: Recorded daily hours for {today}")
        logger.info(f"  Total hours: {total_hours}h")
        logger.info(f"  Games tracked: {games_played}")
        if games_played_today:
            logger.info(f"  Games played today: {len(games_played_today)}")
            logger.info(f"  Achievements synced: {achievements_synced}")
        logger.info(f"=" * 60)
        
        return True
        
    except Exception as e:
        error_msg = f"Error recording daily hours: {e}"
        logger.error(f"=" * 60)
        logger.error(f"❌ FAILED: {error_msg}")
        logger.error(traceback.format_exc())
        logger.error(f"=" * 60)
        
        # Log failure
        try:
            if conn is None:
                conn = get_db()
            cur = conn.cursor()
            est = pytz.timezone('US/Eastern')
            today = datetime.now(est).date().isoformat()
            cur.execute('''
                INSERT INTO daily_tracker_log (date_recorded, success, error_message)
                VALUES (?, 0, ?)
            ''', (today, str(e)[:500]))
            conn.commit()
            conn.close()
        except Exception as log_error:
            logger.error(f"Failed to log error: {log_error}")
        
        return False
    finally:
        # Always release the lock
        _record_lock.release()

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
        
        history.sort(key=lambda x: x['date'])
        return history
        
    except Exception as e:
        logger.error(f"Error getting daily hours history: {e}")
        return []

@app.route('/api/excluded-games', methods=['GET'])
@login_required
def get_excluded_games():
    """Get list of excluded Steam games"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT steam_app_id, last_attempt 
            FROM steam_import_status 
            WHERE error_message = "User excluded this game"
            ORDER BY last_attempt DESC
        ''')
        
        excluded = [dict(row) for row in cur.fetchall()]
        conn.close()
        
        return jsonify(excluded)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/excluded-games/<int:app_id>', methods=['DELETE'])
@login_required
def remove_from_excluded(app_id):
    """Remove a game from the excluded list (allow re-import)"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            DELETE FROM steam_import_status 
            WHERE steam_app_id = ? AND error_message = "User excluded this game"
        ''', (app_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Game removed from exclusion list'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def schedule_daily_tracking():
    """Schedule daily hours tracking at 12:30 PM EST (17:30 UTC)"""
    global _scheduler_initialized
    
    if _scheduler_initialized:
        logger.warning("Scheduler already initialized, skipping")
        return
    
    _scheduler_initialized = True
    
    try:
        def job():
            est = pytz.timezone('US/Eastern')
            now = datetime.now(est)
            logger.info(f"\n{'='*60}")
            logger.info(f"SCHEDULED JOB TRIGGERED")
            logger.info(f"Current EST time: {now}")
            logger.info(f"{'='*60}\n")
            record_daily_hours()
        
        # 17:30 UTC = 12:30 PM EST (safer than midnight)
        schedule.every().day.at("17:30").do(job)
        
        def run_scheduler():
            logger.info("Scheduler thread started")
            while True:
                try:
                    schedule.run_pending()
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"Scheduler error: {e}")
                    time.sleep(60)
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        
        next_run = schedule.next_run()
        logger.info("=" * 60)
        logger.info("Daily hours tracking scheduler STARTED")
        logger.info(f"Schedule: 12:30 PM EST daily (17:30 UTC)")
        logger.info(f"Next run: {next_run}")
        logger.info("=" * 60)
        
        # Check if we need to record today's data (with delay to avoid conflicts)
        def delayed_check():
            time.sleep(5)  # Wait 5 seconds for app to fully start
            try:
                est = pytz.timezone('US/Eastern')
                today = datetime.now(est).date().isoformat()
                
                conn = get_db()
                cur = conn.cursor()
                cur.execute('SELECT id FROM daily_hours_history WHERE date = ?', (today,))
                if not cur.fetchone():
                    logger.info(f"No record for {today} found, running initial recording...")
                    record_daily_hours()
                else:
                    logger.info(f"Record for {today} already exists")
                conn.close()
            except Exception as e:
                logger.error(f"Error in delayed check: {e}")
        
        threading.Thread(target=delayed_check, daemon=True).start()
        
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        logger.error(traceback.format_exc())

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

@app.route('/api/games/<int:game_id>/favorite', methods=['PUT'])
@login_required
def toggle_favorite(game_id):
    conn = get_db()
    cur = conn.cursor()
    
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
@login_required
def import_steam_library():
    if not STEAM_API_KEY or not STEAM_USER_ID:
        return jsonify({'error': 'Steam API not configured. Please check your .env file.'}), 400
    
    import_achievements = False
    
    try:
        if request.is_json:
            data = request.get_json() or {}
            import_achievements = data.get('import_achievements', False)
        else:
            import_achievements = request.form.get('import_achievements', 'false').lower() == 'true'
    except Exception as e:
        logger.error(f"Error parsing request data: {e}")
    
    try:
        logger.info("Starting Steam library import...")
        
        games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={STEAM_USER_ID}&include_appinfo=1&include_played_free_games=1"
        games_response = steam_api_call_with_rate_limit(games_url)
        
        if games_response.status_code != 200:
            error_msg = f"Steam API returned status {games_response.status_code}"
            if games_response.status_code == 429:
                error_msg = "Steam API rate limit exceeded. Please wait a few minutes and try again."
            elif games_response.status_code == 401:
                error_msg = "Steam API key invalid or expired. Please check your API key."
            elif games_response.status_code == 403:
                error_msg = "Access forbidden. Your Steam profile may be private."
            return jsonify({'error': error_msg}), 400
        
        try:
            games_data = games_response.json()
        except ValueError as e:
            return jsonify({'error': f'Invalid response from Steam API: {str(e)}'}), 400
        
        steam_games = games_data.get('response', {}).get('games', [])
        
        if not steam_games:
            return jsonify({'error': 'No games found in your Steam library.'}), 400
        
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('SELECT steam_app_id, game_imported, achievements_imported FROM steam_import_status')
        import_status = {row['steam_app_id']: row for row in cur.fetchall()}
        
        cur.execute('SELECT steam_app_id FROM games WHERE steam_app_id IS NOT NULL')
        existing_app_ids = set(row['steam_app_id'] for row in cur.fetchall())

        # Get excluded games (ones marked as excluded in import status)
        cur.execute('SELECT steam_app_id FROM steam_import_status WHERE error_message = "User excluded this game"')
        excluded_app_ids = set(row['steam_app_id'] for row in cur.fetchall())
        
        imported_count = 0
        skipped_count = 0
        resumed_count = 0
        achievements_imported = 0
        achievements_failed = 0
        games_with_achievements = 0
        
        steam_games.sort(key=lambda x: x.get('playtime_forever', 0), reverse=True)
        
        MAX_GAMES_TO_IMPORT = 20 if import_achievements else 1000
        if len(steam_games) > MAX_GAMES_TO_IMPORT:
            steam_games = steam_games[:MAX_GAMES_TO_IMPORT]
        
        for i, game in enumerate(steam_games):
            app_id = game.get('appid')
            title = game.get('name', f'App {app_id}')

            if app_id in excluded_app_ids:
                skipped_count += 1
                logger.info(f"Skipping excluded game: {title} (app_id: {app_id})")
                continue
            
            status = import_status.get(app_id)
            
            if status and status['game_imported'] == 1 and (not import_achievements or status['achievements_imported'] == 1):
                skipped_count += 1
                continue
            
            if app_id in existing_app_ids and (not status or status['game_imported'] == 0):
                cur.execute(
                    'INSERT OR REPLACE INTO steam_import_status (steam_app_id, game_imported, achievements_imported) VALUES (?, 1, ?)',
                    (app_id, 1 if not import_achievements else 0)
                )
                skipped_count += 1
                continue
            
            if not status or status['game_imported'] == 0:
                hours_played = round(game.get('playtime_forever', 0) / 60, 1) if game.get('playtime_forever', 0) > 0 else None
                cover_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
                
                cur.execute(
                    """INSERT INTO games (title, platform, status, hours_played, steam_app_id, cover_url, rating, completion_date) 
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (title, 'PC', 'Playing', hours_played, app_id, cover_url, None, None)
                )
                game_id = cur.lastrowid
                
                achievements_status = 1 if not import_achievements else 0
                cur.execute(
                    'INSERT OR REPLACE INTO steam_import_status (steam_app_id, game_imported, achievements_imported) VALUES (?, 1, ?)',
                    (app_id, achievements_status)
                )
                imported_count += 1
            else:
                game_id = cur.execute('SELECT id FROM games WHERE steam_app_id = ?', (app_id,)).fetchone()['id']
                if import_achievements:
                    resumed_count += 1
            
            if import_achievements and app_id and (not status or status['achievements_imported'] == 0):
                try:
                    steam_achievements = get_steam_achievements(app_id)
                    if steam_achievements and len(steam_achievements) > 0:
                        games_with_achievements += 1
                        
                        cur.execute('DELETE FROM achievements WHERE game_id = ?', (game_id,))
                        
                        for ach in steam_achievements:
                            try:
                                cur.execute(
                                    'INSERT INTO achievements (game_id, title, description, date, unlocked, icon_url) VALUES (?,?,?,?,?,?)',
                                    (game_id, ach.get('name'), ach.get('description'), 
                                     ach.get('unlock_date'), ach.get('achieved', 0), ach.get('icon'))
                                )
                            except Exception:
                                continue
                        
                        achievements_imported += len(steam_achievements)
                        cur.execute(
                            'UPDATE steam_import_status SET achievements_imported = 1 WHERE steam_app_id = ?',
                            (app_id,)
                        )
                    else:
                        achievements_failed += 1
                        cur.execute(
                            'UPDATE steam_import_status SET achievements_imported = 1 WHERE steam_app_id = ?',
                            (app_id,)
                        )
                except Exception as e:
                    achievements_failed += 1
                    cur.execute(
                        'UPDATE steam_import_status SET error_message = ? WHERE steam_app_id = ?',
                        (str(e), app_id)
                    )
            elif not import_achievements:
                cur.execute(
                    'UPDATE steam_import_status SET achievements_imported = 1 WHERE steam_app_id = ?',
                    (app_id,)
                )
            
            conn.commit()
            
            if import_achievements and i < len(steam_games) - 1:
                time.sleep(1)
        
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
        return jsonify({'error': 'Steam API request timed out. Please try again later.'}), 408
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Cannot connect to Steam API. Please check your internet connection.'}), 503
    except Exception as e:
        logger.error(f'Unexpected error in import_steam_library: {str(e)}')
        logger.error(traceback.format_exc())
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
        
        cur.execute('DELETE FROM top10_games')
        
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
@login_required
def api_delete_top10(game_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM top10_games WHERE game_id=?', (game_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/daily-game-hours/<date>')
def api_daily_game_hours(date):
    """Get per-game hours breakdown for a specific day"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
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
        
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        prev_date = (date_obj - timedelta(days=1)).strftime('%Y-%m-%d')
        
        cur.execute('''
            SELECT game_id, hours_played
            FROM daily_game_hours
            WHERE date = ?
        ''', (prev_date,))
        
        prev_snapshot = {row['game_id']: row['hours_played'] for row in cur.fetchall()}
        
        result = []
        for game in current_snapshot:
            prev_hours = prev_snapshot.get(game['game_id'], game['hours_played'])
            hours_this_day = round(game['hours_played'] - prev_hours, 1)
            
            if hours_this_day > 0:
                result.append({
                    'game_id': game['game_id'],
                    'game_title': game['game_title'],
                    'total_hours': game['hours_played'],
                    'hours_this_day': hours_this_day,
                    'cover_url': game['cover_url']
                })
        
        result.sort(key=lambda x: x['hours_this_day'], reverse=True)
        
        conn.close()
        return jsonify(result)
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/tracker-logs')
@login_required
def api_tracker_logs():
    """View tracker execution logs"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Check if table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_tracker_log'")
        if not cur.fetchone():
            conn.close()
            return jsonify({'error': 'daily_tracker_log table does not exist yet'}), 404
        
        cur.execute('''
            SELECT * FROM daily_tracker_log 
            ORDER BY timestamp DESC 
            LIMIT 30
        ''')
        logs = [dict(row) for row in cur.fetchall()]
        conn.close()
        return jsonify(logs)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/scheduler-status')
@login_required
def api_scheduler_status():
    """Check scheduler status"""
    try:
        import schedule
        jobs = schedule.jobs
        
        est = pytz.timezone('US/Eastern')
        now = datetime.now(est)
        
        return jsonify({
            'current_time_est': str(now),
            'jobs_scheduled': len(jobs),
            'next_run_utc': str(jobs[0].next_run) if jobs else None,
            'schedule_time': '12:30 PM EST (17:30 UTC) daily'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/record-daily-hours-now', methods=['POST'])
@login_required
def api_record_daily_hours_now():
    """Manually trigger daily hours recording"""
    try:
        success = record_daily_hours()
        if success:
            return jsonify({'success': True, 'message': 'Daily hours recorded successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to record daily hours'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/games')
def api_games():
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
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
        
        for game in rows:
            cur.execute('SELECT tag FROM tags WHERE game_id=?', (game['id'],))
            game['tags'] = [r['tag'] for r in cur.fetchall()]
            
            if game['total_achievements'] > 0:
                game['achievement_progress'] = {
                    'unlocked_achievements': game['unlocked_achievements'],
                    'total_achievements': game['total_achievements'],
                    'completion_percentage': game['completion_percentage']
                }
            else:
                game['achievement_progress'] = None
        
        return jsonify(rows)
    finally:
        if conn:
            conn.close()

@app.route('/api/games/<int:game_id>', methods=['GET', 'PUT', 'DELETE'])
def api_game(game_id):
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
        
        cur.execute(
            """UPDATE games SET title=?, platform=?, status=?, notes=?, rating=?, 
               hours_played=?, steam_app_id=?, cover_url=?, completion_date=? WHERE id=?""",
            (data.get('title'), data.get('platform'), data.get('status'), 
             data.get('notes'), data.get('rating'), data.get('hours_played'),
             data.get('steam_app_id'), data.get('cover_url'), 
             data.get('completion_date'), game_id)
        )
        
        cur.execute('DELETE FROM tags WHERE game_id=?', (game_id,))
        for tag in data.get('tags', []):
            cur.execute('INSERT INTO tags (game_id, tag) VALUES (?,?)', (game_id, tag))
        
        conn.commit()
        conn.close()
        return ('', 204)
    
    else:  # DELETE
        # Mark as excluded if it's a Steam game so it won't be re-imported
        cur.execute('SELECT steam_app_id FROM games WHERE id=?', (game_id,))
        game = cur.fetchone()
        
        if game and game['steam_app_id']:
            # Mark this Steam app ID as excluded
            cur.execute('''
                INSERT OR REPLACE INTO steam_import_status 
                (steam_app_id, game_imported, achievements_imported, error_message) 
                VALUES (?, 0, 0, 'User excluded this game')
            ''', (game['steam_app_id'],))
        
        cur.execute('DELETE FROM games WHERE id=?', (game_id,))
        conn.commit()
        conn.close()
        return ('', 204)

@app.route('/api/games/<int:game_id>/achievements', methods=['GET', 'POST'])
def api_achievements(game_id):
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
@login_required
def api_achievement(game_id, ach_id):
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
@login_required
def update_game_from_steam(game_id):
    """Update a single game's data from Steam"""
    if not STEAM_API_KEY:
        return jsonify({'error': 'Steam API not configured'}), 400
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('SELECT steam_app_id, title, status FROM games WHERE id=?', (game_id,))
        game = cur.fetchone()
        
        if not game:
            return jsonify({'error': 'Game not found'}), 404
        
        app_id = game['steam_app_id']
        if not app_id:
            return jsonify({'error': 'Game has no Steam App ID'}), 400
        
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
        
        if hours_played is not None:
            cur.execute('UPDATE games SET hours_played=? WHERE id=?', (hours_played, game_id))
        
        achievements_updated = 0
        all_achievements_unlocked = False
        completion_date = None
        
        steam_achievements = get_steam_achievements(app_id)
        if steam_achievements and len(steam_achievements) > 0:
            cur.execute('DELETE FROM achievements WHERE game_id=?', (game_id,))
            
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
            
            unlocked_count = sum(1 for ach in steam_achievements if ach.get('achieved', 0))
            if unlocked_count == len(steam_achievements) and len(steam_achievements) > 0:
                all_achievements_unlocked = True
                
                if achievement_dates:
                    try:
                        date_objects = [datetime.strptime(date, '%Y-%m-%d') for date in achievement_dates if date]
                        if date_objects:
                            latest_date = max(date_objects)
                            completion_date = latest_date.strftime('%Y-%m-%d')
                    except Exception:
                        completion_date = datetime.now().strftime('%Y-%m-%d')
                else:
                    completion_date = datetime.now().strftime('%Y-%m-%d')
                
                cur.execute('UPDATE games SET status=?, completion_date=? WHERE id=?', 
                           ('Completed', completion_date, game_id))
        
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
        traceback.print_exc()
        return jsonify({'error': f'Update failed: {str(e)}'}), 500

@app.route('/api/steam/update-all-games', methods=['POST'])
@login_required
def update_all_games_from_steam():
    """Update all Steam games with current data"""
    if not STEAM_API_KEY or not STEAM_USER_ID:
        return jsonify({'error': 'Steam API not configured'}), 400
    
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('SELECT id, title, steam_app_id FROM games WHERE steam_app_id IS NOT NULL')
        steam_games = cur.fetchall()
        
        if not steam_games:
            conn.close()
            return jsonify({'error': 'No Steam games found'}), 400
        
        games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={STEAM_USER_ID}&include_appinfo=1"
        
        try:
            games_response = steam_api_call_with_rate_limit(games_url)
            
            if games_response.status_code != 200:
                conn.close()
                return jsonify({'error': f'Steam API returned status {games_response.status_code}'}), 500
            
            games_data = games_response.json()
            steam_library = {game['appid']: game for game in games_data.get('response', {}).get('games', [])}
            
        except requests.exceptions.Timeout:
            if conn:
                conn.close()
            return jsonify({'error': 'Steam API request timed out'}), 408
        except requests.exceptions.ConnectionError:
            if conn:
                conn.close()
            return jsonify({'error': 'Cannot connect to Steam API'}), 503
        
        updated_count = 0
        hours_updated = 0
        
        for game in steam_games:
            app_id = game['steam_app_id']
            steam_game = steam_library.get(app_id)
            
            if not steam_game:
                continue
            
            try:
                playtime_minutes = steam_game.get('playtime_forever', 0)
                hours_played = round(playtime_minutes / 60, 1) if playtime_minutes > 0 else 0
                
                cur.execute('UPDATE games SET hours_played=? WHERE id=?', (hours_played, game['id']))
                hours_updated += 1
                updated_count += 1
            except Exception:
                continue
        
        conn.commit()
        
        try:
            record_daily_hours()
        except Exception:
            pass
        
        return jsonify({
            'success': True,
            'games_updated': updated_count,
            'hours_updated': hours_updated,
            'message': f'Updated hours for {hours_updated} games from Steam'
        })
        
    except Exception as e:
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
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT tag FROM tags WHERE game_id=?', (random_game['id'],))
    random_game['tags'] = [r['tag'] for r in cur.fetchall()]
    conn.close()
    
    return jsonify(random_game)

@app.route('/api/batch/update-status', methods=['POST'])
@login_required
def api_batch_update_status():
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
@login_required
def api_batch_delete():
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
    conn = None
    try:
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
        
        cur.execute('''
            SELECT status, COUNT(*) as count FROM games 
            WHERE status IS NOT NULL AND status != ''
            GROUP BY status
            ORDER BY count DESC
        ''')
        status_breakdown = {row['status']: row['count'] for row in cur.fetchall()}
        
        cur.execute('''
            SELECT platform, COUNT(*) as count FROM games 
            WHERE platform IS NOT NULL AND platform != ''
            GROUP BY platform
            ORDER BY count DESC
        ''')
        platform_breakdown = {row['platform']: row['count'] for row in cur.fetchall()}
        
        cur.execute('''
            SELECT id, title, cover_url, completion_date, hours_played, rating 
            FROM games 
            WHERE status='Completed' AND completion_date IS NOT NULL
            ORDER BY completion_date DESC
            LIMIT 5
        ''')
        recent_completions = [dict(r) for r in cur.fetchall()]
        
        cur.execute('SELECT AVG(rating) as avg_rating FROM games WHERE rating IS NOT NULL')
        avg_rating = cur.fetchone()['avg_rating']
        
        cur.execute('''
            SELECT title, hours_played 
            FROM games 
            WHERE hours_played IS NOT NULL AND hours_played > 0
            ORDER BY hours_played DESC 
            LIMIT 1
        ''')
        most_played = cur.fetchone()
        
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
        
        completion_rate = round((completed / total * 100), 1) if total > 0 else 0
        avg_hours_per_game = round(total_hours / total, 1) if total > 0 else 0
        
        daily_hours_history = get_daily_hours_history(30)
        
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
            'rating_distribution': rating_distribution,
            'daily_hours_history': daily_hours_history
        })
    finally:
        if conn:
            conn.close()

@app.route('/api/games/<int:game_id>/completionist', methods=['GET', 'POST'])
def api_completionist_achievements(game_id):
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
        # FIX: Don't use f-string for SQL ORDER BY - prevents SQL injection
        sort_by = request.args.get('sort', 'date')
        
        if sort_by == 'difficulty':
            cur.execute('''
                SELECT * FROM completionist_achievements 
                WHERE game_id=? 
                ORDER BY difficulty DESC
            ''', (game_id,))
        else:
            cur.execute('''
                SELECT * FROM completionist_achievements 
                WHERE game_id=? 
                ORDER BY created_at DESC
            ''', (game_id,))
        
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify(rows)

@app.route('/api/games/<int:game_id>/completionist/<int:comp_id>', methods=['PUT', 'DELETE'])
@login_required
def api_completionist_achievement(game_id, comp_id):
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
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        sort_by = request.args.get('sort', 'date')
        filter_status = request.args.get('status', 'all')
        
        # FIX: Don't use f-string for SQL - prevents injection
        if sort_by == 'difficulty':
            order_clause = 'ca.difficulty DESC'
        else:
            order_clause = 'ca.created_at DESC'
        
        if filter_status == 'completed':
            cur.execute(f'''
                SELECT ca.*, g.title as game_title, g.id as game_id 
                FROM completionist_achievements ca
                JOIN games g ON ca.game_id = g.id
                WHERE ca.completed = 1
                ORDER BY {order_clause}
            ''')
        elif filter_status == 'incomplete':
            cur.execute(f'''
                SELECT ca.*, g.title as game_title, g.id as game_id 
                FROM completionist_achievements ca
                JOIN games g ON ca.game_id = g.id
                WHERE ca.completed = 0
                ORDER BY {order_clause}
            ''')
        else:
            cur.execute(f'''
                SELECT ca.*, g.title as game_title, g.id as game_id 
                FROM completionist_achievements ca
                JOIN games g ON ca.game_id = g.id
                ORDER BY {order_clause}
            ''')
        
        rows = [dict(r) for r in cur.fetchall()]
        return jsonify(rows)
    finally:
        if conn:
            conn.close()

schedule_daily_tracking()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)