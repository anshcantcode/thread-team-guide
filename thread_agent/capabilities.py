"""THREAD-owned, typed tools. Network tools return evidence; drafts stay labelled drafts.

No provider may execute Python, write arbitrary paths, or turn a draft into an external
transaction. Notes are the only persistent write here, in one local SQLite notebook.
"""
from __future__ import annotations

import ast
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
from html import unescape
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from .fixtures import obj, text, DATE
from .protocol import Manifest, ToolSpec


def read_pack(id, title, description, props, required, defaults=None):
    return Manifest(id=id, title=title, description=description, slots=obj(props), defaults=defaults or {},
                    tools=[dict(name=f'{id}.lookup', description=description, purpose='lookup', effect='read',
                                parameters=obj(props, required))]).check()


SHORT = text('Text supplied by the user or composed for their request.', minLength=1, maxLength=200)
NUM = {'type': 'number', 'minimum': -1e15, 'maximum': 1e15}
STRINGS = {'type': 'array', 'items': text('One entry.', maxLength=1200), 'maxItems': 30}
BLOCK = obj({'heading': text('Section label.', maxLength=140),
             'text': text('Content. Plain text, never HTML.', maxLength=7000), 'items': STRINGS}, ['heading'])
DOC_KINDS = ['plan', 'itinerary', 'checklist', 'recipe', 'comparison', 'writing', 'study', 'code', 'brief']
BUILTINS = {m.id: m for m in [
    read_pack('web', 'Online search', 'Search the live web independently of Gemini grounding. Use news mode for recent events/headlines and web mode for general sources. Return publisher links, snippets and timestamps. Snippets are not full articles. Never invent facts missing from the sources.',
              {'query': SHORT, 'mode':text('Search mode.', enum=['web','news']),
               'recency':text('For news mode only.',enum=['day','week','month','any']),
               'limit':{'type':'integer','minimum':1,'maximum':8}}, ['query'], {'mode':'web','recency':'any','limit':5}),
    read_pack('sports', 'Sports', 'Find teams or athletes across sports, with actual recent results and sport-specific statistics where covered: soccer, basketball (including women), baseball, American football, hockey, tennis singles, Formula 1 and cricket batting/bowling innings. Cricket reads the verified player public table, first page only; use cricket_skill and cricket_format. Other sports receive an identity profile and current source discovery with explicit missing coverage, never invented match rows. Football covers current-club competitions including friendlies. Use full names and clarify ambiguous identities. Respect returned coverage, seasons and dates; a dated historical record is not proof of current form.',
              {'query': SHORT, 'entity_type':text('Team or individual football player.',enum=['team','player']),
              'team':text('Optional team name to disambiguate a player.',maxLength=200),
              'sport':text('Optional sport to disambiguate: soccer, basketball, baseball, american-football, hockey, tennis, racing, cricket, golf, mma, or another named sport. Football alone is ambiguous; use soccer or american-football.',maxLength=80),
              'cricket_skill':text('For cricket only: batting innings or bowling spells. Use bowling for a bowler. These are innings, not necessarily distinct Test matches.',enum=['batting','bowling']),
              'cricket_format':text('For cricket only. Filter the available source rows by match format.',enum=['all','ODI','Test','T20']),
               'competition':text('Optional competition to disambiguate a team, e.g. esp.w.1 for Barcelona women.',maxLength=100),
               'entity_id':text('Only an ID returned by a prior sports_choice.',pattern='^[0-9]{1,12}$'),
               'limit':{'type':'integer','minimum':1,'maximum':10}}, ['query','entity_type'], {'limit':5}),
    read_pack('calculate', 'Calculation', 'Evaluate arithmetic locally with a bounded calculator. Use this for numeric answers, percentages, budgets and splits. % is remainder; write percentages as /100. No code execution.',
              {'expression': text('Arithmetic: + - * / // % **, parentheses, sqrt, abs, round, min, max, sum, sin, cos, tan, log, log10, floor, ceil, factorial; pi and e. Trigonometry uses radians.', minLength=1, maxLength=400), 'label': SHORT}, ['expression']),
    read_pack('convert', 'Unit conversion', 'Convert compatible physical units locally. US cup/tablespoon/teaspoon and decimal KB vs binary KiB are explicit. Reject incompatible units.',
              {'value': NUM, 'from_unit': SHORT, 'to_unit': SHORT}, ['value', 'from_unit', 'to_unit']),
    read_pack('currency', 'Currency exchange', 'Fetch dated reference exchange rates from Frankfurter. These are indicative reference rates, not bank quotes or trading prices. No financial transactions.',
              {'amount': NUM, 'from_currency': text('ISO currency code, e.g. INR.', pattern='^[A-Z]{3}$'),
               'to_currency': text('ISO currency code, e.g. USD.', pattern='^[A-Z]{3}$')}, ['amount', 'from_currency', 'to_currency']),
    read_pack('weather', 'Weather', 'Fetch actual weather forecast from Open-Meteo. Location is the user-named city, never inferred from their IP. Up to seven forecast days. An optional country_code helps disambiguate.',
              {'city': SHORT, 'country_code': text('ISO two-letter country code.', pattern='^[A-Z]{2}$'),
               'days': {'type': 'integer', 'minimum': 1, 'maximum': 7}}, ['city'], {'days': 5}),
    read_pack('research', 'Sources', 'Search public reference sources: Wikipedia for encyclopedia topics, Crossref for scholarly paper metadata, Open Library for books. This is source discovery, not an unrestricted web/news search or full-paper analysis. Returned links and dates are evidence.',
              {'query': SHORT, 'collection': text('Choose encyclopedia, papers or books.', enum=['encyclopedia', 'papers', 'books'])}, ['query'], {'collection': 'encyclopedia'}),
    read_pack('dates', 'Date arithmetic', 'Calculate calendar dates locally: add days, days between dates, or count weekdays excluding the starting date and including the end. Weekdays omit weekends only, not public holidays.',
              {'operation': text('Operation.', enum=['add', 'between', 'weekdays']), 'start': DATE, 'end': DATE,
               'days': {'type': 'integer', 'minimum': -36525, 'maximum': 36525}}, ['operation', 'start']),
    read_pack('clock', 'World clock', 'Convert a specific local date and time between IANA timezones, accounting for daylight saving. Use timezone names such as Asia/Kolkata or America/New_York, not ambiguous abbreviations. Ask to clarify ambiguous/nonexistent DST times.',
              {'at': text('ISO local datetime, e.g. 2026-10-08T14:00, optionally with explicit UTC offset.', maxLength=40),
               'from_zone': SHORT, 'to_zone': SHORT}, ['at', 'from_zone', 'to_zone']),
    read_pack('world_clocks', 'Live world clocks', 'Show the CURRENT time in one to four user-requested cities together. Also supplies native home-screen clocks that keep ticking offline. Resolve each city to its IANA timezone; never invent a current timestamp. For example Manchester uses Europe/London, Barcelona uses Europe/Madrid. For a specific date conversion use clock instead.',
              {'locations': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'uniqueItems': True,
                             'items': obj({'label': text('City display name.', minLength=1, maxLength=60),
                                           'zone': text('IANA timezone, e.g. Europe/London.', minLength=1, maxLength=100)}, ['label', 'zone'])}}, ['locations']),
    read_pack('timer', 'Focus timer', 'Create a countdown in this conversation workspace. It signals visually while this page is open; it is not a background alarm or OS notification. Duration is seconds. A new duration restarts the timer.',
              {'seconds': {'type': 'integer', 'minimum': 1, 'maximum': 86400}, 'label': SHORT}, ['seconds'], {'label': 'A little time to focus'}),
    read_pack('document', 'Working document', 'Create or revise a structured AI draft for any subject: plans, itineraries, checklists, recipes, comparisons, writing, study guides, code or briefs. Put useful finished content in blocks (and columns/rows for comparisons). This does not browse, verify claims, execute code, send messages, book hotels or schedule real calendar events. Drafts are downloadable.',
              {'kind': text('Presentation.', enum=DOC_KINDS), 'title': SHORT, 'summary': text('Short overview.', maxLength=600),
               'blocks': {'type': 'array', 'items': BLOCK, 'minItems': 1, 'maxItems': 16},
               'columns': {'type': 'array', 'items': text('Column label.', maxLength=60), 'minItems': 2, 'maxItems': 5},
               'rows': {'type': 'array', 'items': {'type': 'array', 'items': text('Cell.', maxLength=400), 'minItems': 2, 'maxItems': 5}, 'maxItems': 20}}, ['kind', 'title', 'blocks']),
    read_pack('notes', 'Notebook', 'Preview a note for this local notebook. Then ask to save it using commit on the returned option. Saving is persistent on the device running THREAD, not a cloud sync or a message to anyone.',
              {'title': SHORT, 'body': text('Exact note text to save.', minLength=1, maxLength=15000)}, ['title', 'body']),
    read_pack('library', 'Saved notes', 'Search notes the user explicitly saved in THREAD on the device running the task engine. Empty query lists recent notes. Do not search unrelated files or claim knowledge of other apps.',
              {'query': text('Title/body search, or empty for recent notes.', maxLength=200)}, [], {'query': ''}),
]}

