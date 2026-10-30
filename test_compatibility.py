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
        with patch.object(bot,'has_full_access',return_value=True),patch.object(bot,'compatibility_position',return_value=('Synthetic title','Synthetic meaning')):
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
