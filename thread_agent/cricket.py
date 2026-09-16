"""Read the public Cricbuzz innings table after resolving and verifying its player.

No undocumented authenticated API, guessed player IDs, JS execution, or score synthesis.
Only the provider's returned first page is covered; innings are not distinct matches.
"""
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import urlparse

from .online import clean, fetch_feed, normalized, search_web


class CricketTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside=False;self.cell=None;self.row=[];self.rows=[];self.heading=None;self.headings=[]

    def handle_starttag(self,tag,attrs):
        if tag=='h1':self.heading=''
        if tag=='table':self.inside=True
        if self.inside and tag=='tr':self.row=[]
        if self.inside and tag in ('td','th'):self.cell=''

    def handle_data(self,data):
        if self.heading is not None:self.heading+=data
        if self.cell is not None:self.cell+=data

    def handle_endtag(self,tag):
        if tag=='h1' and self.heading is not None:self.headings.append(clean(self.heading));self.heading=None
        if tag in ('td','th') and self.cell is not None:self.row.append(clean(self.cell));self.cell=None
        if tag=='tr' and self.inside and self.row:self.rows.append(self.row)
        if tag=='table':self.inside=False


def parse_innings(html, name, now, url, skill='batting', match_format='all'):
    table=CricketTable();table.feed(html)
    if not any(normalized(h)==normalized(name) for h in table.headings):
        raise ValueError('The cricket page did not confirm the requested player identity.')
    headers=[];series='';records=[]
    for index,cells in enumerate(table.rows):
        if 'Date' in cells and any(c.startswith('OPPN') for c in cells):headers=cells;continue
        if len(cells)==1:series=cells[0];continue
        if not headers or len(cells)!=len(headers):continue
        row=dict(zip(headers,cells))
        try: day=datetime.strptime(row['Date'],'%d %b %y').date()
        except (KeyError,ValueError):continue
        if day>now.date():continue
        format_value=row.get('Format','')
        if match_format!='all' and format_value.casefold()!=match_format.casefold():continue
        score=row.get('Score',row.get('Figures',row.get('Wickets','')))
        if not score or score.upper() in ('DNB','DNP','TDNB','—','-'):continue
        stats=[]
        if skill=='batting':
            innings=re.fullmatch(r'(\d+)(\*)?\s*\((\d+)\)',score)
            if not innings:continue
            stats=[{'key':'runs','label':'Runs','value':innings[1]}, {'key':'balls','label':'Balls','value':innings[3]},
                   {'key':'strike_rate','label':'Strike rate','value':row.get('SR','—')}]
        else:
            if not any(c.isdigit() for c in score):continue
            stats=[{'key':k.lower(),'label':{'Ov':'Overs','Econ':'Economy','ER':'Economy'}.get(k,k),'value':v}
                   for k,v in row.items() if k not in ('Date','OPPN.','OPPN','Format','Venue','Score','Figures','Wickets')]
        records.append({'id':sha256(f'{url}:{index}:{cells}'.encode()).hexdigest()[:16], 'date':day.isoformat(),
            'title':row.get('OPPN.',row.get('OPPN','Opponent')),'subtitle':' · '.join(filter(None,[format_value,series,row.get('Venue','')])),
            'score':score,'stats':stats,'result':'','url':url,'format':format_value,'record_type':'innings',
            'not_out':bool(skill=='batting' and '*' in score)})
    return sorted(records,key=lambda r:r['date'],reverse=True)


async def cricket_log(entity,args,get,now):
    name=entity['displayName'];skill=args.get('cricket_skill','batting');match_format=args.get('cricket_format','all')
    sources=await search_web({'query':f'site:cricbuzz.com/profiles/ "{name}"','mode':'web','limit':8})
    candidates=[]
    for item in sources['items']:
        url=urlparse(item['url'])
        match=re.fullmatch(r'/profiles/(\d{1,12})/([a-zA-Z0-9-]+)(?:/all-matches/(?:batting|bowling))?/?',url.path)
        if url.hostname not in ('www.cricbuzz.com','m.cricbuzz.com','cricbuzz.com') or not match:continue
        if normalized(name) not in normalized(item['title']):continue
        candidates.append(f'https://www.cricbuzz.com/profiles/{match[1]}/{match[2]}/all-matches/{skill}')
    if not candidates:raise ValueError('No matching public cricket profile was discovered.')
    url=candidates[0]
    html=(await fetch_feed(url,{})).decode('utf-8')
    records=parse_innings(html,name,now,url,skill,match_format)[:args.get('limit',5)]
    metrics=[]
    if records and skill=='batting':
        runs=sum(int(r['stats'][0]['value']) for r in records);balls=sum(int(r['stats'][1]['value']) for r in records)
        outs=sum(not r['not_out'] for r in records)
        metrics=[{'label':'Runs','value':str(runs)},{'label':'Average','value':f'{runs/outs:.1f}' if outs else '—'},
                 {'label':'Strike rate','value':f'{100*runs/balls:.1f}' if balls else '—'}]
    elif records:
        figures=[re.fullmatch(r'(\d+)[-/](\d+)',r['score']) for r in records]
        if all(figures):metrics=[{'label':'Wickets','value':str(sum(int(f[1]) for f in figures))},
                                {'label':'Runs conceded','value':str(sum(int(f[2]) for f in figures))}]
    return records,metrics,f'Cricbuzz public {skill} table · {match_format} formats · source first page only · innings, not distinct matches','Cricbuzz'