# Reuse the existing authorization / stale-result / cancellation controller for saves.
note = BUILTINS['notes']
note.tools.extend(ToolSpec.model_validate(t) for t in [
    {'name': 'notes.save', 'description': 'Save this exact preview to the local THREAD notebook. Persistent write, idempotent by operation ID.',
     'authorization_objects': ['note'],
     'purpose': 'create', 'effect': 'write', 'parameters': obj({**note.slots['properties'], 'option_id': SHORT}, ['title', 'body', 'option_id'])},
    *[{'name': f'notes.{purpose}', 'description': f'{purpose.capitalize()} a saved note by its original operation ID. Cancellation archives only this note.',
       'purpose': purpose, 'effect': 'write' if purpose == 'cancel' else 'read',
       'parameters': obj({'operation_id': SHORT}, ['operation_id'])} for purpose in ['status', 'cancel']],
])
BUILTINS['notes'] = Manifest.model_validate(note.model_dump()).check()


def validate(domain, args):
    json.dumps(args, allow_nan=False)
    errors = list(Draft202012Validator(BUILTINS[domain].tool('lookup').parameters, format_checker=FormatChecker()).iter_errors(args))
    if errors:
        raise ValueError(errors[0].message)


def identifier(domain, args):
    return domain + '-' + hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def answer(domain, args, title, *, source='THREAD local tools', provenance='computed', summary='', **data):
    return {'status': 'completed', 'items': [{'id': identifier(domain, args), 'title': title, 'kind': domain, **data}],
            'source': source, 'provenance': provenance, 'summary': summary or title,
            'retrieved_at': datetime.now(timezone.utc).isoformat()}


