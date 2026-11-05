#!/usr/bin/env python3
"""Build data/rosters/<st>.json: sitting legislators for every jurisdiction Open States covers.

Input:  a checkout of github.com/openstates/people (data/<st>/legislature/*.yml).
Output: data/rosters/<st>.json  {"meta": {...}, "members": [{chamber, district, name, party}]}
        data/rosters/index.json  which jurisdictions have a roster and which don't.

District names are matched to the names used by the bundled district maps (geo/sld) and
the results feed (results_feed.json), so roster, map and results line up.

These are the members serving before the 2026 winners take office. The atlas uses them to
color seats that were not on the 2026 ballot and to show who held each seat; it never uses
them to claim a flip.

Usage:  OPENSTATES_PEOPLE=/path/to/people python3 tools/build_rosters.py [atlas_dir]
"""
import json, os, re, subprocess, sys
from datetime import date
from pathlib import Path
import yaml

PEOPLE = Path(os.environ.get('OPENSTATES_PEOPLE', 'people'))
ATLAS = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
OUT = ATLAS / 'data' / 'rosters'
JUR = json.loads((ATLAS / 'jurisdictions.json').read_text())
FEED = json.loads((ATLAS / 'results_feed.json').read_text())
ORD = {'first': '1st', 'second': '2nd', 'third': '3rd', 'fourth': '4th', 'fifth': '5th', 'sixth': '6th',
       'seventh': '7th', 'eighth': '8th', 'ninth': '9th', 'tenth': '10th'}
DROP = {'and', 'district', 'senate', 'state', 'house', 'legislative', 'subdistrict', 'of'}


def tokens(s):
    out = []
    for t in re.split(r'[\s,\-_./]+', str(s).lower().replace('&', ' and ')):
        if not t or t in DROP:
            continue
        t = ORD.get(t, t)
        if re.fullmatch(r'0+\d+[a-z]?', t):
            t = t.lstrip('0')
        out.append(t)
    return out


def okey(s):
    return ''.join(tokens(s))


def skey(s):
    return ' '.join(sorted(tokens(s)))


def topo_districts(st, layer):
    p = ATLAS / 'geo' / 'sld' / f'{st.lower()}.topo.json'
    if not p.exists():
        return set()
    t = json.loads(p.read_text())
    ob = t.get('objects', {}).get(layer)
    return {g.get('properties', {}).get('district') for g in (ob or {}).get('geometries', []) if g.get('properties')} - {None}


def canonical(st, ch):
    names = set(topo_districts(st, 'sldl' if ch == 'lower' else 'sldu'))
    names |= {r['district'] for r in FEED['races'] if r['state'] == st and r['chamber'] == ch}
    return names


def matcher(names):
    by_o, by_s = {}, {}
    for n in names:
        by_o.setdefault(okey(n), n)
        by_s.setdefault(skey(n), []).append(n)

    def match(d):
        if d in names:
            return d
        if okey(d) in by_o:
            return by_o[okey(d)]
        c = by_s.get(skey(d), [])
        if len(c) == 1:
            return c[0]
        m = re.fullmatch(r'0*(\d+)[A-Za-z]?', okey(d))
        if m and m.group(1) in by_o:
            return by_o[m.group(1)]
        return None
    return match


def current(role):
    end = role.get('end_date')
    if not end:
        return True
    return str(end) >= date.today().isoformat()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        when = subprocess.run(['git', '-C', str(PEOPLE), 'log', '-1', '--format=%cs'], capture_output=True, text=True).stdout.strip()
    except Exception:
        when = ''
    index = {}
    for j in JUR:
        st, chambers = j['code'], {c['id'] for c in j['chambers']}
        folder = PEOPLE / 'data' / st.lower() / 'legislature'
        if not folder.is_dir():
            index[st] = {'roster': False, 'reason': 'Open States has no legislator data for this jurisdiction'}
            continue
        members, unmatched = [], 0
        matchers = {ch: matcher(canonical(st, ch)) for ch in chambers}
        for f in sorted(folder.glob('*.yml')):
            p = yaml.safe_load(f.read_text(encoding='utf-8'))
            party = ((p.get('party') or [{}])[0] or {}).get('name', '')
            for role in p.get('roles') or []:
                if not current(role):
                    continue
                typ = role.get('type')
                ch = {'lower': 'lower', 'upper': 'upper', 'legislature': 'upper'}.get(typ)
                if ch not in chambers:
                    continue
                raw = str(role.get('district') or '').strip()
                if not raw:
                    continue
                d = matchers[ch](raw)
                if d is None:
                    unmatched += 1
                    m = re.fullmatch(r'([A-Za-z .]+?)\s+0*(\d+)', raw)  # NH floterials: 'Merrimack 26' -> 'Merrimack-26'
                    d = f'{m.group(1)}-{m.group(2)}' if m else raw
                members.append({'chamber': ch, 'district': d, 'name': p.get('name', ''), 'party': party})
        if not members:
            index[st] = {'roster': False, 'reason': 'Open States lists no current members'}
            continue
        members.sort(key=lambda m: (m['chamber'], [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', m['district'])], m['name']))
        out = {'meta': {'source': 'Open States (github.com/openstates/people)', 'as_of': when, 'count': len(members),
                        'note': 'Members serving before the 2026 winners take office. Used to color seats not on the 2026 ballot; never used to claim a flip.',
                        'unmatched_districts': unmatched},
               'members': members}
        (OUT / f'{st.lower()}.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        index[st] = {'roster': True, 'count': len(members), 'seats': j['seats'], 'unmatched_districts': unmatched}
    (OUT / 'index.json').write_text(json.dumps({'as_of': when, 'jurisdictions': index}, indent=1), encoding='utf-8')
    have = [s for s, v in index.items() if v['roster']]
    print(f'{len(have)} rosters written; none for: {", ".join(s for s, v in index.items() if not v["roster"])}')
    for s, v in index.items():
        if v.get('roster') and (v['unmatched_districts'] or abs(v['count'] - v['seats']) > v['seats'] * 0.1):
            print(f"  {s}: {v['count']} members for {v['seats']} seats, {v['unmatched_districts']} district names not matched")


if __name__ == '__main__':
    main()
