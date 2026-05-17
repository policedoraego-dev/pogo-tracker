#!/usr/bin/env python3
"""Pokemon GO Event Tracker - Backend Server"""
import http.server
import json
import os
import time
import threading
import re
import uuid
from urllib.parse import urlparse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

PORT = int(os.environ.get('PORT', 3001))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')
CACHE_FILE = os.path.join(BASE_DIR, 'events_cache.json')
CUSTOM_FILE = os.path.join(BASE_DIR, 'custom_events.json')
CACHE_DURATION = 30 * 60  # 30 minutes

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

EVENT_COLORS = {
    'community_day': '#E74C3C',
    'raid_hour': '#8E44AD',
    'spotlight_hour': '#F39C12',
    'go_battle_league': '#3B82F6',
    'special_research': '#22C55E',
    'season': '#14B8A6',
    'default': '#3B82F6',
}

def classify_event(title):
    t = title.lower()
    if 'community day' in t: return 'community_day'
    if 'raid hour' in t or 'raid day' in t: return 'raid_hour'
    if 'spotlight hour' in t: return 'spotlight_hour'
    if 'go battle' in t or 'battle league' in t: return 'go_battle_league'
    if 'special research' in t or 'timed research' in t: return 'special_research'
    if 'season' in t: return 'season'
    return 'default'

MONTHS = {
    'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
    'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
    'jan':1,'feb':2,'mar':3,'apr':4,'jun':6,'jul':7,'aug':8,
    'sep':9,'oct':10,'nov':11,'dec':12,
}

def parse_date_str(s):
    if not s:
        return None
    s = s.strip()
    s = re.sub(r'\s+', ' ', s)
    s = s.replace('a.m.', 'AM').replace('p.m.', 'PM').replace('local time', '').strip()

    formats = [
        '%B %d, %Y %I:%M %p',
        '%b %d, %Y %I:%M %p',
        '%B %d, %Y',
        '%b %d, %Y',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M',
        '%Y-%m-%d',
        '%m/%d/%Y',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).isoformat()
        except Exception:
            pass
    return None

def extract_date_range(text):
    """Extract start/end ISO dates from a date range string."""
    if not text:
        return None, None
    text = text.strip()

    # Split on separators
    for sep in [' – ', ' - ', '–', ' to ']:
        if sep in text:
            parts = text.split(sep, 1)
            start = parse_date_str(parts[0].strip())
            end = parse_date_str(parts[1].strip())
            return start, end

    start = parse_date_str(text)
    return start, None