def calculate(expression):
    """Interpret a small arithmetic AST; never eval, compile, or execute user code."""
    expression = expression.strip().replace('×', '*').replace('÷', '/').replace('−', '-')
    if len(expression) > 400: raise ValueError('Use an expression under 400 characters.')
    try: tree = ast.parse(expression, mode='eval')
    except (SyntaxError, RecursionError): raise ValueError('That is not a supported arithmetic expression.') from None
    if len(list(ast.walk(tree))) > 120: raise ValueError('This calculation is too complex.')

    def bounded(value):
        value = Decimal(str(value))
        if not value.is_finite() or abs(value) > Decimal('1e100'): raise ValueError('Result exceeds the calculator range.')
        return value

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return bounded(ast.get_source_segment(expression, node))
        if isinstance(node, ast.Name) and node.id in ('pi', 'e'): return Decimal(str(getattr(math, node.id)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            x = visit(node.operand)
            return x if isinstance(node.op, ast.UAdd) else -x
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow):
                if b != int(b) or abs(b) > 100: raise ValueError('Powers require an integer exponent from -100 to 100.')
                return bounded(a ** int(b))
            operations = {ast.Add: lambda: a+b, ast.Sub: lambda: a-b, ast.Mult: lambda: a*b,
                          ast.Div: lambda: a/b, ast.FloorDiv: lambda: Decimal(math.floor(a/b)),
                          ast.Mod: lambda: a-b*math.floor(a/b)}
            if type(node.op) in operations: return bounded(operations[type(node.op)]())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords and 1 <= len(node.args) <= 30:
            name, values = node.func.id, [visit(n) for n in node.args]
            x = values[0]
            if name in ('sum', 'min', 'max'): return bounded({'sum': sum, 'min': min, 'max': max}[name](values))
            if name == 'round' and len(values) in (1, 2):
                digits = values[1] if len(values) == 2 else Decimal(0)
                if digits != int(digits) or abs(digits) > 20: raise ValueError('Rounding precision must be an integer from -20 to 20.')
                return bounded(round(x, int(digits)))
            if len(values) != 1: raise ValueError('Wrong number of function arguments.')
            if name == 'sqrt': return bounded(x.sqrt())
            if name == 'abs': return abs(x)
            if name == 'factorial':
                if x != int(x) or not 0 <= x <= 50: raise ValueError('Factorial accepts integers from 0 to 50.')
                return bounded(math.factorial(int(x)))
            if name in ('sin', 'cos', 'tan', 'log', 'log10', 'floor', 'ceil'):
                return bounded(getattr(math, name)(float(x)))
        raise ValueError('Only numbers and supported arithmetic functions are allowed.')
    try:
        with localcontext() as context:
            context.prec = 28
            result = bounded(visit(tree.body))
            return format(result.normalize(), 'f') if abs(result) < Decimal('1e28') else str(result.normalize())
    except (ArithmeticError, InvalidOperation, OverflowError, RecursionError, TypeError):
        raise ValueError('The expression has an undefined result, division by zero, or exceeds the calculator range.') from None


# dimension, scale to base, offset to base. Decimal constants keep ordinary conversions exact.
UNITS = {}
def units(dimension, entries):
    for name, scale in entries.items(): UNITS[name] = (dimension, Decimal(str(scale)), Decimal(0))
units('length', {'m': 1, 'km': 1000, 'cm': .01, 'mm': .001, 'in': .0254, 'ft': .3048, 'yd': .9144, 'mi': 1609.344, 'nmi': 1852})
units('mass', {'kg': 1, 'g': .001, 'mg': .000001, 'lb': .45359237, 'oz': .028349523125, 'tonne': 1000})
units('volume', {'l': 1, 'ml': .001, 'us_gal': 3.785411784, 'us_cup': .2365882365, 'us_tbsp': .01478676478125, 'us_tsp': .00492892159375})
units('time', {'s': 1, 'min': 60, 'h': 3600, 'day': 86400, 'week': 604800})
units('speed', {'m/s': 1, 'km/h': Decimal(5)/18, 'mph': .44704, 'knot': Decimal(1852)/3600})
units('area', {'m2': 1, 'km2': 1000000, 'ft2': .09290304, 'acre': 4046.8564224, 'hectare': 10000})
units('energy', {'j': 1, 'kj': 1000, 'kcal': 4184, 'wh': 3600, 'kwh': 3600000})
units('power', {'w': 1, 'kw': 1000, 'mw': 1000000})
units('data', {'byte': 1, 'kb': 1000, 'mb': 1000000, 'gb': 1000000000, 'tb': 1000000000000,
               'kib': 1024, 'mib': 1048576, 'gib': 1073741824, 'bit': Decimal(1)/8})
UNITS.update({'c': ('temperature', Decimal(1), Decimal('273.15')),
              'f': ('temperature', Decimal(5)/9, Decimal('459.67')*5/9),
              'k': ('temperature', Decimal(1), Decimal(0))})
ALIASES = {'meter':'m','meters':'m','metre':'m','metres':'m','kilometers':'km','kilometres':'km','kilometer':'km',
           'centimeters':'cm','centimetres':'cm','inches':'in','inch':'in','feet':'ft','foot':'ft','miles':'mi','mile':'mi',
           'yards':'yd','pounds':'lb','pound':'lb','lbs':'lb','ounces':'oz','ounce':'oz','grams':'g','kilograms':'kg',
           'liters':'l','litres':'l','liter':'l','litre':'l','milliliters':'ml','millilitres':'ml',
           'cup':'us_cup','cups':'us_cup','tbsp':'us_tbsp','tsp':'us_tsp','gallon':'us_gal',
           'seconds':'s','second':'s','minutes':'min','minute':'min','hours':'h','hour':'h','days':'day','weeks':'week',
           'celsius':'c','fahrenheit':'f','kelvin':'k','°c':'c','°f':'f','bytes':'byte','bits':'bit',
           'kilobytes':'kb','megabytes':'mb','gigabytes':'gb','watts':'w','kilowatts':'kw','m²':'m2','ft²':'ft2','km²':'km2'}


def convert(value, from_unit, to_unit):
    def key(unit): return ALIASES.get(unit.strip().lower(), unit.strip().lower())
    a, b = key(from_unit), key(to_unit)
    if a not in UNITS or b not in UNITS: raise ValueError('That unit is not supported. Use a precise metric, US customary, time, temperature, data, speed, area, power or energy unit.')
    da, sa, oa = UNITS[a]; db, sb, ob = UNITS[b]
    if da != db: raise ValueError('Those units measure different quantities.')
    base = Decimal(str(value))*sa+oa
    if da == 'temperature' and base < Decimal('-0.000000001'): raise ValueError('Temperature is below absolute zero.')
    result = (base-ob)/sb
    return float(round(result, 10)), a, b, da


def date_math(args):
    start = date.fromisoformat(args['start']); op = args['operation']
    if op == 'add':
        if 'days' not in args: raise ValueError('How many days should I add or subtract?')
        try: end = start + timedelta(days=args['days'])
        except OverflowError: raise ValueError('The resulting date is outside the supported calendar.') from None
        return {'value': end.isoformat(), 'weekday': end.strftime('%A'), 'start': start.isoformat(), 'days': args['days']}
    if 'end' not in args: raise ValueError('What is the end date?')
    end = date.fromisoformat(args['end']); days = (end-start).days
    if abs(days) > 36525: raise ValueError('Use a date span of at most 100 years.')
    count = days
    if op == 'weekdays':
        direction = 1 if days >= 0 else -1
        count = direction*sum((start+timedelta(days=direction*n)).weekday()<5 for n in range(1,abs(days)+1))
    return {'value': count, 'unit': 'weekdays' if op == 'weekdays' else 'days', 'start': start.isoformat(), 'end': end.isoformat(),
            'detail': 'Excludes the start; includes the end. Weekdays exclude weekends, not holidays.'}


def clock_math(args):
    try: source, destination = ZoneInfo(args['from_zone']), ZoneInfo(args['to_zone'])
    except (ZoneInfoNotFoundError, ValueError): raise ValueError('Use an IANA timezone such as Asia/Kolkata or Europe/London.') from None
    try: value = datetime.fromisoformat(args['at'])
    except ValueError: raise ValueError('Use a calendar date and time, such as 2026-10-08T14:00.') from None
    if 'T' not in args['at'] and ' ' not in args['at']: raise ValueError('A date and a time are both required.')
    if value.tzinfo:
        if value.astimezone(source).replace(tzinfo=None) != value.replace(tzinfo=None):
            raise ValueError('The explicit UTC offset disagrees with the source timezone at that time.')
        value = value.astimezone(source)
    else:
        first, second = value.replace(tzinfo=source, fold=0), value.replace(tzinfo=source, fold=1)
        if first.astimezone(timezone.utc).astimezone(source).replace(tzinfo=None) != value:
            raise ValueError('That local time does not exist because clocks move forward. Choose a valid time.')
        if first.utcoffset() != second.utcoffset():
            raise ValueError('That time occurs twice when clocks move back. Supply its UTC offset to choose which one.')
        value = first
    converted = value.astimezone(destination)
    return {'from_time': value.isoformat(), 'to_time': converted.isoformat(), 'from_zone': args['from_zone'],
            'to_zone': args['to_zone'], 'value': converted.strftime('%H:%M'), 'date': converted.date().isoformat()}


class Notebook:
    def __init__(self, path=None):
        directory = Path(os.environ['THREAD_DATA_DIR']) if os.environ.get('THREAD_DATA_DIR') else Path(__file__).resolve().parent.parent/'data'
        self.path = Path(path) if path else directory/'notebook.sqlite3'

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL, status TEXT NOT NULL)')
        try:
            with db: yield db
        finally: db.close()

    def save(self, operation, args):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO notes VALUES (?, ?, ?, ?, ?)',
                       (operation, args['title'], args['body'], datetime.now(timezone.utc).isoformat(), 'completed'))
        return self.status(operation)

    def status(self, operation):
        with self.connect() as db: row = db.execute('SELECT * FROM notes WHERE id = ?', (operation,)).fetchone()
        return {'status': row['status'] if row else 'not_performed', 'operation_id': operation,
                **({'reference': 'NOTE-'+operation, 'title': row['title']} if row else {})}

    def cancel(self, operation):
        with self.connect() as db: db.execute("UPDATE notes SET status = 'cancelled' WHERE id = ?", (operation,))
        return self.status(operation)

    def search(self, query=''):
        # instr treats SQL wildcards as literal input, and parameters never become SQL.
        with self.connect() as db:
            rows = db.execute("SELECT * FROM notes WHERE status = 'completed' AND (instr(lower(title), lower(?)) > 0 OR instr(lower(body), lower(?)) > 0) ORDER BY created DESC LIMIT 30", (query, query)).fetchall()
        return [dict(row) for row in rows]


