"""Capture the small public datasets used in the film. No account data."""
import json
from pathlib import Path
import urllib.request
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent
URLS={
 'weather': 'https://api.open-meteo.com/v1/forecast?latitude=19.076&longitude=72.878&current=temperature_2m,apparent_temperature,weather_code&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code&forecast_days=3&timezone=Asia%2FKolkata',
 'paper': 'https://api.crossref.org/works/10.3847/2041-8213/ab0ec7',
}
if __name__=='__main__':
 for name,url in URLS.items():
  req=urllib.request.Request(url,headers={'User-Agent':'THREADFilm/2.0 (public source capture)'})
  with urllib.request.urlopen(req,timeout=30) as r:data=json.load(r)
  if name=='paper':
   fields=['DOI','title','container-title','publisher','published','URL','type']
   data={'message':{k:data['message'][k] for k in fields if k in data['message']}}
  out={'retrieved_at':datetime.now(timezone.utc).isoformat(),'url':url,'data':data}
  (ROOT/'assets'/f'{name}.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
  print(name, json.dumps(data.get('current') or data.get('message',{}).get('title')))
