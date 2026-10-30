"""Partner calculations and private-chat flow; all catalog fixtures are synthetic."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from portrait import calculate_compatibility, reduce22

# Reuse production modules with a synthetic private catalog, never real reading texts.
_temp = tempfile.TemporaryDirectory()
_fixture = Path(_temp.name)/'positions.json'
_fixture.write_text(json.dumps([
    {'number':i,'key':{22:'A',23:'B',24:'C',25:'D',26:'E',27:'F',28:'G1',29:'G2',31:'H',32:'Кп',33:'J'}.get(i,f'П{i}'),'title':'Fixture','meaning':'Fixture',
     'arcana':{str(a):{'name':'Fixture','core':'Fixture','positive':'Fixture',
                     'problems':'Synthetic private problems','blocks':'Fixture'} for a in range(1,23)}}
    for i in range(1,34)]))
os.environ.setdefault('CATALOG_PATH',str(_fixture))
from payments import Store, Prices
import bot
from compatibility_catalog import read_catalog

class API:
    def __init__(self): self.messages=[]
    def say(self,cid,text,**extra): self.messages.append({'text':text,**extra})
    def call(self,*args,**kwargs): return {}

class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.directory.name)/'state.sqlite3')
        self.api=API()
        self.store.set_current_birth(1,'16.09.1998')
    def tearDown(self):
        self.store.close(); self.directory.cleanup()
    def message(self,text,cid=1):
        bot.handle(self.api,{'message':{'chat':{'type':'private','id':cid},'from':{'id':cid},'text':text}},self.store,Prices('',''))
    def callback(self,data):
        bot.handle(self.api,{'callback_query':{'id':'test','from':{'id':1},'data':data,
                   'message':{'chat':{'type':'private','id':1}}}},self.store,Prices('',''))
    def test_book_example(self):
        rows=calculate_compatibility('14.11.1948','01.07.1961')
        self.assertEqual([r[3] for r in rows],[15,18,17,11,13,2,6,20])
        self.assertEqual([r[1] for r in rows],[14,11,22,3,11,14,3,3])
        self.assertEqual([r[2] for r in rows],[1,7,17,8,2,10,3,17])
    def test_reduction_and_symmetry(self):
        self.assertEqual([reduce22(x) for x in (22,44,66,36)],[22,22,22,14])
        for a,b in [('31.12.1999','29.02.2000'),('22.01.1980','22.01.1980')]:
            x=calculate_compatibility(a,b); y=calculate_compatibility(b,a)
            self.assertEqual([r[3] for r in x],[r[3] for r in y])
            self.assertTrue(all(1<=r[3]<=22 for r in x))
    def test_two_step_does_not_change_personal_date(self):
        self.message('/compatibility'); self.message('14.11.1948'); self.message('01.07.1961')
        self.assertEqual(self.store.compatibility_dates(1),['14.11.1948','01.07.1961'])
        self.assertEqual(self.store.current_birth(1),'16.09.1998')
        self.assertIn('С8: 20',self.api.messages[-1]['text'])
    def test_two_dates_atomic_and_invalid_date_preserves_state(self):
        self.message('/compatibility'); self.message('14.11.1948\n01.07.1961')
        before=self.store.compatibility_dates(1)
        self.message('16.09.1998 31.02.2000')
        self.assertEqual(self.store.compatibility_dates(1),before)
        self.message('01.01.1990 02.02.1990 03.03.1990')
        self.assertEqual(self.store.compatibility_dates(1),before)
    def test_completed_pair_replacement_and_reset(self):
        self.message('/compatibility'); self.message('14.11.1948 01.07.1961')
        self.message('15.03.1989')
        self.assertEqual(self.store.compatibility_dates(1),['15.03.1989'])
        self.callback('compat_reset')
        self.assertEqual(self.store.compatibility_dates(1),[])
    def test_state_persists_and_users_are_isolated(self):
        self.store.set_compatibility_dates(1,['14.11.1948','01.07.1961'])
        self.store.set_section(1,'compatibility')
        self.store.close();self.store=Store(Path(self.directory.name)/'state.sqlite3')
        self.assertEqual(self.store.section(1),'compatibility')
        self.assertEqual(len(self.store.compatibility_dates(1)),2)
        self.assertEqual(self.store.compatibility_dates(2),[])
    def test_forget_clears_both_dates(self):
        self.store.set_compatibility_dates(1,['14.11.1948','01.07.1961'])
        self.message('/forgetdate')
        self.assertEqual(self.store.compatibility_dates(1),[])
        self.assertIsNone(self.store.current_birth(1))
    def test_lock_checked_before_catalog(self):
        self.message('/compatibility');self.message('14.11.1948 01.07.1961')
        with patch.object(bot,'compatibility_position',side_effect=AssertionError('Must not read')):
            self.callback('compat_position:4')
        self.assertIn('🔒',self.api.messages[-1]['text'])
    def test_member_and_expiry(self):
        self.message('/compatibility');self.message('14.11.1948 01.07.1961')
        with patch.object(bot,'has_full_access',return_value=True),patch.object(bot,'compatibility_position',return_value=('Synthetic title','Synthetic meaning')),patch.object(bot,'compatibility_description',return_value='Synthetic reading'):
            self.callback('compat_position:4')
            self.assertIn('Synthetic meaning',self.api.messages[-1]['text'])
            self.assertIn('П4 першої людини — 3',self.api.messages[-1]['text'])
        self.callback('compat_position:4')
        self.assertNotIn('Synthetic meaning',self.api.messages[-1]['text'])
    def test_menu_and_callback_limits(self):
        menu=bot.main_menu()['inline_keyboard']
        self.assertEqual(sum(b['callback_data']=='section:compatibility' for row in menu for b in row if 'callback_data' in b),1)
        self.message('/compatibility');self.message('14.11.1948 01.07.1961')
        rows=self.api.messages[-1]['reply_markup']['inline_keyboard']
        self.assertEqual(len([b for row in rows for b in row if b['callback_data'].startswith('compat_position:')]),8)
        self.assertTrue(all(len(b['callback_data'].encode())<=64 for row in rows for b in row))
    def test_no_pair_callback_and_invalid_index(self):
        self.callback('compat_position:4')
        self.assertIn('першої людини',self.api.messages[-1]['text'])
        self.callback('compat_position:9')
        self.assertEqual(self.store.compatibility_dates(1),[])
    def test_catalog_shape_rejected(self):
        read_catalog.cache_clear()
        with patch.dict(os.environ,{'COMPATIBILITY_POSITIONS_JSON':'{}'}):
            with self.assertRaises(ValueError):read_catalog()
        read_catalog.cache_clear()

if __name__=='__main__':unittest.main()

class CompatibilityCatalogTests(unittest.TestCase):
    @staticmethod
    def fixture():
        return [dict(number=n,name=f'Fixture {n}',keywords='Synthetic keywords',positions={
            str(i):dict(general=f'General {n}/{i}',positive=f'Positive {n}/{i}',difficulties=f'Difficulties {n}/{i}')
            for i in range(1,9)}) for n in range(1,23)]
    @staticmethod
    def encoded(entries):
        import base64,hashlib,lzma
        raw=json.dumps(entries).encode()
        return dict(COMPATIBILITY_XZ_PARTS='1',COMPATIBILITY_SHA256=hashlib.sha256(raw).hexdigest(),
                    COMPATIBILITY_XZ_B64_1=base64.b64encode(lzma.compress(raw)).decode())
    def tearDown(self):
        from compatibility_catalog import read_arcana_catalog
        read_arcana_catalog.cache_clear()
    def test_all_176_contexts_and_formatting(self):
        from compatibility_catalog import read_arcana_catalog,compatibility_description
        read_arcana_catalog.cache_clear()
        with patch.dict(os.environ,self.encoded(self.fixture())):
            texts=set()
            for n in range(1,23):
                for i in range(1,9):
                    text=compatibility_description(i,n);texts.add(text)
                    self.assertIn(f'General {n}/{i}',text)
                    self.assertIn(f'Positive {n}/{i}',text)
                    self.assertIn(f'Difficulties {n}/{i}',text)
                    rendered=bot.instagram_nickname_link('sendMessage',{'text':text})
                    entities=[e for e in rendered['entities'] if e['type']=='bold']
                    self.assertEqual(len(entities),5)
                    self.assertLess(len(text.encode('utf-16-le'))//2,4096)
            self.assertEqual(len(texts),176)
    def test_corruption_and_missing_positions_rejected(self):
        from compatibility_catalog import read_arcana_catalog
        cases=[]
        corrupt=self.encoded(self.fixture());corrupt['COMPATIBILITY_SHA256']='0'*64;cases.append(corrupt)
        entries=self.fixture();entries[0]['positions'].pop('8');cases.append(self.encoded(entries))
        entries=self.fixture();entries[1]['number']=1;cases.append(self.encoded(entries))
        entries=self.fixture();entries[0]['positions']['1']['positive']='';cases.append(self.encoded(entries))
        for env in cases:
            read_arcana_catalog.cache_clear()
            with patch.dict(os.environ,env):
                with self.assertRaises(ValueError):read_arcana_catalog()
    def test_locked_user_never_loads_private_readings(self):
        store=Store(Path(tempfile.mkdtemp())/'state.sqlite3')
        try:
            store.set_compatibility_dates(1,['14.11.1948','01.07.1961'])
            with patch.object(bot,'compatibility_description',side_effect=AssertionError('Private catalog read')):
                api=API();bot.show_compatibility_position(api,1,4,store)
            self.assertIn('🔒',api.messages[-1]['text'])
        finally:store.close()