async def fetch_json(url, params):
    # URLs are constants below; user input is query data, never a network destination.
    async with asyncio.timeout(25), httpx.AsyncClient(timeout=httpx.Timeout(10,connect=5), headers={'User-Agent': 'THREAD/0.3 (local voice research prototype)'}, follow_redirects=False) as client:
        for attempt in range(2):
            try:
                async with client.stream('GET', url, params=params) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        limit = 12_000_000 if re.fullmatch(r'https://site\.api\.espn\.com/apis/site/v2/sports/tennis/(atp|wta)/scoreboard',url) else 2_000_000
                        if len(raw) > limit: raise ValueError('The source response exceeded the size limit.')
                return json.loads(raw)
            except httpx.HTTPStatusError as exc:
                if attempt or exc.response.status_code not in (502,503,504): raise
            except httpx.RequestError:
                if attempt: raise
            await asyncio.sleep(.25)


WEATHER_CODES = {0:'Clear sky',1:'Mostly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Freezing fog',
                 51:'Light drizzle',53:'Drizzle',55:'Heavy drizzle',56:'Freezing drizzle',57:'Freezing drizzle',
                 61:'Light rain',63:'Rain',65:'Heavy rain',66:'Freezing rain',67:'Freezing rain',
                 71:'Light snow',73:'Snow',75:'Heavy snow',77:'Snow grains',80:'Rain showers',81:'Rain showers',
                 82:'Heavy showers',85:'Snow showers',86:'Heavy snow showers',95:'Thunderstorm',96:'Thunderstorm with hail',99:'Thunderstorm with hail'}


