#!/usr/bin/env python3
"""U.S. State/Territory Legislature Atlas — optional local results + GIS proxy.

Run `python live_server.py` and open http://127.0.0.1:8766.
External feeds are NOT verified in this offline packaging environment. They can fail.
This server never turns raw vote leaders into official results or silently fills missing seats.
"""
from __future__ import annotations
import csv
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from html.parser import HTMLParser
from html import unescape
from pathlib import Path
from threading import RLock
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from result_store import (curated_rows, snapshot_rows, save_observed, get_coverage, merge_rows, read_json, write_json, utcnow)

HERE=Path(__file__).resolve().parent
HOST=os.getenv('HOST','127.0.0.1')
PORT=int(os.getenv('PORT','8766'))
CIVIC='https://civicapi.org/api/v2'
MAPBASE='https://www.electionwrld.com/geo'
DATA_API='https://www.electionwrld.com/api/v1/datasets'
JURISDICTIONS=json.loads((HERE/'jurisdictions.json').read_text())
GUAM_SEED=json.loads((HERE/'guam_nov4_snapshot.json').read_text())
USVI_SEED=json.loads((HERE/'usvi_nov3_snapshot.json').read_text())
UTAH_SEED=json.loads((HERE/'utah_nov4_snapshot.json').read_text())
# Utah's bundled Nov 4 morning snapshot, usable as a server-side fallback. Holdover
# senators are not 2026 results; the one vacant prior seat ('V') becomes unknown ('U').
UTAH_SEED_ROWS=[{**r,'state':'UT','district':str(r.get('district')),
                 'previous_party':'U' if r.get('previous_party')=='V' else r.get('previous_party'),
                 'source':r.get('source') or 'Utah 2026 documented snapshot','source_kind':'seed'}
                for r in UTAH_SEED.get('races',[]) if r.get('status')!='holdover']
# Nationwide results feed (all states with reported winners). The live copy is the
# atlas-feed.json file in the election-2026 repository; a dated copy ships with this
# app so the map still has data if GitHub can't be reached. Set
# ATLAS_RESULTS_FEED_URL to another URL to override, or to "off" to disable.
DEFAULT_FEED_URL='https://raw.githubusercontent.com/dwhitney2181/election-2026/main/atlas-feed.json'
BUNDLED_FEED=HERE/'results_feed.json'
ISLAND_GEO=json.loads((HERE/'island_geography.json').read_text())
STATES={r['code'] for r in JURISDICTIONS}
SLUGS={r['code']:re.sub(r'[^a-z0-9]+','-',r['name'].lower()).strip('-') for r in JURISDICTIONS}
MULTISTATE_BASE='https://www.multistate.us/elections/results/' 
# A source-checked correction, not a certification or automatic winner call.
# Verified against the Salt Lake Tribune's November 4 general-election returns
# and MultiState's 2026 general-election winner listing.
AUDITED_UTAH_H41={
 'state':'UT','chamber':'lower','district':'41','candidate':'John Arthur',
 'party':'D','status':'leading','previous_party':'D','votes':9761,
 'reporting':None,'updated':'2026-11-04',
 'source_kind':'news',
 'source':'Salt Lake Tribune 2026 general election returns (observed Nov 4; unofficial)',
 'source_url':'https://www.sltrib.com/politics/election/',
}

def enforce_audited_utah_41(st,payload):
    """Repair known-wrong cached/observed UT House 41 candidates *only*.

    This does not assert an official call. Other districts remain unchanged.
    Persistent snapshots are corrected too, so restarting does not reintroduce
    an old primary/aggregator record.
    """
    if st!='UT' or not isinstance(payload,dict):return payload
    races=list(payload.get('races') or [])
    idx=[i for i,r in enumerate(races) if str(r.get('chamber'))=='lower' and
         str(r.get('district')).strip().lstrip('0')=='41' and not str(r.get('seat') or '')]
    if not idx:return payload  # No House 41 record to correct; do not add a missing seat.
    good=lambda r: (str(r.get('candidate','')).casefold().strip()=='john arthur' and r.get('party')=='D')
    if len(idx)==1 and good(races[idx[0]]):return payload
    conflicting=[races[i].get('candidate','') for i in idx]
    races=[r for i,r in enumerate(races) if i not in set(idx)]
    races.append(dict(AUDITED_UTAH_H41))
    meta=dict(payload.get('meta') or {})
    warnings=list(meta.get('warnings') or [])
    warnings.append('UT House 41: disputed cached/feed candidate '+str(conflicting)+' was replaced with the November 4 source-checked John Arthur result; not an official certification.')
    meta.update({'warnings':warnings,'corrections_applied':['UT lower 41'],
                 'matched':len(races),'partial':True})
    repaired={**payload,'meta':meta,'races':races}
    write_json('UT',repaired)
    return repaired

