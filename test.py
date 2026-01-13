#!/usr/bin/env python3
"""
Test what happens when we query Jan 1, 2026
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path("data/gametracker.db")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=" * 60)
print("TESTING JAN 1, 2026 BREAKDOWN")
print("=" * 60)

date_str = "2026-01-01"
prev_date = "2025-12-31"

print(f"\n1. Checking snapshot for {date_str}...")
cur.execute('''
    SELECT COUNT(*) as count
    FROM daily_game_snapshots
    WHERE date = ?
''', (date_str,))
jan1_count = cur.fetchone()['count']
print(f"   Found {jan1_count} games in Jan 1 snapshot")

print(f"\n2. Checking snapshot for {prev_date}...")
cur.execute('''
    SELECT COUNT(*) as count
    FROM daily_game_snapshots
    WHERE date = ?
''', (prev_date,))
dec31_count = cur.fetchone()['count']
print(f"   Found {dec31_count} games in Dec 31 snapshot")

print(f"\n3. Comparing Jan 1 vs Dec 31...")

# Get Jan 1 data
cur.execute('''
    SELECT game_id, game_title, hours_played, cover_url
    FROM daily_game_snapshots
    WHERE date = ?
    ORDER BY hours_played DESC
    LIMIT 10
''', (date_str,))
current_snapshot = [dict(row) for row in cur.fetchall()]

# Get Dec 31 data
cur.execute('''
    SELECT game_id, hours_played
    FROM daily_game_snapshots
    WHERE date = ?
''', (prev_date,))
prev_snapshot = {row['game_id']: row['hours_played'] for row in cur.fetchall()}

print(f"\n   Analyzing top 10 games from Jan 1...")
games_with_changes = []

for game in current_snapshot:
    prev_hours = prev_snapshot.get(game['game_id'], 0)
    hours_added = game['hours_played'] - prev_hours
    
    print(f"\n   {game['game_title']}:")
    print(f"      Dec 31: {prev_hours}h")
    print(f"      Jan 1:  {game['hours_played']}h")
    print(f"      Change: {hours_added:+.1f}h")
    
    if hours_added > 0.1:
        games_with_changes.append({
            'game_title': game['game_title'],
            'hours_added': round(hours_added, 1),
            'total_hours': round(game['hours_played'], 1)
        })

print("\n" + "=" * 60)
print("RESULT")
print("=" * 60)

if games_with_changes:
    print(f"\n✓ Found {len(games_with_changes)} games with >0.1h increase:")
    for game in games_with_changes[:5]:
        print(f"   {game['game_title']}: +{game['hours_added']}h (total: {game['total_hours']}h)")
else:
    print("\n⚠️  NO GAMES had hours increase > 0.1h")
    print("   This explains why you see 'No detailed game data available'!")
    print("\n   Possible reasons:")
    print("   1. The snapshots are identical (no gaming happened Dec 31 → Jan 1)")
    print("   2. All changes are < 0.1h (very small amounts)")
    print("   3. Hours decreased (unlikely)")

# Check total hours
print("\n" + "=" * 60)
print("TOTAL HOURS CHECK")
print("=" * 60)

cur.execute('SELECT total_hours FROM daily_snapshots WHERE date = ?', (prev_date,))
dec31_total = cur.fetchone()['total_hours']

cur.execute('SELECT total_hours FROM daily_snapshots WHERE date = ?', (date_str,))
jan1_total = cur.fetchone()['total_hours']

print(f"\nDec 31 total: {dec31_total}h")
print(f"Jan 1 total:  {jan1_total}h")
print(f"Difference:   {jan1_total - dec31_total:+.1f}h")

if abs(jan1_total - dec31_total) < 0.1:
    print("\n⚠️  DIAGNOSIS: Snapshots are nearly identical!")
    print("   You didn't play any games (or only tiny amounts) between Dec 31 and Jan 1.")
    print("   This is why there's 'no detailed game data' - there's nothing to show!")

conn.close()