async def weather(args, get):
    places = await get('https://geocoding-api.open-meteo.com/v1/search', {'name':args['city'], 'count':5, 'language':'en', **({'countryCode':args['country_code']} if args.get('country_code') else {})})
    matches = places.get('results', [])
    if not matches: return {'status':'completed','items':[],'source':'Open-Meteo / GeoNames','provenance':'live','note':'No matching city was found. Try the city and its country.'}
    place = matches[0]
    # Same-named towns need a country, rather than confidently choosing a random Springfield.
    if not args.get('country_code') and len({p.get('country_code') for p in matches if p['name'].casefold()==place['name'].casefold() and p.get('population',0)>50000}) > 1:
        raise ValueError('There are multiple cities with this name. Which country?')
    data = await get('https://api.open-meteo.com/v1/forecast', {'latitude':place['latitude'],'longitude':place['longitude'],
        'current':'temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m',
        'daily':'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max', 'timezone':'auto','forecast_days':args.get('days',5)})
    current, daily = data['current'], data['daily']
    forecast = [{'date':day,'high':daily['temperature_2m_max'][i],'low':daily['temperature_2m_min'][i],
                 'rain':daily['precipitation_probability_max'][i], 'code':daily['weather_code'][i],
                 'condition':WEATHER_CODES.get(daily['weather_code'][i], 'Weather unavailable')} for i,day in enumerate(daily['time'])]
    return answer('weather', args, place['name'], source='Open-Meteo · GeoNames', provenance='live',
                  country=place.get('country',''), region=place.get('admin1',''), temperature=current['temperature_2m'],
                  humidity=current['relative_humidity_2m'], wind=current['wind_speed_10m'], code=current['weather_code'],
                  condition=WEATHER_CODES.get(current['weather_code'],'Weather unavailable'), forecast=forecast,
                  observed_at=current['time'], timezone=data.get('timezone'), url='https://open-meteo.com/',
                  summary=f"{place['name']}: {current['temperature_2m']}°C, {WEATHER_CODES.get(current['weather_code'],'unknown conditions')}. Forecast shown for {len(forecast)} days.")