# Lower chambers whose geographic districts commonly fill multiple member positions.
# The automated importer does not presume one top-vote-getter won an individual seat.
MULTI_LOWER={'AZ','ID','NJ','ND','SD','WA','NH','VT','MD'}
CACHE={};LOCK=RLock()
LOG_LOCK=RLock()

def activity(message):
    # These messages are deliberately user-facing: keep Terminal activity legible.
    with LOG_LOCK:
        stamp=datetime.now().astimezone().strftime('%H:%M:%S')
        print(f'[{stamp}] {message}', flush=True)


def fetch(url):
    req=Request(url,headers={'User-Agent':'USLegislativeAtlas/0.9 (public noncommercial election viewer)', 'Accept':'application/json,text/csv;q=0.8,*/*;q=0.2'})
    with urlopen(req,timeout=22) as resp:
        raw=resp.read(22_000_000)
        typ=resp.headers.get('Content-Type','')
    if 'csv' in typ or raw[:20].lower().startswith(b'state,chamber'):
        return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    return json.loads(raw.decode('utf-8-sig'))

def fetch_html(url):
    """Retrieve a published HTML page. No private/scraped credentials are used."""
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; LegislativeAtlas/1.1)', 'Accept':'text/html,application/xhtml+xml'})
    with urlopen(req,timeout=25) as resp:
        if resp.status!=200:raise RuntimeError(f'upstream HTTP {resp.status}')
        raw=resp.read(8_000_000)
    return raw.decode('utf-8','replace')

