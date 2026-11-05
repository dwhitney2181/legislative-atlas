#!/usr/bin/env python3
"""Refresh the copies of the results files that ship with the atlas.

The page always tries the published files in the election-2026 repository first; these
bundled copies are only used when GitHub can't be reached. This merges the daily
legislative feed with the latest automatic update (newest row wins) and copies the
Congress/governor file. Standard library only.
"""
import json, sys, time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
BASE = 'https://raw.githubusercontent.com/dwhitney2181/election-2026/main/'


def get(name, tries=4):
    """Fetch a published file, retrying GitHub's occasional 5xx/timeout hiccups."""
    for n in range(tries):
        try:
            with urlopen(Request(BASE + name, headers={'User-Agent': 'legislative-atlas-refresh'}), timeout=60) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            if n == tries - 1:
                raise
            print(f'{name}: {e}; retrying in {15 * (n + 1)} s')
            time.sleep(15 * (n + 1))


def key(r):
    return (r['state'], r['chamber'], str(r['district']).lower(), r.get('seat') or '')


def main():
    feed = get('atlas-feed.json')
    try:
        live = get('atlas-live.json')
    except Exception as e:
        print('no 30-minute file:', e)
        live = {'races': [], 'meta': {}}
    rows = {key(r): r for r in feed['races']}
    for r in live['races']:
        if str(r.get('updated', '')) >= str(rows.get(key(r), {}).get('updated', '')):
            rows[key(r)] = r
    if len(rows) < 1000:
        sys.exit(f'only {len(rows)} rows; keeping the current bundled copy')
    feed['races'] = sorted(rows.values(), key=lambda r: key(r))
    feed['meta']['rows'] = len(feed['races'])
    feed['meta']['data_as_of_utc'] = max(feed['meta'].get('data_as_of_utc', ''), live['meta'].get('data_as_of_utc', ''))
    (ROOT / 'results_feed.json').write_text(json.dumps(feed, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    fed = get('atlas-federal.json')
    if len(fed.get('house', [])) >= 400:
        (ROOT / 'federal_results.json').write_text(json.dumps(fed, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"results_feed.json: {feed['meta']['rows']} rows; federal_results.json: {len(fed.get('house', []))} House rows")


if __name__ == '__main__':
    main()
