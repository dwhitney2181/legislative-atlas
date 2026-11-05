#!/usr/bin/env python3
"""Build congressional district maps (geo/cd/<st>.topo.json) for the atlas.

Input: GeoJSON/500k/2022/congressional-district.json (118th Congress, 2022 Census
cartographic file) from github.com/loganpowell/census-geojson. Only states whose
2026 congressional lines are the same as their 2022 lines are built; the states in
REDRAWN use new lines in 2026 that are not in any Census file yet.
Usage: CENSUS_GEOJSON=... NODE_MODULES=... python3 tools/build_cd.py [atlas_dir]
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
SRC = Path(os.environ.get('CENSUS_GEOJSON', 'census-geojson')) / 'GeoJSON/500k/2022/congressional-district.json'
NM = Path(os.environ.get('NODE_MODULES', 'node_modules'))
ATLAS = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
# New congressional lines for 2026 (NCSL mid-decade tracker, July 2026) or since 2022:
REDRAWN = {'AL', 'CA', 'FL', 'GA', 'LA', 'MO', 'NC', 'NY', 'OH', 'TN', 'TX', 'UT'}
FIPS = {'01':'AL','02':'AK','04':'AZ','05':'AR','06':'CA','08':'CO','09':'CT','10':'DE','12':'FL','13':'GA','15':'HI','16':'ID','17':'IL','18':'IN','19':'IA','20':'KS','21':'KY','22':'LA','23':'ME','24':'MD','25':'MA','26':'MI','27':'MN','28':'MS','29':'MO','30':'MT','31':'NE','32':'NV','33':'NH','34':'NJ','35':'NM','36':'NY','37':'NC','38':'ND','39':'OH','40':'OK','41':'OR','42':'PA','44':'RI','45':'SC','46':'SD','47':'TN','48':'TX','49':'UT','50':'VT','51':'VA','53':'WA','54':'WV','55':'WI','56':'WY'}
out = ATLAS / 'geo' / 'cd'; out.mkdir(parents=True, exist_ok=True)
g = json.loads(SRC.read_text())
by = {}
for f in g['features']:
    st = FIPS.get(f['properties']['STATEFP'])
    if not st or st in REDRAWN or not f.get('geometry'):
        continue
    cd = f['properties'].get('CD118FP', '')
    if not cd.isdigit():
        continue
    f['properties'] = {'district': str(int(cd) or 1), 'name': f['properties'].get('NAMELSAD', '')}
    by.setdefault(st, []).append(f)
tmp = Path(tempfile.mkdtemp()); total = 0
for st, fs in sorted(by.items()):
    p = tmp / 'cd.json'; p.write_text(json.dumps({'type': 'FeatureCollection', 'features': fs}))
    dest = out / f'{st.lower()}.topo.json'
    subprocess.run([str(NM / '.bin' / 'mapshaper'), '-i', str(p), '-simplify', '6%' if st == 'AK' else '20%', 'keep-shapes',
                    '-o', 'format=topojson', 'quantization=100000', str(dest)], check=True, capture_output=True)
    total += dest.stat().st_size
print(f'{len(by)} states, {sum(len(v) for v in by.values())} districts, {total//1024} KB')
