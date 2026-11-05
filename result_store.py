"""Small defensive, disk-backed results ledger.

Only preserve source-attributed, explicitly matched seat results. This module
never calls elections, infers a winner from a lead, or assigns party to missing
seats. A JSON file is an *observed source snapshot*, not a certified canvass.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
import json
import os
import re
import tempfile

ROOT=Path(os.environ.get('ATLAS_DATA_DIR',str(Path(__file__).parent/'runtime')))
LOCK=RLock()
KINDS={'official','civicapi','news','multistate','manual','import','seed'}
STATUSES={'leading','reported','called','certified'}
PARTIES={'R','D','F','I','N','O'}


def utcnow(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

def record_key(r):
    return (r['state'].upper(),r['chamber'],str(r['district']).strip().lower(),str(r.get('seat') or '').strip().lower())

def validate_row(r, st=None, curated=False):
    if not isinstance(r,dict):return None
    state=str(r.get('state') or '').upper()
    if not re.fullmatch('[A-Z]{2}',state) or (st and state!=st):return None
    ch=r.get('chamber')
    if ch not in ('upper','lower'):return None
    dist=str(r.get('district') or '').strip()
    if not 0<len(dist)<=100 or not re.fullmatch(r'[a-zA-Z0-9 .\-]+',dist):return None
    if not str(r.get('candidate') or '').strip():return None
    party=str(r.get('party') or '')
    if party not in PARTIES:return None
    status=r.get('status')
    if status not in STATUSES:return None
    kind=r.get('source_kind') or 'import'
    if kind not in KINDS:return None
    source=str(r.get('source') or '').strip()
    if not source:return None
    url=str(r.get('source_url') or '')
    if url and not re.match(r'^https://[^\s/]+(?:/[^\s]*)?$',url):return None
    if curated and (not url or not r.get('updated')):return None
    if curated and status=='certified' and kind!='official':return None
    before=r.get('previous_party')
    if before is not None and before!='' and before not in PARTIES and before!='U':return None
    return {**r,'state':state,'chamber':ch,'district':dist,'candidate':str(r['candidate']).strip(),
            'party':party,'source':source,'source_kind':kind, 'seat':str(r.get('seat') or '').strip()}

def precedence(r):
    # A news/AP call should not be silently demoted by a later partial count.
    status={'certified':4000,'called':3000,'leading':2000,'reported':1000}.get(r.get('status'),0)
    kind={'official':650,'manual':600,'news':510,'civicapi':460,'seed':410,'import':400,'multistate':200}.get(r.get('source_kind'),0)
    # A MultiState "reported winner" is not treated as an official race call.
    return status+kind

def merge_rows(old,new,st):
    """Newer equal-priority entries replace older. Missing rows never zero seats."""
    out={}
    for source in (old,new):
        for raw in source:
            r=validate_row(raw,st)
            if not r:continue
            k=record_key(r)
            prev=out.get(k)
            if prev is None or precedence(r)>precedence(prev):out[k]=r
            elif precedence(r)==precedence(prev):
                # No source update time supplied? Keep the existing observation.
                if str(r.get('updated') or '')>=str(prev.get('updated') or ''):out[k]=r
    return list(out.values())

def _path(st,kind):
    if not re.fullmatch('[A-Z]{2}',st):raise ValueError('invalid state code')
    return ROOT/kind/(st+'.json')

def read_json(st,kind='snapshots'):
    path=_path(st,kind)
    try:
        obj=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(obj,dict) and isinstance(obj.get('races'),list):return obj
    except (OSError,ValueError,UnicodeDecodeError):pass
    return None

def write_json(st,obj,kind='snapshots'):
    path=_path(st,kind)
    try:
        with LOCK:
            path.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.'+st+'.',suffix='.tmp')
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as f:
                    json.dump(obj,f,ensure_ascii=False,separators=(',',':'))
                    f.flush();os.fsync(f.fileno())
                os.replace(tmp,path)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        return True
    except (OSError,PermissionError):
        # Read-only hosting can still serve results; persistence is optional.
        return False

def curated_rows(st):
    obj=read_json(st,'curated')
    if not obj:return []
    return [r for raw in obj['races'] if (r:=validate_row(raw,st,curated=True))]

def snapshot_rows(st):
    obj=read_json(st)
    return obj['races'] if obj else []

def save_observed(st,rows,sources,warnings=None):
    previous=read_json(st)
    merged=merge_rows(previous['races'] if previous else [],rows,st)
    obj={'meta':{'source':' + '.join(sources) if sources else 'Previously observed sources',
                 'timestamp':utcnow(),'matched':len(merged),'partial':True,
                 'warnings':warnings or [],'has_snapshot':True},'races':merged}
    write_json(st,obj)
    return obj

def get_coverage(jurisdictions):
    states=[];total=0;with_data=0
    seed_path=Path(__file__).parent/'utah_nov4_snapshot.json'
    try: bundled=json.loads(seed_path.read_text(encoding='utf-8')).get('races',[])
    except (OSError,ValueError):bundled=[]
    for j in jurisdictions:
        code=j['code'];o=read_json(code);c=read_json(code,'curated')
        rows=[]
        if code=='GU':
            try:
                guam=json.loads((Path(__file__).parent/'guam_nov4_snapshot.json').read_text(encoding='utf-8')).get('races',[])
                rows=merge_rows(rows,guam,code)
            except (OSError,ValueError):pass
        if code=='VI':
            try:
                vi=json.loads((Path(__file__).parent/'usvi_nov3_snapshot.json').read_text(encoding='utf-8')).get('races',[])
                rows=merge_rows(rows,vi,code)
            except (OSError,ValueError):pass
        if code=='UT':rows=merge_rows(rows,[{**r,'state':'UT','previous_party':'U' if r.get('previous_party')=='V' else r.get('previous_party'),'source':r.get('source') or 'Utah 2026 documented snapshot','source_kind':'seed'} for r in bundled if r.get('status')!='holdover'],code)
        if o:rows=merge_rows(rows,o['races'],code)
        if c:rows=merge_rows(rows,c['races'],code)
        n=len(rows);total+=n
        if n:with_data+=1
        states.append({'state':code,'name':j['name'],'seats':j['seats'],'seats_up':j['up2026'],
            'available_records':n,'remote_records':len(o['races']) if o else 0,
            'curated_records':len(c['races']) if c else 0,
            'bundled_2026_results':sum(r.get('status')!='holdover' for r in bundled) if code=='UT' else (len(guam) if code=='GU' and 'guam' in locals() else len(vi) if code=='VI' and 'vi' in locals() else 0),
            'bundled_holdovers':sum(r.get('status')=='holdover' for r in bundled) if code=='UT' else 0,
            'snapshot_as_of':o['meta'].get('timestamp') if o else None,
            'coverage':'partial' if n else 'none'})
    return {'as_of':utcnow(),'jurisdictions':len(jurisdictions),'jurisdictions_with_results':with_data,
            'available_records':total,'bundled_holdovers':sum(r.get('status')=='holdover' for r in bundled),'partial':True,'states':states,
            'note':'Numbers include the dated Utah seed and saved imported/observed records; not certified winners or nationally exhaustive.'}