class _Tables(HTMLParser):
    """Extract plain text from semantic HTML tables, ignoring markup/script."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=[];self.level=0;self.rows=None;self.row=None;self.cell=None
        self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):
            self.skip+=1;return
        if self.skip:return
        if tag=='table':
            self.level+=1
            if self.level==1:self.rows=[]
        elif self.level==1 and tag=='tr':self.row=[]
        elif self.level==1 and tag in ('th','td') and self.row is not None:self.cell=[]
        elif self.level==1 and tag=='br' and self.cell is not None:self.cell.append(' ')
    def handle_data(self,data):
        if not self.skip and self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('script','style'):
            self.skip=max(0,self.skip-1);return
        if self.skip:return
        if self.level==1 and tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        elif self.level==1 and tag=='tr' and self.row is not None:
            if self.row:self.rows.append(self.row)
            self.row=None
        elif tag=='table' and self.level:
            self.level-=1
            if self.level==0:
                self.tables.append(self.rows);self.rows=None

def parse_multistate_html(html, st, retrieved=None):
    """Only accept explicit winner cells in MultiState's *legislative* table.

    Unfilled winner cells are skipped, not guessed from candidate order. Only
    an explicit "Flipped X to Y" note provides a previous-party baseline.
    This is publisher-reported, NOT an official election-office vote total.
    """
    if st not in STATES or st in ('DC','GU','VI','AS','PR','MP'):
        return []
    doc=_Tables();doc.feed(html)
    timestamp=retrieved or datetime.now(timezone.utc).isoformat(timespec='seconds')
    link=MULTISTATE_BASE+SLUGS[st]+'-2026'
    out=[];seen=set()
    for table in doc.tables:
        if not table or len(table)<2:continue
        hdr=[x.lower() for x in table[0]]
        if not {'race','winner','others'}.issubset(hdr):continue
        col={h:i for i,h in enumerate(hdr)}
        for values in table[1:]:
            def cell(h):return values[col[h]] if h in col and col[h]<len(values) else ''
            race=cell('race')
            race_match=re.match(r'^\s*(?:State\s+)?(House|Assembly|Senate|House of Delegates)\s+(?:(?:HD|AD|SD|LD)[-\s]*)?(\d+[a-z]?|[a-z])\s*$',race,re.I)
            if not race_match:continue
            chamber='upper' if race_match.group(1).lower()=='senate' else 'lower'
            if st=='NE':chamber='upper'
            if chamber=='lower' and st in MULTI_LOWER:continue
            raw_dist=race_match.group(2)
            number_part=re.match(r'\d+',raw_dist)
            district=(str(int(number_part.group()))+raw_dist[len(number_part.group()):]) if number_part else raw_dist.upper()
            key=(chamber,district)
            if key in seen:continue
            winner=cell('winner')
            if not winner or 'no winner' in winner.lower():continue
            match=re.match(r'^\s*(.+?)\s*\(([^)]+)\)\s*$',winner)
            if not match:continue
            candidate=match.group(1).strip()
            party=clean_party(match.group(2))
            if not candidate or not party:continue
            notes=cell('notes')
            flip=re.search(r'\bflipped\s+([a-z]+)\s+to\s+([a-z]+)\b',notes,re.I)
            prev=None
            if flip:
                oldp,newp=clean_party(flip.group(1)),clean_party(flip.group(2))
                if oldp and newp==party and oldp!=party:prev=oldp
            out.append({'state':st,'chamber':chamber,'district':district,'candidate':candidate,
                'party':party,'status':'reported','previous_party':prev,'votes':None,'reporting':None,
                'updated':timestamp,'source_kind':'multistate','source':'MultiState — publisher-reported winner (not certified)',
                'source_url':link})
            seen.add(key)
    return out

def get_multistate(st):
    if st in ('DC','GU','VI','AS','PR','MP'):return []
    return cached('multistate:'+st,900,lambda:parse_multistate_html(fetch_html(MULTISTATE_BASE+SLUGS[st]+'-2026'),st))

def cached(key,ttl,fn):
    with LOCK:
        previous=CACHE.get(key)
        if previous and time.monotonic()-previous[0]<ttl:return previous[1]
    result=fn()
    with LOCK:CACHE[key]=(time.monotonic(),result)
    return result

def parse_rows(d):
    if isinstance(d,list):return d
    if not isinstance(d,dict):return []
    for k in ('races','rows','records','data','results','items','elections','response'):
        v=d.get(k)
        if isinstance(v,list):return v
        if isinstance(v,dict):
            r=parse_rows(v)
            if r:return r
    if 'candidates' in d:return [d]
    return []

def number(x):
    if isinstance(x,(int,float)):return float(x)
    if isinstance(x,str):
        try:return float(x.replace(',','').replace('%','').strip())
        except ValueError:pass
    return None

def clean_party(p):
    if isinstance(p,dict):p=p.get('name') or p.get('abbreviation') or p.get('id') or ''
    p=str(p or '').strip().lower()
    if p in ('r','rep','republican') or 'republican' in p:return 'R'
    if p in ('d','dem','democratic') or 'democrat' in p:return 'D'
    if p in ('f','forward') or 'forward' in p:return 'F'
    if p in ('i','ind','independent','unaffiliated','no party affiliation') or 'unaffiliated' in p:return 'I'
    if p in ('np','nonpartisan','non-partisan') or 'nonpartisan' in p:return 'N'
    if p=='independent american' or 'independent american' in p:return 'O'
    if p=='n':return 'N'
    if p:return 'O'
    return None

def is_nov_2026_general_race(r):
    """Reject primaries, other years, and undated races from the general feed.

    A date-filtered provider search alone is not evidence that the detail
    endpoint is the November 3 general election; that endpoint may refer to a
    different ballot (such as the June Republican primary). Ambiguous records
    are deliberately omitted rather than shown as election-night winners.
    """
    if not isinstance(r,dict):return False
    fields=('election_name','electionName','election_type','electionType','type',
            'title','name','race_name','raceName','contest','election')
    labels=[]
    for f in fields:
        v=r.get(f)
        if isinstance(v,dict):
            labels.extend(str(v.get(k) or '') for k in ('name','title','type','election_name','date','election_date'))
        elif v is not None: labels.append(str(v))
    meta=' '.join(labels).lower()
    if re.search(r'\b(primary|primaries|runoff|special election)\b',meta):return False
    date_keys=('date','election_date','electionDate','election_day','electionDay',
               'start_date','startDate','poll_date','pollDate')
    dates=[]
    for k in date_keys:
        v=r.get(k)
        if v is not None:dates.extend(re.findall(r'\b\d{4}-\d{2}-\d{2}\b',str(v)))
    dates.extend(re.findall(r'\b\d{4}-\d{2}-\d{2}\b',meta))
    if dates:return all(d=='2026-11-03' for d in dates)
    return bool(re.search(r'\b2026\b',meta) and re.search(r'\bgeneral\b',meta))

def race_location(row,st):
    # Safe matching: a district and a recognizable *state-legislative* office required.
    if not isinstance(row,dict):return None
    s=' '.join(str(row.get(k,'')) for k in ('name','title','race_name','raceName','office','office_name','officeName','district','district_name','districtName','contest','office_type','race'))
    lo=s.lower()
    if re.search(r'\bu\.?s\.? (?:house|senate)|congressional|us house|us senate',lo):return None
    upper=bool(re.search(r'\bstate senate|\bsenate district|\bstate senator|\bsldu|\bsd[- ]\d',lo))
    lower=bool(re.search(r'\bstate house|\bhouse of representatives|\bstate representative|\bhouse district|\bstate assembly|\blegislative district|\bsldl|\bhd[- ]\d|\bhouse of delegates',lo))
    if not (upper or lower):return None
    if upper and lower:return None
    ch='upper' if upper else 'lower'
    m=re.search(r'(?:district|dist\.?|sd|hd|sldu|sldl)[-:# ]*(\d{1,3}[ab]?)\b',lo)
    if not m:return None
    d=m.group(1).lstrip('0') or '0'
    if st=='NE':ch='upper'
    if ch=='lower' and st in MULTI_LOWER:return None
    if st in ('DC','GU','VI','AS','PR','MP'):return None  # no reliable uniform parser
    return ch,d

def candidates(r):
    for k in ('candidates','contestants','options','choices','results'):
        v=r.get(k)
        if isinstance(v,list):return v
        if isinstance(v,dict):
            for kk in ('candidates','results','data','items'):
                if isinstance(v.get(kk),list):return v[kk]
    return []

def normalize(r,st):
    if not is_nov_2026_general_race(r):return None
    pos=race_location(r,st)
    if not pos:return None
    for key in ('seats','seats_to_fill','num_seats','positions','positions_available'):
        if number(r.get(key)) is not None and number(r[key])>1:return None
    c=[]
    for item in candidates(r):
        if not isinstance(item,dict):continue
        n=next((item.get(k) for k in ('name','candidate_name','candidateName','full_name','displayName') if isinstance(item.get(k),str)),None)
        if not n and isinstance(item.get('candidate'),str):n=item['candidate']
        if not n and isinstance(item.get('candidate'),dict):n=item['candidate'].get('name')
        p=next((item.get(k) for k in ('party','party_name','partyName','party_code','partyCode','affiliation') if item.get(k) is not None),None)
        votes=next((number(item[k]) for k in ('votes','vote_count','voteCount','total_votes','totalVotes','raw_votes','count') if number(item.get(k)) is not None),None)
        if n and clean_party(p) and votes is not None:c.append((int(votes),str(n),clean_party(p),item))
    c.sort(key=lambda x:x[0],reverse=True)
    if not c or c[0][0]==0 or (len(c)>1 and c[0][0]==c[1][0]):return None
    win=c[0]
    declared=any(win[3].get(k) is True for k in ('winner','called','is_winner','isWinner'))
    reporting=next((number(r[k]) for k in ('percent_reporting','percentReporting','reporting','precincts_reporting_percent','precinctsReportingPercent') if number(r.get(k)) is not None),None)
    ch,d=pos
    return {'state':st,'chamber':ch,'district':d,'candidate':win[1],'party':win[2], 'status':'called' if declared else 'leading','votes':win[0], 'reporting':reporting,'updated':datetime.now(timezone.utc).isoformat(timespec='seconds'), 'source':'civicAPI aggregate (unofficial); verify with election office'}

def get_civic_rows(st):
    """The provider may be unavailable/partial; never infer a missing race."""
    url=CIVIC+'/race/search?'+urlencode({'country':'US','province':st,'start_date':'2026-11-03','end_date':'2026-11-03','limit':1300})
    obj=fetch(url)
    rows=parse_rows(obj)
    if not rows:raise RuntimeError('No dated races from civicAPI')
    eligible=[r for r in rows if race_location(r,st) and is_nov_2026_general_race(r)]
    def resolve(r):
        x=normalize(r,st)
        if x:return x
        raceid=next((r.get(k) for k in ('raceid','race_id','raceId','id') if r.get(k)),None)
        if not raceid:return None
        try:
            detail=fetch(CIVIC+'/race/'+str(raceid)+'?light=true')
            if not isinstance(detail,dict):return None
            d={**detail}
            for attr in ('title','name','race_name','office','district','election_name','election_date','date','election_type'):
                if not d.get(attr):d[attr]=r.get(attr)
            return normalize(d,st)
        except Exception:return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        found=list(pool.map(resolve,eligible[:160]))
    found=[r for r in found if r]
    # Check parties/status, preserve civicAPI as more authoritative than reported winners.
    for r in found:
        r['source_kind']='civicapi'
        r['source_url']='https://civicapi.org'
    return {(r['chamber'],r['district']):r for r in found}

def _load_feed():
    """Return (rows, label, error). Falls back to the bundled copy on any failure."""
    url=os.getenv('ATLAS_RESULTS_FEED_URL','').strip()
    if url.lower() in ('off','0','none','disabled'):return [],'',None
    url=url or DEFAULT_FEED_URL
    error=None
    try:
        obj=fetch(url)
        rows=[r for r in parse_rows(obj) if isinstance(r,dict)]
        if rows:
            stamp=(obj.get('meta') or {}).get('data_as_of_utc') if isinstance(obj,dict) else None
            return rows,'Nationwide results feed'+(' (data as of '+stamp+')' if stamp else ''),None
        error='feed returned no rows'
    except Exception as e:error=str(e)[:150]
    try:
        obj=json.loads(BUNDLED_FEED.read_text(encoding='utf-8'))
        rows=[r for r in parse_rows(obj) if isinstance(r,dict)]
        stamp=(obj.get('meta') or {}).get('data_as_of_utc')
        return rows,'Bundled results feed copy'+(' (data as of '+stamp+')' if stamp else ''),error
    except (OSError,ValueError):return [],'',error

def feed_rows_by_state():
    """Feed rows grouped by state code; cached for 10 minutes."""
    def work():
        rows,label,error=_load_feed()
        if error:activity(f'FEED: live feed unavailable ({error}); using {label or "no feed"}')
        out={}
        for r in rows:
            st=str(r.get('state','')).upper()
            if st in STATES:out.setdefault(st,[]).append(r)
        return {'rows':out,'label':label,'error':error}
    return cached('feed',600,work)

def all_results():
    """Every known 2026 result in one response, for the page's first paint."""
    def work():
        feed=feed_rows_by_state()
        races=[];states=0
        for code in sorted(STATES):
            rows=list(feed['rows'].get(code,[]))
            if code=='GU':rows=GUAM_SEED['races']+rows
            if code=='VI':rows=USVI_SEED['races']+rows
            if code=='UT':rows=UTAH_SEED_ROWS+rows
            merged=merge_rows(snapshot_rows(code),rows,code)
            if code=='UT':merged=enforce_audited_utah_41('UT',{'races':merged}).get('races',merged)
            if merged:states+=1
            races.extend(merged)
        return {'meta':{'source':feed['label'] or 'Bundled seeds and saved observations',
                        'timestamp':utcnow(),'matched':len(races),'jurisdictions':states,'partial':True,
                        'warnings':[f"Live feed unavailable: {feed['error']}"] if feed['error'] else [],
                        'note':'Unofficial reported winners and leaders. Uncalled races are not listed.'},
                'races':races}
    return cached('all-results',120,work)