def fetch_leekduck():
    events = []
    try:
        resp = requests.get('https://leekduck.com/events/', headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        items = soup.select('.event-item')
        if not items:
            items = [el for el in soup.find_all(['div','li','article'])
                     if el.get('class') and any('event' in c.lower() for c in el.get('class', []))]

        seen_titles = set()
        now_iso = datetime.now().isoformat()

        for i, item in enumerate(items[:60]):
            # Title — leekduck uses <h2>
            title_el = item.select_one('h2') or item.select_one('h3') or item.select_one('[class*="event-name"]')
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or len(title) < 4 or title in seen_titles:
                continue
            seen_titles.add(title)

            # Date — key insight: leekduck stores exact dates in data-countdown attribute
            cd_el = item.select_one('[data-countdown]')
            cd_date = cd_el.get('data-countdown', '') if cd_el else ''
            cd_to   = cd_el.get('data-countdown-to', 'end') if cd_el else 'end'

            # Human-readable date from <p> tag
            p_el = item.select_one('p')
            date_text = p_el.get_text(strip=True) if p_el else cd_date

            # Map countdown date to start/end
            if cd_date:
                # Normalize ISO (remove timezone offset for local display)
                cd_iso = re.sub(r'\+\d{2}:\d{2}$', '', cd_date)
                if cd_to == 'end':
                    end   = cd_iso
                    start = now_iso  # event is currently active
                else:
                    start = cd_iso
                    end   = None
            else:
                start, end = extract_date_range(date_text)

            # Image
            img = item.select_one('img')
            img_url = ''
            if img:
                img_url = img.get('src') or img.get('data-src') or ''
                if img_url and img_url.startswith('/'):
                    img_url = 'https://leekduck.com' + img_url

            # Link
            a = item.select_one('a[href]')
            href = a['href'] if a else ''
            if href and href.startswith('/'):
                href = 'https://leekduck.com' + href
            if not href:
                href = 'https://leekduck.com/events/'

            etype = classify_event(title)
            events.append({
                'id': f'leek-{i}',
                'title': title,
                'date_text': date_text,
                'start': start,
                'end': end,
                'type': etype,
                'color': EVENT_COLORS.get(etype, EVENT_COLORS['default']),
                'image': img_url,
                'source': 'leekduck',
                'url': href,
            })

        print(f'[LeekDuck] {len(events)} events fetched')
    except Exception as e:
        print(f'[LeekDuck] Error: {e}')
    return events

def fetch_pokemongolive():
    """Try to fetch upcoming events from the official Pokemon GO blog."""
    events = []
    try:
        resp = requests.get('https://pokemongolive.com/post/', headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Each news/event post card
        cards = soup.select('article, .post-card, [class*="post"], [class*="card"]')

        seen = set()
        for i, card in enumerate(cards[:20]):
            title_el = card.select_one('h1, h2, h3, h4, [class*="title"]')
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or title in seen:
                continue
            seen.add(title)

            date_el = card.select_one('time, [class*="date"]')
            date_text = date_el.get('datetime') or date_el.get_text(strip=True) if date_el else ''
            start, end = extract_date_range(date_text)

            a = card.select_one('a[href]')
            href = a['href'] if a else ''
            if href and not href.startswith('http'):
                href = 'https://pokemongolive.com' + href

            img = card.select_one('img')
            img_url = img.get('src', '') if img else ''

            etype = classify_event(title)
            events.append({
                'id': f'pgl-{i}',
                'title': title,
                'date_text': date_text,
                'start': start,
                'end': end,
                'type': etype,
                'color': EVENT_COLORS.get(etype, EVENT_COLORS['default']),
                'image': img_url,
                'source': 'pokemongolive',
                'url': href,
            })

        print(f'[PokemonGOLive] {len(events)} posts fetched')
    except Exception as e:
        print(f'[PokemonGOLive] Error: {e}')
    return events

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# In-memory cache
_cache = load_json(CACHE_FILE) or {'events': [], 'ts': 0, 'updated': ''}
_cache_lock = threading.Lock()

def get_all_events(force=False):
    global _cache
    with _cache_lock:
        now = time.time()
        if force or (now - _cache.get('ts', 0)) > CACHE_DURATION:
            print('[Server] Fetching fresh events...')
            fresh = fetch_leekduck()
            if not fresh:
                fresh = fetch_pokemongolive()
            if fresh:
                _cache = {
                    'events': fresh,
                    'ts': now,
                    'updated': datetime.now().isoformat(),
                }
                save_json(CACHE_FILE, _cache)
                print(f'[Server] Cache updated with {len(fresh)} events')
            else:
                print('[Server] No events fetched; using cached data')
                _cache['ts'] = now  # Don't retry immediately

        custom = load_json(CUSTOM_FILE) or []
        all_events = _cache.get('events', []) + custom
        return {
            'events': all_events,
            'count': len(all_events),
            'last_updated': _cache.get('updated', ''),
        }

def background_refresh():
    while True:
        time.sleep(CACHE_DURATION)
        try:
            get_all_events(force=True)
        except Exception as e:
            print(f'[BG] Refresh error: {e}')

threading.Thread(target=background_refresh, daemon=True).start()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass  # quiet

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/events':
            self.send_json(get_all_events())
        elif path == '/api/refresh':
            self.send_json(get_all_events(force=True))
        else:
            super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/custom':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            custom = load_json(CUSTOM_FILE) or []
            etype = body.get('type', 'default')
            event = {
                'id': f'custom-{uuid.uuid4().hex[:8]}',
                'title': body.get('title', ''),
                'date_text': '',
                'start': body.get('start') or None,
                'end': body.get('end') or None,
                'type': etype,
                'color': EVENT_COLORS.get(etype, EVENT_COLORS['default']),
                'image': '',
                'source': 'custom',
                'url': '',
            }
            custom.append(event)
            save_json(CUSTOM_FILE, custom)
            self.send_json({'ok': True, 'event': event})
        else:
            self.send_json({'error': 'not found'}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith('/api/custom/'):
            eid = path.split('/')[-1]
            custom = load_json(CUSTOM_FILE) or []
            custom = [e for e in custom if e['id'] != eid]
            save_json(CUSTOM_FILE, custom)
            self.send_json({'ok': True})
        else:
            self.send_json({'error': 'not found'}, 404)


if __name__ == '__main__':
    # Initial event fetch
    get_all_events()

    print(f'')
    print(f'  ポケモンGO イベントトラッカー')
    print(f'  http://localhost:{PORT} で起動中')
    print(f'  停止するには Ctrl+C')
    print(f'')

    with http.server.HTTPServer(('', PORT), Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('\n停止しました')