def plain(value): return unescape(re.sub('<[^>]*>', '', str(value)))[:600]


async def research(args, get):
    collection = args.get('collection', 'encyclopedia'); query = args['query']; items = []
    if collection == 'encyclopedia':
        data = await get('https://en.wikipedia.org/w/api.php', {'action':'query','list':'search','srsearch':query,'srlimit':5,'format':'json','utf8':1})
        source = 'Wikipedia'
        for row in data.get('query',{}).get('search',[]):
            items.append({'id':f"wiki-{row['pageid']}", 'title':row['title'], 'detail':plain(row.get('snippet','')),
                          'url':'https://en.wikipedia.org/?curid='+str(row['pageid']), 'published':row.get('timestamp',''), 'provider':source, 'kind':'source'})
    elif collection == 'books':
        data = await get('https://openlibrary.org/search.json', {'q':query,'limit':5,'fields':'key,title,author_name,first_publish_year,edition_count'})
        source = 'Open Library'
        for row in data.get('docs',[]):
            items.append({'id':row['key'], 'title':row['title'], 'detail':', '.join(row.get('author_name',[])[:3]),
                          'url':'https://openlibrary.org'+row['key'], 'published':str(row.get('first_publish_year','')), 'provider':source, 'kind':'book'})
    else:
        data = await get('https://api.crossref.org/works', {'query':query,'rows':5,'select':'DOI,title,author,published,publisher,container-title'})
        source = 'Crossref'
        for row in data.get('message',{}).get('items',[]):
            year = row.get('published',{}).get('date-parts',[[]])[0]
            items.append({'id':row['DOI'], 'title':(row.get('title') or [row['DOI']])[0],
                          'detail':', '.join(' '.join([a.get('given',''),a.get('family','')]).strip() for a in row.get('author',[])[:3]),
                          'url':'https://doi.org/'+quote(row['DOI'], safe='/'), 'published':str(year[0]) if year else '',
                          'provider':row.get('publisher') or source, 'kind':'paper'})
    return {'status':'completed','items':items,'source':source,'provenance':'live','retrieved_at':datetime.now(timezone.utc).isoformat(),
            'summary':f'{len(items)} source records from {source} for {query}. Metadata and snippets only; full works were not read.',
            'note':'No matching source records. Try a more specific query.'}