def get_results(st):
    """Merge publisher listings, available vote counts and operator-verified news.

    Existing observations survive upstream outages and missing rows. Every
    response marks whether it came from cache or includes new source readings.
    """
    def work():
        rows=[];sources=[];errors=[]
        try:
            feed=feed_rows_by_state()
            fr=feed['rows'].get(st,[])
            if fr:
                rows.extend(fr);sources.append(feed['label']+' ('+str(len(fr))+')')
            if feed['error']:errors.append('Live feed: '+feed['error'])
        except Exception as e:errors.append('Feed: '+str(e)[:150])
        if os.getenv('ATLAS_MULTISTATE_ENABLE','1')!='0':
            try:
                ms=get_multistate(st)
                rows.extend(ms)
                if ms:sources.append('MultiState reported winners ('+str(len(ms))+')')
            except Exception as e:errors.append('MultiState: '+str(e)[:150])
        if st not in ('GU','VI','AS','MP','PR','DC') and os.getenv('ATLAS_CIVIC_ENABLE','1')!='0':
            try:
                civic=get_civic_rows(st)
                rows.extend(civic.values())
                if civic:sources.append('civicAPI vote-leading records ('+str(len(civic))+')')
            except Exception as e:errors.append('civicAPI: '+str(e)[:150])
        verified=curated_rows(st)
        if verified:
            rows.extend(verified);sources.append('Operator-verified news / election office entries ('+str(len(verified))+')')
        if st in ('GU','VI') and not rows:
            if st=='VI':
                rows.extend(USVI_SEED['races'])
                sources.append('VI Elections System Nov 3 unofficial top-15 report')
            # Source-attributed, 15-person at-large slate; no per-seat flip claims.
            if st=='GU':
                rows.extend(GUAM_SEED['races'])
                sources.append('Guam Nov 4 reported 15-candidate slate')
        if st=='UT' and not rows and not read_json(st):
            # Same idea as Guam/VI: never answer "no results" for Utah when a dated snapshot ships with the app.
            rows.extend(UTAH_SEED_ROWS)
            sources.append('Bundled Utah Nov 4 morning snapshot')
        if not rows and not any(j['code']==st and j.get('up2026') for j in JURISDICTIONS):
            # Louisiana, Mississippi, New Jersey, Virginia, Puerto Rico...: nothing on the 2026 ballot.
            return {'meta':{'source':'No regular legislative elections in 2026','timestamp':utcnow(),
                            'matched':0,'partial':False,'warnings':[],
                            'notice':'This legislature had no regularly scheduled general election in November 2026.'},
                    'races':[]}
        if not rows:
            previous=read_json(st)
            if previous:
                previous['meta']={**previous.get('meta',{}),'stale':True,'cached':True,
                    'warnings':errors,'notice':'All sources failed or returned no records; showing last saved observations.'}
                return previous
            raise RuntimeError('No matched 2026 legislative results. '+('; '.join(errors) if errors else 'No source reported this jurisdiction.'))
        return save_observed(st,rows,sources,errors)
    # Distinguish an actual source check from a short-lived cached response.
    with LOCK:
        saved=CACHE.get('result:'+st)
        cache_hit=bool(saved and time.monotonic()-saved[0]<135)
    try:
        result=cached('result:'+st,135,work)
        corrected=enforce_audited_utah_41(st,result)
        if corrected is not result:
            result=corrected
            with LOCK:CACHE['result:'+st]=(time.monotonic(),result)
        meta=result.get('meta',{}) if isinstance(result,dict) else {}
        count=len(result.get('races',[])) if isinstance(result,dict) else 0
        phase='CACHED (up to 135 seconds old)' if cache_hit else 'SOURCES CHECKED'
        freshness=' / STALE SNAPSHOT' if meta.get('stale') else ''
        source=meta.get('source') or 'previously saved snapshot'
        activity(f'RESULTS {st}: {phase}{freshness} | {count} seat records | {source}')
        for warning in meta.get('warnings',[]) or []:
            activity(f'  {st} provider warning: {str(warning)[:180]}')
        return result
    except Exception as exc:
        activity(f'RESULTS {st}: FAILED | {str(exc)[:220]}')
        raise

