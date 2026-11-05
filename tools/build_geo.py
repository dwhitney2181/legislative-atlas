#!/usr/bin/env python3
"""Build bundled district maps for the Legislative Atlas.

Input:  2022 Census cartographic state legislative district GeoJSON (500k),
        from github.com/loganpowell/census-geojson (GeoJSON/500k/2022/<fips>/
        state-legislative-district-_lower-chamber_.json and _upper-chamber_.json),
        plus states-10m.json from the us-atlas npm package.
Needs:  mapshaper (npm install mapshaper us-atlas).
Usage:  CENSUS_GEOJSON=/path/to/census-geojson NODE_MODULES=/path/to/node_modules \
        python3 tools/build_geo.py [atlas_dir]
Output: <atlas>/geo/sld/<st>.topo.json (layers sldl, sldu) and geo/states.topo.json.

Each district shape gets a `district` property spelled the way the results feed
spells it (e.g. "Belknap-2", "1st Barnstable", "26"), so the page can color it.
"""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path

SRC = Path(os.environ.get('CENSUS_GEOJSON', 'census-geojson')) / 'GeoJSON/500k/2022'
NM = Path(os.environ.get('NODE_MODULES', 'node_modules'))
ATLAS = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
FEED = json.loads((ATLAS / 'results_feed.json').read_text())
MS = str(NM / '.bin' / 'mapshaper')
OUT = ATLAS / 'geo' / 'sld'
OUT.mkdir(parents=True, exist_ok=True)

ORD = {'first': '1st', 'second': '2nd', 'third': '3rd', 'fourth': '4th', 'fifth': '5th', 'sixth': '6th',
       'seventh': '7th', 'eighth': '8th', 'ninth': '9th', 'tenth': '10th'}
DROP = {'and', 'district', 'senate', 'state', 'house', 'legislative', 'subdistrict', 'of'}


def tokens(s):
    s = str(s).lower().replace('&', ' and ')
    toks = re.split(r'[\s,\-_./]+', s)
    out = []
    for t in toks:
        if not t or t in DROP:
            continue
        t = ORD.get(t, t)
        if re.fullmatch(r'0+\d+[a-z]?', t):
            t = t.lstrip('0')
        out.append(t)
    return out


def okey(s):  # order-preserving
    return ''.join(tokens(s))


def skey(s):  # order-free
    return ' '.join(sorted(tokens(s)))


def display(name):
    """Readable fallback when the feed has no row for this district."""
    n = re.sub(r'\s*(State (House|Senate) District|State Legislative Subdistrict|Legislative District|Senate District|State House District|District)\s*', ' ', name).strip()
    m = re.fullmatch(r'([A-Za-z .]+?)\s+0*(\d+)', n)  # 'Hillsborough 24' -> 'Hillsborough-24'
    if m:
        return f'{m.group(1)}-{m.group(2)}'
    return re.sub(r'^0+(?=\d)', '', n)


def feed_districts(st, ch):
    return sorted({r['district'] for r in FEED['races'] if r['state'] == st and r['chamber'] == ch})


def assign(features, st, ch):
    feed = feed_districts(st, ch)
    by_o = {okey(d): d for d in feed}
    by_s = {skey(d): d for d in feed}
    matched = 0
    # order-free matching only where it can't confuse e.g. 'Middlesex and Suffolk' with 'Suffolk and Middlesex'
    import collections
    scount = collections.Counter(skey(f['properties'].get('NAME') or '') for f in features)
    for f in features:
        p = f['properties']
        name = p.get('NAME') or p.get('NAMELSAD') or ''
        code = p.get('SLDLST') or p.get('SLDUST') or ''
        d = None
        for cand in (name, p.get('NAMELSAD', ''), code):
            if not cand:
                continue
            d = by_o.get(okey(cand)) or (by_s.get(skey(cand)) if scount[skey(cand)] <= 1 else None)
            if d:
                break
        if not d:  # '26A' shape inside a district the feed lists as '26'
            m = re.fullmatch(r'0*(\d+)[A-Za-z]', okey(name) or '')
            if m and m.group(1) in by_o:
                d = by_o[m.group(1)]
        if d:
            matched += 1
        f['properties'] = {'district': d or display(name), 'name': p.get('NAMELSAD') or name}
    return matched, len(feed)


def run(st_fips, st):
    layers, report = [], []
    tmp = tempfile.mkdtemp()
    for ch, fn, layer in (('lower', 'lower', 'sldl'), ('upper', 'upper', 'sldu')):
        p = SRC / st_fips / f'state-legislative-district-_{fn}-chamber_.json'
        if not p.exists():
            continue
        g = json.loads(p.read_text())
        g['features'] = [f for f in g['features'] if f.get('geometry')]
        # skip 'ZZZ' (water / not defined) pseudo-districts
        g['features'] = [f for f in g['features'] if not str(f['properties'].get('SLDLST') or f['properties'].get('SLDUST') or '').startswith('ZZ')]
        m, nfeed = assign(g['features'], st, ch)
        report.append(f'{ch}: {len(g["features"])} shapes, {m} matched to {nfeed} feed districts')
        out = Path(tmp) / f'{layer}.json'
        out.write_text(json.dumps(g))
        layers.append(str(out))
    if not layers:
        return None
    dest = OUT / f'{st.lower()}.topo.json'
    pct = '6%' if st == 'AK' else '18%'
    cmd = [MS, '-i', *layers, 'combine-files', '-simplify', pct, 'keep-shapes', 'target=*',
           '-o', 'format=topojson', 'quantization=100000', 'precision=0.00001', str(dest), 'target=*']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-500:])
    return f'{st}: {dest.stat().st_size // 1024} KB | ' + ' | '.join(report)


def main():
    import collections
    fips = {}
    for d in sorted(os.listdir(SRC)):
        p = SRC / d / 'state-legislative-district-_upper-chamber_.json'
        if p.exists():
            fips[d] = json.loads(p.read_text())['features'][0]['properties']['STUSPS']
    total = 0
    for f, st in sorted(fips.items(), key=lambda x: x[1]):
        if st == 'DC':
            continue
        line = run(f, st)
        if line:
            print(line)
            total += (OUT / f'{st.lower()}.topo.json').stat().st_size
    # National outline (unprojected lon/lat; object 'states', ids are FIPS codes)
    us = NM / 'us-atlas' / 'states-10m.json'
    (ATLAS / 'geo' / 'states.topo.json').write_bytes(Path(us).read_bytes())
    print(f'total sld {total // 1024} KB')


if __name__ == '__main__':
    main()