async def execute(domain, args, *, get=fetch_json, notebook=None, now=None):
    validate(domain, args)
    if domain == 'calculate':
        result = calculate(args['expression'])
        return answer(domain,args,args.get('label','The numbers, worked out.'), value=result, expression=args['expression'], summary=f"{args['expression']} = {result}")
    if domain == 'convert':
        value, origin, target, dimension = convert(args['value'],args['from_unit'],args['to_unit'])
        return answer(domain,args,f'{origin} to {target}', value=value, from_value=args['value'], from_unit=origin, to_unit=target, dimension=dimension,
                      summary=f"{args['value']} {origin} = {value:g} {target}.")
    if domain == 'dates':
        data = date_math(args)
        return answer(domain,args,'A date to keep.', **data, summary=f"Date calculation: {data['value']} {data.get('unit','')}.")
    if domain == 'clock':
        data = clock_math(args)
        return answer(domain,args,'Across time zones.', **data, summary=f"{args['at']} in {args['from_zone']} is {data['to_time']} in {args['to_zone']}.")
    if domain == 'world_clocks':
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None: raise ValueError('The current clock must include a timezone.')
        clocks = []
        for location in args['locations']:
            try: local = instant.astimezone(ZoneInfo(location['zone']))
            except (ZoneInfoNotFoundError, ValueError): raise ValueError('Use a valid IANA timezone for each city.') from None
            clocks.append({'id': identifier(domain, location), 'kind': 'world_clock', 'title': location['label'],
                           'zone': location['zone'], 'time': local.isoformat(), 'value': local.strftime('%H:%M'),
                           'date': local.date().isoformat(), 'abbreviation': local.tzname()})
        return {'status': 'completed', 'items': clocks, 'source': 'IANA time zones · device clock', 'provenance': 'computed',
                'retrieved_at': instant.isoformat(), 'summary': ' · '.join(f"{c['title']} {c['value']} {c['abbreviation']}" for c in clocks)}
    if domain == 'timer':
        instant = now or datetime.now(timezone.utc)
        return answer(domain,args,args.get('label','Focus time'), seconds=args['seconds'], end_at=(instant+timedelta(seconds=args['seconds'])).isoformat(),
                      summary=f"{args['seconds']}-second countdown is shown. Keep this page open; this is not a background alarm.")
    if domain == 'document':
        if bool(args.get('rows')) != bool(args.get('columns')): raise ValueError('A comparison needs both column labels and rows.')
        if any(len(row) != len(args['columns']) for row in args.get('rows',[])): raise ValueError('Every comparison row must have one value per column.')
        if not any(block.get('text','').strip() or block.get('items') for block in args['blocks']): raise ValueError('The document needs useful content, not just headings.')
        return answer(domain,args,args['title'], source='Composed by THREAD · AI draft', provenance='draft',
                      document=deepcopy(args), summary=args.get('summary') or f"{args['title']} is ready in the workspace as an editable conversation draft.")
    if domain == 'notes':
        return answer(domain,args,args['title'],source='THREAD notebook · preview',provenance='draft',body=args['body'],
                      summary='Note preview is ready. It is not saved yet. Save this exact note with explicit authorization.')
    if domain == 'library':
        rows = (notebook or Notebook()).search(args.get('query',''))
        return {'status':'completed', 'items':[{'id':r['id'],'kind':'notes','title':r['title'],'body':r['body'],'created':r['created']} for r in rows],
                'source':'THREAD local notebook', 'provenance':'saved', 'summary':f'{len(rows)} saved notes found.', 'note':'No saved notes match this search.'}
    if domain == 'weather': return await weather(args,get)
    if domain == 'research': return await research(args,get)
    if domain in ('web','sports'):
        from .online import search_web
        from .sports import recent_sports
        return await search_web(args) if domain=='web' else await recent_sports(args,get,now)
    if domain == 'currency':
        base, quote_currency = args['from_currency'], args['to_currency']
        if base == quote_currency:
            return answer(domain,args,f'{base} → {quote_currency}',value=args['amount'],amount=args['amount'],base=base,target=quote_currency,rate=1,
                          summary='Both currency codes are identical; no exchange is needed.')
        data = await get(f'https://api.frankfurter.dev/v1/latest', {'base':base,'symbols':quote_currency})
        rate = data['rates'][quote_currency]
        if not isinstance(rate,(int,float)) or not math.isfinite(rate) or rate <= 0: raise ValueError('The source returned an invalid rate.')
        value = float(round(Decimal(str(args['amount']))*Decimal(str(rate)), 2))
        return answer(domain,args,f'{base} → {quote_currency}',source='Frankfurter · reference exchange rates',provenance='live',
                      amount=args['amount'],value=value,base=base,target=quote_currency,rate=rate,date=data['date'],url='https://frankfurter.dev/',
                      summary=f"{args['amount']} {base} ≈ {value} {quote_currency}, reference rate dated {data['date']}. Bank fees and spreads are excluded.")
    raise ValueError('This capability has no executor.')


async def safe_execute(domain, args, **kwargs):
    try: return await execute(domain,args,**kwargs)
    except ValueError as exc: return {'status':'failed','error':str(exc)[:500]}
    except (httpx.HTTPError, TimeoutError, KeyError, TypeError, IndexError):
        return {'status':'failed','error':'The information source is unavailable or returned incomplete data. No result was invented; try again later.'}