def get_geo(st):
    if st in ISLAND_GEO and st!='PR':return ISLAND_GEO[st]
    return cached('geo:'+st,86400,lambda:fetch(MAPBASE+'/sld/'+st.lower()+'.topo.json'))

def get_national_geo():
    return cached('geo:national',86400,lambda:fetch(MAPBASE+'/states.topo.json'))

def get_roster(st):
    """Load a member roster, retaining the last successful source payload on disk.

    A saved roster is shown with its original fetch timestamp, NEVER relabeled
    as live or confused with a 2026 election result. This prevents a provider
    outage or a Python restart from turning previously colored states gray.
    """
    cache_dir=HERE/'runtime'/'roster_cache'
    cache_file=cache_dir/(st+'.json')
    try:
        rows=cached('roster:'+st,43200,lambda:fetch(DATA_API+'/state-legislators/'+st.lower()))
        if not isinstance(rows,(dict,list)) or not parse_rows(rows):
            raise ValueError('Roster provider returned no member rows')
        saved=utcnow()
        cache_dir.mkdir(parents=True,exist_ok=True)
        temp=cache_file.with_suffix('.tmp')
        temp.write_text(json.dumps({'saved_at':saved,'data':rows}),encoding='utf-8')
        temp.replace(cache_file)
        return {'data':rows,'_atlas':{'roster_source':'live','saved_at':saved}}
    except Exception as exc:
        if cache_file.exists():
            try:
                old=json.loads(cache_file.read_text(encoding='utf-8'))
                if parse_rows(old.get('data')):
                    activity(f'ROSTER {st}: upstream failed ({str(exc)[:85]}); using saved roster dated {old.get("saved_at", "unknown")}')
                    return {'data':old['data'],'_atlas':{'roster_source':'saved-cache','saved_at':old.get('saved_at'),'warning':'Provider unavailable; dated saved roster'}}
            except Exception:pass
        raise


class H(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):
        # Restore the visible request activity from the original Utah server.
        # Skip health checks so they don't bury the useful election/map lines.
        if self.path.startswith('/api/health'):
            return
        activity('HTTP ' + fmt % args)
    def do_GET(self):
        path=urlparse(self.path)
        query=parse_qs(path.query)
        st=str(query.get('state',[''])[0]).upper()
        try:
            if path.path in ('/','/index.html'):
                return self.send((HERE/'index.html').read_bytes(),'text/html; charset=utf-8')
            if path.path=='/api/geo':
                if st not in STATES:return self.err('Unknown jurisdiction',400)
                return self.json(get_geo(st))
            if path.path=='/api/national-geo':return self.json(get_national_geo())
            if path.path=='/api/roster':
                if st not in STATES:return self.err('Unknown jurisdiction',400)
                return self.json(get_roster(st))
            if path.path=='/api/multistate':
                if st not in STATES:return self.err('Unknown jurisdiction',400)
                rows=get_multistate(st)
                return self.json({'meta':{'source':'MultiState published 2026 winners; not official certifications',
                    'timestamp':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'matched':len(rows),'partial':True},'races':rows})
            if path.path=='/api/results':
                if st not in STATES:return self.err('Unknown jurisdiction',400)
                return self.json(get_results(st))
            if path.path=='/api/results-all':return self.json(all_results())
            if path.path=='/api/health':return self.json({'status':'ok','version':'1.4.0','time':utcnow()})
            if path.path=='/api/coverage':
                try:extra=feed_rows_by_state()['rows']
                except Exception:extra={}
                return self.json(get_coverage(JURISDICTIONS,extra))
            if path.path=='/jurisdictions_2026.csv':return self.send((HERE/'jurisdictions_2026.csv').read_bytes(),'text/csv')
            if path.path=='/README.md':return self.send((HERE/'README.md').read_bytes(),'text/plain')
            if path.path=='/source-policy.html':return self.send((HERE/'source-policy.html').read_bytes(),'text/html; charset=utf-8')
            # Static files the standalone page loads (bundled maps and results feed copy).
            rel=path.path.lstrip('/')
            if re.fullmatch(r'(geo/(sld/[a-z]{2}|states)\.topo\.json|results_feed\.json|[a-z0-9_]+_snapshot\.json|island_geography\.json)',rel):
                f=(HERE/rel).resolve()
                if HERE in f.parents and f.is_file():return self.send(f.read_bytes(),'application/json')
            return self.err('Not found',404)
        except Exception as e:return self.err(str(e),503)
    def json(self,obj):return self.send(json.dumps(obj,separators=(',',':')).encode(),'application/json')
    def err(self,message,code):return self.send(json.dumps({'error':message}).encode(),'application/json',code)
    def send(self,data,mimetype,status=200):
        self.send_response(status)
        self.send_header('Content-Type',mimetype)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers();self.wfile.write(data)

if __name__=='__main__':
    activity(f'United States Legislative Election Atlas — http://{HOST}:{PORT}')
    activity('Showing browser requests, source checks and provider warnings below.')
    activity('When the dashboard is open, its selected state refreshes every 3 minutes.')
    activity('This server does NOT automatically poll all states while the browser is closed.')
    activity('Press Control+C to stop.')
    ThreadingHTTPServer((HOST,PORT),H).serve_forever()
