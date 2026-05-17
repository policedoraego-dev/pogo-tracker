"""
Vercel Serverless Function: GET /api/events
LeekDuck からポケモンGOイベントを取得して返す
"""
from http.server import BaseHTTPRequestHandler
import json
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}

EVENT_COLORS = {
    'community_day':    '#E74C3C',
    'raid_hour':        '#8E44AD',
    'spotlight_hour':   '#F97316',
    'go_battle_league': '#3B82F6',
    'special_research': '#22C55E',
    'season':           '#14B8A6',
    'default':          '#3B82F6',
}

def classify(title):
    t = title.lower()
    if 'community day' in t:                    return 'community_day'
    if 'raid hour' in t or 'raid day' in t:     return 'raid_hour'
    if 'spotlight hour' in t:                   return 'spotlight_hour'
    if 'go battle' in t or 'battle league' in t:return 'go_battle_league'
    if 'special research' in t or 'timed research' in t: return 'special_research'
    if 'season' in t:                           return 'season'
    return 'default'

def fetch_leekduck():
    events = []
    try:
        resp = requests.get('https://leekduck.com/events/', headers=HEADERS, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.event-item')
        now_iso = datetime.now().isoformat()
        seen = set()

        for i, item in enumerate(items[:60]):
            title_el = item.select_one('h2') or item.select_one('h3')
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or len(title) < 4 or title in seen:
                continue
            seen.add(title)

            # 正確な日時は data-countdown 属性から取得
            cd_el  = item.select_one('[data-countdown]')
            cd_date = cd_el.get('data-countdown', '') if cd_el else ''
            cd_to   = cd_el.get('data-countdown-to', 'end') if cd_el else 'end'

            p_el = item.select_one('p')
            date_text = p_el.get_text(strip=True) if p_el else ''

            start = end = None
            if cd_date:
                cd_iso = re.sub(r'\+\d{2}:\d{2}$', '', cd_date)
                if cd_to == 'end':
                    end   = cd_iso
                    start = now_iso
                else:
                    start = cd_iso

            img = item.select_one('img')
            img_url = ''
            if img:
                img_url = img.get('src') or img.get('data-src') or ''
                if img_url.startswith('/'):
                    img_url = 'https://leekduck.com' + img_url

            etype = classify(title)
            events.append({
                'id':        f'leek-{i}',
                'title':     title,
                'date_text': date_text,
                'start':     start,
                'end':       end,
                'type':      etype,
                'color':     EVENT_COLORS.get(etype, EVENT_COLORS['default']),
                'image':     img_url,
                'source':    'leekduck',
                'url':       'https://leekduck.com/events/',
            })
    except Exception as e:
        print(f'[LeekDuck] Error: {e}')
    return events


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        events = fetch_leekduck()
        data = {
            'events':       events,
            'count':        len(events),
            'last_updated': datetime.now().isoformat(),
        }
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')

        self.send_response(200)
        self.send_header('Content-Type',   'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        # Vercel CDN で30分キャッシュ
        self.send_header('Cache-Control',  'public, s-maxage=1800, stale-while-revalidate=3600')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass
