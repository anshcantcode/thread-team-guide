"""Offline tests of real tool code. Expected values are explicit, not model answers.

These are NOT speech-understanding tests. The separate native-workspace runner
exercises natural language through the actual live model and websocket bridge.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from thread_agent.capabilities import (BUILTINS, DOC_KINDS, Notebook, calculate, convert,
                                       date_math, clock_math, execute, safe_execute, validate)


CALCULATIONS = [
    ('precedence','2+3*4','14'),('parentheses','(2+3)*4','20'),('negative','-18+5','-13'),
    ('decimal_precision','0.1+0.2','0.3'),('percent_tax','18500*1.18','21830'),
    ('split_bill','(1200+1200*0.18)/4','354'),('discount','2499*(1-15/100)','2124.15'),
    ('percent_change','(150-120)/120*100','25'),('compound','10000*(1+5/100)**2','11025'),
    ('budget_remaining','50000-12500-8500-6000','23000'),('recipe_scale','125*6/4','187.5'),
    ('speed_distance','72*2.5','180'),('work_rate','1/(1/6+1/3)','2'),('weighted_mean','(80*3+90*2)/5','84'),
    ('absolute','abs(-32.5)','32.5'),('square_root','sqrt(144)','12'),('root_decimal','sqrt(2.25)','1.5'),
    ('negative_power','2**-3','0.125'),('zero_power','9**0','1'),('negative_base','(-3)**3','-27'),
    ('power_precedence','-2**2','-4'),('right_associative','2**3**2','512'),
    ('remainder','17%5','2'),('negative_remainder','-17%5','3'),('negative_divisor','17%-5','-3'),
    ('floor_division','17//5','3'),('negative_floor','-17//5','-4'),('round_tie_even','round(2.5)','2'),
    ('round_precision','round(12.3456,2)','12.35'),('round_negative','round(1234,-2)','1200'),
    ('sum','sum(5,9,11)','25'),('minimum','min(8,-2,3)','-2'),('maximum','max(8,-2,3)','8'),
    ('nested_functions','max(sqrt(81),abs(-12))','12'),('factorial','factorial(6)','720'),
    ('factorial_zero','factorial(0)','1'),('floor','floor(-3.2)','-4'),('ceil','ceil(-3.2)','-3'),
    ('sine_zero','sin(0)','0'),('cosine_zero','cos(0)','1'),('tangent_zero','tan(0)','0'),
    ('log_ten','log10(10000)','4'),('log_one','log(1)','0'),('pi_area','round(pi*10**2,2)','314.16'),
    ('scientific','1.2e3+4e2','1600'),('unicode_multiply','18×25','450'),('unicode_divide','225÷5','45'),
    ('unicode_minus','12−19','-7'),('unary_plus','+(+3)','3'),('double_negative','--8','8'),
    ('zero','0','0'),('whitespace',' 2 + 4 ','6'),('fraction','3/8','0.375'),
    ('large_integer','999999999999+1','1000000000000'),('small_decimal','0.00001*0.01','0.0000001'),
    ('temperature_formula','(98.6-32)*5/9','37'),('inventory','24*12-17','271'),
    ('time_minutes','2*60+35','155'),('mixed_fraction','2+3/4','2.75'),('multi_discount','1000*.8*.9','720'),
]
INVALID_CALCULATIONS = [
    ('division_zero','1/0'),('floor_zero','2//0'),('mod_zero','2%0'),('sqrt_negative','sqrt(-1)'),
    ('log_zero','log(0)'),('log_negative','log10(-1)'),('huge_power','10**101'),
    ('nested_huge_power','9**9**9'),('fractional_power','2**0.5'),('oversized_literal','1e200'),
    ('nan_name','nan'),('infinite_name','inf'),('infinite_literal','1e999'),('unknown_symbol','x+1'),
    ('import',"__import__('os')"),('file_access',"open('secret')"),('attribute','(1).__class__'),
    ('lambda','(lambda: 3)()'),('comprehension','sum([x for x in range(10)])'),('list','[1,2]'),
    ('dict',"{'a':1}"),('subscript','[1][0]'),('assignment','x=2'),('walrus','(x:=2)'),
    ('string',"'hello'"),('boolean','True'),('conditional','1 if True else 2'),
    ('empty',''),('unterminated','(2+3'),('bitshift','1<<100'),('keyword','round(3,ndigits=1)'),
    ('no_args','sum()'),('factorial_negative','factorial(-1)'),('factorial_fraction','factorial(2.5)'),
    ('factorial_huge','factorial(10000)'),('round_fraction','round(3.14,1.5)'),('round_huge','round(3,999)'),
    ('wrong_arity','sqrt(3,4)'),('overlong','1+'*201+'1'),('oversized_ast','+'.join(['1']*45)),
]
CONVERSIONS = [
    ('km_m',1,'km','m',1000),('m_cm',1,'m','cm',100),('cm_mm',2.5,'cm','mm',25),
    ('mile_km',1,'mi','km',1.609344),('foot_cm',1,'ft','cm',30.48),('inch_mm',1,'in','mm',25.4),
    ('yard_m',1,'yd','m',.9144),('nautical_m',1,'nmi','m',1852),('negative_length',-2,'m','cm',-200),
    ('same_length',123,'ft','ft',123),('alias_inches',12,'inches','feet',1),('case_units',1,'KM','M',1000),
    ('kg_g',1,'kg','g',1000),('g_mg',.5,'g','mg',500),('lb_kg',1,'lb','kg',.45359237),
    ('oz_g',1,'oz','g',28.349523125),('tonne_kg',1,'tonne','kg',1000),('pound_oz',1,'lb','oz',16),
    ('alias_mass',2,'pounds','ounces',32),('l_ml',1,'l','ml',1000),('us_gallon_l',1,'us_gal','l',3.785411784),
    ('us_cup_ml',1,'us_cup','ml',236.5882365),('tablespoon_teaspoon',1,'us_tbsp','us_tsp',3),
    ('cup_tablespoon',1,'cup','tbsp',16),('ml_l',500,'ml','l',.5),('h_min',1.5,'h','min',90),
    ('min_s',2.5,'min','s',150),('day_h',1,'day','h',24),('week_day',2,'week','day',14),
    ('time_alias',3,'hours','minutes',180),('zero_time',0,'min','s',0),('kmh_ms',36,'km/h','m/s',10),
    ('mph_ms',1,'mph','m/s',.44704),('knot_kmh',1,'knot','km/h',1.852),('square_km',1,'km2','m2',1000000),
    ('square_feet',1,'ft2','m2',.09290304),('acre_m2',1,'acre','m2',4046.8564224),
    ('hectare_m2',1,'hectare','m2',10000),('square_alias',2,'m²','ft²',21.5278208334),
    ('kj_j',1,'kj','j',1000),('kcal_j',1,'kcal','j',4184),('kwh_j',1,'kwh','j',3600000),
    ('wh_kj',1,'wh','kj',3.6),('kw_w',2.5,'kw','w',2500),('mw_kw',1,'mw','kw',1000),
    ('kb_byte',1,'kb','byte',1000),('kib_byte',1,'kib','byte',1024),('mb_kb',1,'mb','kb',1000),
    ('mib_kib',1,'mib','kib',1024),('gib_mib',1,'gib','mib',1024),('gb_mb',1,'gb','mb',1000),
    ('tb_gb',1,'tb','gb',1000),('byte_bit',1,'byte','bit',8),('bit_byte',12,'bit','byte',1.5),
    ('c_f_freezing',0,'c','f',32),('c_f_boiling',100,'c','f',212),('f_c_body',98.6,'f','c',37),
    ('negative_f_c',-40,'f','c',-40),('k_c',273.15,'k','c',0),('c_k',-273.15,'c','k',0),
    ('f_k',-459.67,'f','k',0),('k_f',0,'k','f',-459.67),('temperature_alias',20,'Celsius','Fahrenheit',68),
]
INVALID_CONVERSIONS = [
    ('length_mass',1,'m','kg'),('mass_volume',1,'kg','l'),('data_time',1,'byte','s'),
    ('energy_power',1,'j','w'),('area_length',1,'m2','m'),('speed_time',1,'mph','h'),
    ('unknown_from',1,'parsec','m'),('unknown_to',1,'m','banana'),('absolute_c',-274,'c','f'),
    ('absolute_f',-460,'f','c'),('absolute_k',-1,'k','c'),('ambiguous_ton',1,'ton','kg'),
]
DATE_CASES = [
    ('leap_day',{'operation':'add','start':'2024-02-28','days':1},'2024-02-29'),
    ('nonleap_day',{'operation':'add','start':'2025-02-28','days':1},'2025-03-01'),
    ('leap_century',{'operation':'add','start':'2000-02-28','days':1},'2000-02-29'),
    ('nonleap_century',{'operation':'add','start':'1900-02-28','days':1},'1900-03-01'),
    ('year_rollover',{'operation':'add','start':'2026-12-31','days':1},'2027-01-01'),
    ('negative_rollover',{'operation':'add','start':'2026-01-01','days':-1},'2025-12-31'),
    ('month_rollover',{'operation':'add','start':'2026-04-30','days':1},'2026-05-01'),
    ('same_date',{'operation':'add','start':'2026-10-08','days':0},'2026-10-08'),
    ('two_weeks',{'operation':'add','start':'2026-09-13','days':14},'2026-09-27'),
    ('subtract_month',{'operation':'add','start':'2026-03-01','days':-28},'2026-02-01'),
    ('span_leap',{'operation':'between','start':'2024-02-28','end':'2024-03-01'},2),
    ('span_nonleap',{'operation':'between','start':'2025-02-28','end':'2025-03-01'},1),
    ('span_reverse',{'operation':'between','start':'2026-10-08','end':'2026-10-01'},-7),
    ('span_zero',{'operation':'between','start':'2026-10-08','end':'2026-10-08'},0),
    ('weekdays_weekend',{'operation':'weekdays','start':'2026-09-11','end':'2026-09-14'},1),
    ('weekdays_week',{'operation':'weekdays','start':'2026-09-07','end':'2026-09-14'},5),
    ('weekdays_reverse',{'operation':'weekdays','start':'2026-09-14','end':'2026-09-11'},-1),
    ('weekdays_zero',{'operation':'weekdays','start':'2026-09-13','end':'2026-09-13'},0),
    ('weekdays_start_excluded',{'operation':'weekdays','start':'2026-09-11','end':'2026-09-13'},0),
    ('weekdays_not_holidays',{'operation':'weekdays','start':'2026-12-24','end':'2026-12-25'},1),
]
CLOCK_CASES = [
    ('kolkata_utc','2026-10-08T14:00','Asia/Kolkata','UTC','2026-10-08T08:30:00+00:00'),
    ('nepal_offset','2026-10-08T14:00','Asia/Kathmandu','UTC','2026-10-08T08:15:00+00:00'),
    ('newyork_summer','2026-07-01T12:00','America/New_York','UTC','2026-07-01T16:00:00+00:00'),
    ('newyork_winter','2026-01-01T12:00','America/New_York','UTC','2026-01-01T17:00:00+00:00'),
    ('london_summer','2026-07-01T12:00','Europe/London','UTC','2026-07-01T11:00:00+00:00'),
    ('london_winter','2026-01-01T12:00','Europe/London','UTC','2026-01-01T12:00:00+00:00'),
    ('previous_day','2026-01-01T02:00','Asia/Tokyo','UTC','2025-12-31T17:00:00+00:00'),
    ('next_day','2026-01-01T20:00','UTC','Asia/Kolkata','2026-01-02T01:30:00+05:30'),
    ('fold_early','2026-11-01T01:30-04:00','America/New_York','UTC','2026-11-01T05:30:00+00:00'),
    ('fold_late','2026-11-01T01:30-05:00','America/New_York','UTC','2026-11-01T06:30:00+00:00'),
    ('australia_half','2026-01-01T12:00','Australia/Adelaide','UTC','2026-01-01T01:30:00+00:00'),
    ('same_zone','2026-10-08T14:00','Asia/Kolkata','Asia/Kolkata','2026-10-08T14:00:00+05:30'),
]


class ArithmeticTests(unittest.TestCase): pass
class ConversionTests(unittest.TestCase): pass
class CalendarTests(unittest.TestCase): pass


def install(cls, name, fn):
    assert not hasattr(cls,'test_'+name), name
    fn.__name__='test_'+name
    setattr(cls,fn.__name__,fn)


for name,expression,expected in CALCULATIONS:
    def check(self, expression=expression, expected=expected): self.assertEqual(Decimal(calculate(expression)),Decimal(expected))
    install(ArithmeticTests,name,check)
for name,expression in INVALID_CALCULATIONS:
    def check(self, expression=expression):
        with self.assertRaises(ValueError): calculate(expression)
    install(ArithmeticTests,'reject_'+name,check)
for name,value,origin,target,expected in CONVERSIONS:
    def check(self,value=value,origin=origin,target=target,expected=expected): self.assertAlmostEqual(convert(value,origin,target)[0],expected,places=7)
    install(ConversionTests,name,check)
for name,value,origin,target in INVALID_CONVERSIONS:
    def check(self,value=value,origin=origin,target=target):
        with self.assertRaises(ValueError): convert(value,origin,target)
    install(ConversionTests,'reject_'+name,check)
for name,args,expected in DATE_CASES:
    def check(self,args=args,expected=expected): self.assertEqual(date_math(args)['value'],expected)
    install(CalendarTests,name,check)
for name,at,source,target,expected in CLOCK_CASES:
    def check(self,at=at,source=source,target=target,expected=expected): self.assertEqual(clock_math({'at':at,'from_zone':source,'to_zone':target})['to_time'],expected)
    install(CalendarTests,name,check)
for name,args in [
    ('missing_add_days',{'operation':'add','start':'2026-01-01'}),
    ('missing_end',{'operation':'between','start':'2026-01-01'}),
    ('invalid_date',{'operation':'add','start':'2026-02-29','days':1}),
    ('range_overflow',{'operation':'add','start':'9999-12-31','days':1}),
    ('range_underflow',{'operation':'add','start':'0001-01-01','days':-1}),
    ('excessive_span',{'operation':'between','start':'1900-01-01','end':'2200-01-01'}),
]:
    def check(self,args=args):
        with self.assertRaises(ValueError): date_math(args)
    install(CalendarTests,'reject_'+name,check)
for name,at,zone in [
    ('dst_gap','2026-03-08T02:30','America/New_York'),('dst_fold','2026-11-01T01:30','America/New_York'),
    ('offset_conflict','2026-07-01T12:00-05:00','America/New_York'),('bad_zone','2026-01-01T12:00','Not/AZone'),
    ('abbreviation','2026-01-01T12:00','IST'),('missing_time','2026-01-01','UTC'),('bad_datetime','Tuesday','UTC'),
]:
    def check(self,at=at,zone=zone):
        with self.assertRaises(ValueError): clock_math({'at':at,'from_zone':zone,'to_zone':'UTC'})
    install(CalendarTests,'reject_'+name,check)


INVALID_ARGUMENTS = [
    ('calc_missing','calculate',{}),('calc_number','calculate',{'expression':7}),('calc_empty','calculate',{'expression':''}),
    ('calc_command','calculate',{'expression':'2+2','command':'echo secret'}),
    ('convert_string','convert',{'value':'1','from_unit':'km','to_unit':'m'}),
    ('convert_infinite','convert',{'value':float('inf'),'from_unit':'m','to_unit':'km'}),
    ('convert_nan','convert',{'value':float('nan'),'from_unit':'m','to_unit':'km'}),
    ('convert_bool','convert',{'value':True,'from_unit':'m','to_unit':'km'}),
    ('convert_missing_unit','convert',{'value':1,'from_unit':'m'}),
    ('currency_lower','currency',{'amount':100,'from_currency':'usd','to_currency':'INR'}),
    ('currency_long','currency',{'amount':100,'from_currency':'USDD','to_currency':'INR'}),
    ('weather_no_city','weather',{'days':3}),('weather_too_many','weather',{'city':'Delhi','days':8}),
    ('weather_zero','weather',{'city':'Delhi','days':0}),('weather_country','weather',{'city':'Delhi','country_code':'India'}),
    ('weather_url','weather',{'city':'Delhi','url':'http://localhost'}),
    ('research_empty','research',{'query':''}),('research_unknown','research',{'query':'x','collection':'private email'}),
    ('research_long','research',{'query':'x'*201}),('dates_format','dates',{'operation':'add','start':'today','days':1}),
    ('dates_bad_operation','dates',{'operation':'guess','start':'2026-10-08'}),
    ('dates_fraction','dates',{'operation':'add','start':'2026-10-08','days':1.5}),
    ('timer_negative','timer',{'seconds':-1}),('timer_zero','timer',{'seconds':0}),('timer_too_long','timer',{'seconds':86401}),
    ('timer_fraction','timer',{'seconds':1.25}),('timer_boolean','timer',{'seconds':True}),
    ('note_empty_title','notes',{'title':'','body':'yes'}),('note_empty_body','notes',{'title':'Title','body':''}),
    ('note_overlong','notes',{'title':'Title','body':'x'*15001}),('note_path','notes',{'title':'T','body':'text','path':'C:/secret'}),
    ('document_no_blocks','document',{'title':'T','kind':'plan','blocks':[]}),
    ('document_unknown','document',{'title':'T','kind':'execute','blocks':[{'heading':'H','text':'x'}]}),
    ('document_html_field','document',{'title':'T','kind':'plan','blocks':[{'heading':'H','html':'<b>x</b>'}]}),
    ('document_many_columns','document',{'title':'T','kind':'comparison','blocks':[{'heading':'H','text':'x'}],'columns':['a']*6}),
    ('library_path','library',{'query':'x','path':'../'}),
]


class SchemaTests(unittest.TestCase): pass
for name,domain,args in INVALID_ARGUMENTS:
    def check(self,domain=domain,args=args):
        with self.assertRaises(ValueError): validate(domain,args)
    install(SchemaTests,'reject_'+name,check)


class ToolEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_is_failure_not_empty_search(self):
        async def get(*args): raise httpx.ReadTimeout('unavailable')
        r=await safe_execute('research',{'query':'x'},get=get)
        self.assertEqual(r['status'],'failed');self.assertNotIn('items',r)

    async def test_invalid_json_is_failure(self):
        async def get(*args): raise json.JSONDecodeError('bad','',0)
        self.assertEqual((await safe_execute('research',{'query':'x'},get=get))['status'],'failed')

    async def test_currency_uses_returned_date_and_rate(self):
        async def get(url,args):
            self.assertEqual(args,{'base':'USD','symbols':'INR'})
            return {'date':'2026-09-11','rates':{'INR':89.125}}
        r=await execute('currency',{'amount':12,'from_currency':'USD','to_currency':'INR'},get=get)
        self.assertEqual(r['items'][0]['value'],1069.5);self.assertEqual(r['items'][0]['date'],'2026-09-11');self.assertEqual(r['provenance'],'live')

    async def test_same_currency_never_fetches(self):
        async def get(*args): self.fail('unnecessary network request')
        r=await execute('currency',{'amount':75,'from_currency':'INR','to_currency':'INR'},get=get)
        self.assertEqual(r['items'][0]['value'],75);self.assertEqual(r['provenance'],'computed')

    async def test_currency_invalid_rate_fails(self):
        async def get(*args): return {'date':'2026-09-11','rates':{'INR':-1}}
        self.assertEqual((await safe_execute('currency',{'amount':12,'from_currency':'USD','to_currency':'INR'},get=get))['status'],'failed')

    async def test_missing_weather_city_is_empty_not_invented(self):
        async def get(*args): return {}
        r=await execute('weather',{'city':'Atlantis'},get=get)
        self.assertEqual(r['items'],[]);self.assertIn('No matching city',r['note'])

    async def test_weather_ambiguity_requests_country(self):
        async def get(*args): return {'results':[{'name':'Same','country_code':'AA','population':100000},{'name':'Same','country_code':'BB','population':100000}]}
        r=await safe_execute('weather',{'city':'Same'},get=get)
        self.assertEqual(r['status'],'failed');self.assertIn('country',r['error'])

    async def test_weather_incomplete_source_fails(self):
        async def get(url,args): return {'results':[{'name':'Delhi','latitude':28.6,'longitude':77.2}]} if 'geocoding' in url else {}
        self.assertEqual((await safe_execute('weather',{'city':'Delhi','country_code':'IN'},get=get))['status'],'failed')

    async def test_paper_metadata_has_real_doi_link(self):
        async def get(*args): return {'message':{'items':[{'DOI':'10.1234/test','title':['A study'],'author':[{'given':'A','family':'B'}],'published':{'date-parts':[[2025,4]]},'publisher':'Test press'}]}}
        r=await execute('research',{'query':'x','collection':'papers'},get=get)
        self.assertEqual(r['items'][0]['url'],'https://doi.org/10.1234/test');self.assertEqual(r['items'][0]['published'],'2025');self.assertIn('full works were not read',r['summary'])

    async def test_book_metadata_preserves_authors(self):
        async def get(*args): return {'docs':[{'key':'/works/OL1W','title':'A book','author_name':['Someone'],'first_publish_year':1969}]}
        r=await execute('research',{'query':'x','collection':'books'},get=get)
        self.assertEqual(r['items'][0]['detail'],'Someone');self.assertEqual(r['items'][0]['url'],'https://openlibrary.org/works/OL1W')

    async def test_wikipedia_snippet_strips_markup(self):
        async def get(*args): return {'query':{'search':[{'pageid':8,'title':'A topic','snippet':'A <b>topic</b> &amp; evidence.'}]}}
        r=await execute('research',{'query':'x'},get=get)
        self.assertEqual(r['items'][0]['detail'],'A topic & evidence.');self.assertEqual(r['items'][0]['url'],'https://en.wikipedia.org/?curid=8')

    async def test_timer_uses_server_deadline(self):
        r=await execute('timer',{'seconds':90},now=datetime(2026,9,13,0,0,tzinfo=timezone.utc))
        self.assertEqual(r['items'][0]['end_at'],'2026-09-13T00:01:30+00:00');self.assertIn('not a background alarm',r['summary'])

    async def test_note_preview_does_not_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'notes.db';r=await execute('notes',{'title':'T','body':'B'},notebook=Notebook(path))
            self.assertFalse(path.exists());self.assertEqual(r['provenance'],'draft')

    async def test_comparison_misaligned_row_fails(self):
        r=await safe_execute('document',{'kind':'comparison','title':'T','blocks':[{'heading':'H','text':'x'}],'columns':['A','B','C'],'rows':[['a','b']]})
        self.assertEqual(r['status'],'failed')

    async def test_document_empty_content_fails(self):
        r=await safe_execute('document',{'kind':'plan','title':'T','blocks':[{'heading':'Only a heading'}]})
        self.assertEqual(r['status'],'failed')


for kind in DOC_KINDS:
    async def check(self,kind=kind):
        args={'kind':kind,'title':'A useful '+kind,'blocks':[{'heading':'First part','text':'A substantive draft.','items':['Keep this explicit constraint.']}]}
        r=await execute('document',args)
        self.assertEqual(r['items'][0]['document'],args);self.assertEqual(r['provenance'],'draft');self.assertNotIn('reference',r)
    install(ToolEvidenceTests,'document_'+kind,check)


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'notes.sqlite';self.store=Notebook(self.path)
    def tearDown(self): self.temp.cleanup()
    def save(self,id='one',title='A note',body='Keep this'): return self.store.save(id,{'title':title,'body':body})
    def test_save_persists_across_instances(self):
        self.save();self.assertEqual(Notebook(self.path).search()[0]['body'],'Keep this')
    def test_duplicate_operation_id_cannot_rewrite(self):
        self.save();self.save(title='Changed',body='Changed');self.assertEqual(self.store.search()[0]['body'],'Keep this')
    def test_distinct_operation_allows_second_note(self):
        self.save();self.save('two');self.assertEqual(len(self.store.search()),2)
    def test_search_title_case_insensitive(self):
        self.save(title='Packing');self.assertEqual(len(self.store.search('PACK')),1)
    def test_search_body_case_insensitive(self):
        self.save(body='Buy milk');self.assertEqual(len(self.store.search('MILK')),1)
    def test_sql_injection_is_literal(self):
        self.save();self.assertEqual(self.store.search("' OR 1=1 --"),[]);self.assertEqual(len(self.store.search()),1)
    def test_sql_wildcards_are_literal(self):
        self.save();self.assertEqual(self.store.search('%'),[])
    def test_unicode_note_preserved(self):
        self.save(title='याद रखना',body='தமிழ் 日本語 🧵');self.assertEqual(self.store.search()[0]['body'],'தமிழ் 日本語 🧵')
    def test_cancel_archives_only_target(self):
        self.save();self.save('two');self.assertEqual(self.store.cancel('one')['status'],'cancelled');self.assertEqual(self.store.search()[0]['id'],'two')
    def test_unknown_status_not_performed(self): self.assertEqual(self.store.status('missing')['status'],'not_performed')
    def test_cancel_unknown_note(self): self.assertEqual(self.store.cancel('missing')['status'],'not_performed')
    def test_injection_in_title_cannot_change_table(self):
        self.save(title="'); DROP TABLE notes;--");self.assertEqual(len(self.store.search()),1)


if __name__ == '__main__': unittest.main()
