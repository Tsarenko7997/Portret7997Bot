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
    def call(self,method,data=None,file=None):
        if method=='sendPhoto': self.messages.append({'text':data.get('caption',''),**data,'photo':file})
        return {}

class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.directory.name)/'state.sqlite3')
        self.api=API()
        self.store.set_current_birth(1,'16.09.1998')
        self.store.set_compatibility_kind(1,'general')
        self.position_patch=patch.object(bot,'compatibility_position',side_effect=lambda i,kind='general':(f'Position meaning {i}','Synthetic meaning'))
        self.position_patch.start()
        self.image_patch=patch.object(bot,'draw_compatibility',return_value=b'synthetic image')
        self.draw=self.image_patch.start()
    def tearDown(self):
        self.image_patch.stop();self.position_patch.stop()
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
        self.assertEqual(self.draw.call_args.args[2][-1][-1],20)
        self.assertIn('photo',self.api.messages[-1])
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
            self.assertNotIn('Складові позиції',self.api.messages[-1]['text'])
            self.assertNotIn('Розрахунок:',self.api.messages[-1]['text'])
            self.assertNotIn('→',self.api.messages[-1]['text'])
        self.callback('compat_position:4')
        self.assertNotIn('Synthetic meaning',self.api.messages[-1]['text'])
    def test_menu_and_callback_limits(self):
        menu=bot.main_menu()['inline_keyboard']
        self.assertEqual(sum(b['callback_data']=='section:compatibility' for row in menu for b in row if 'callback_data' in b),1)
        self.message('/compatibility');self.message('14.11.1948 01.07.1961')
        rows=self.api.messages[-1]['reply_markup']['inline_keyboard']
        self.assertEqual(len([b for row in rows for b in row if b['callback_data'].startswith('compat_position:')]),8)
        self.assertTrue(all(len(b['callback_data'].encode())<=64 for row in rows for b in row))
        self.assertEqual([len(r) for r in rows[:2]],[4,4])
        self.assertEqual([b['text'] for row in rows[:2] for b in row],['🔒 '+str(i) for i in range(1,9)])
        caption=self.api.messages[-1]['text']
        for i in range(1,9):self.assertIn(f'С{i} · Position meaning {i}',caption)
        for formula in ['→',' + ','Розрахунок:','Складові позиції']:self.assertNotIn(formula,caption)
        self.assertLessEqual(len(caption.encode('utf-16-le'))//2,1024)
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

class CompatibilityKindTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.directory.name)/'state.sqlite3');self.api=API()
        self.images=patch.object(bot,'draw_compatibility',return_value=b'fixture image');self.draw=self.images.start()
        self.positions=patch.object(bot,'compatibility_position',side_effect=lambda n,k='general':(f'{k} title {n}',f'{k} meaning {n}'));self.positions.start()
    def tearDown(self):
        self.positions.stop();self.images.stop();self.store.close();self.directory.cleanup()
    message=CompatibilityTests.message
    callback=CompatibilityTests.callback
    def test_initial_selection_and_dates_require_choice(self):
        self.message('/compatibility')
        buttons=self.api.messages[-1]['reply_markup']['inline_keyboard']
        self.assertEqual([r[0]['callback_data'] for r in buttons[:3]],['compat_kind:love','compat_kind:general','compat_kind:parent'])
        self.message('14.11.1948 01.07.1961')
        self.assertEqual(self.store.compatibility_dates(1),[])
    def test_love_and_general_reuse_pair_but_change_button_context(self):
        self.callback('compat_kind:love');self.message('14.11.1948 01.07.1961')
        pair=self.store.compatibility_dates(1)
        self.assertEqual(self.draw.call_args.args[-1],'love')
        self.callback('compat_kind:general')
        self.assertEqual(self.store.compatibility_dates(1),pair)
        self.assertIn('compat_position:general:1',str(self.api.messages[-1]))
        self.assertIn('Загальна',self.api.messages[-1]['text'])
    def test_parent_role_boundary_clears_old_pair(self):
        self.callback('compat_kind:love');self.message('14.11.1948 01.07.1961')
        self.callback('compat_kind:parent')
        self.assertEqual(self.store.compatibility_dates(1),[])
        self.assertIn('мами або тата',self.api.messages[-1]['text'])
        self.message('16.09.1998');self.assertIn('дитини',self.api.messages[-1]['text'])
        self.message('20.03.2024')
        self.assertEqual(self.store.compatibility_dates(1),['16.09.1998','20.03.2024'])
        self.assertEqual(self.draw.call_args.args[-1],'parent')
        self.callback('compat_kind:general')
        self.assertEqual(self.store.compatibility_dates(1),[])
    def test_stale_kind_button_never_reads_wrong_text(self):
        self.callback('compat_kind:love');self.message('14.11.1948 01.07.1961');self.callback('compat_kind:general')
        with patch.object(bot,'compatibility_description',side_effect=AssertionError('Stale read')):
            self.callback('compat_position:love:1')
        self.assertEqual(self.store.compatibility_kind(1),'general')
        self.assertTrue(any('Тип сумісності змінено' in m['text'] for m in self.api.messages))
    def test_all_kinds_enforce_membership_before_reading(self):
        for kind in ('love','general','parent'):
            self.store.set_compatibility_kind(1,kind)
            self.store.set_compatibility_dates(1,['16.09.1998','20.03.2024'])
            with patch.object(bot,'compatibility_description',side_effect=AssertionError('Locked read')):
                self.callback(f'compat_position:{kind}:4')
            self.assertIn('🔒',self.api.messages[-1]['text'])
    def test_member_reads_selected_context_and_no_formula(self):
        self.callback('compat_kind:parent');self.message('16.09.1998 20.03.2024')
        with patch.object(bot,'has_full_access',return_value=True),patch.object(bot,'compatibility_description',return_value='Parent fixture') as reading:
            self.callback('compat_position:parent:3')
            self.assertEqual(reading.call_args.args[0],3);self.assertEqual(reading.call_args.args[2],'parent')
        self.assertIn('Parent fixture',self.api.messages[-1]['text'])
        self.assertNotIn('→',self.api.messages[-1]['text'])
    def test_kind_persists_and_forget_clears_it(self):
        self.store.set_compatibility_kind(1,'parent');self.store.close()
        self.store=Store(Path(self.directory.name)/'state.sqlite3')
        self.assertEqual(self.store.compatibility_kind(1),'parent')
        self.message('/forgetdate');self.assertIsNone(self.store.compatibility_kind(1))
    def test_new_pair_retains_kind_and_type_picker_keeps_dates(self):
        self.callback('compat_kind:love');self.message('14.11.1948 01.07.1961')
        self.callback('compat_types');self.assertEqual(len(self.store.compatibility_dates(1)),2)
        self.callback('compat_result');self.assertIn('Любовна',self.api.messages[-1]['text'])
        self.callback('compat_reset')
        self.assertEqual(self.store.compatibility_dates(1),[]);self.assertEqual(self.store.compatibility_kind(1),'love')

class ExpandedCatalogTests(unittest.TestCase):
    def tearDown(self):
        from compatibility_catalog import read_arcana_catalog
        from forecast_catalog import read_forecast_catalog
        read_arcana_catalog.cache_clear();read_forecast_catalog.cache_clear()
    def test_528_distinct_contexts_and_practical_heading(self):
        from compatibility_catalog import read_arcana_catalog,compatibility_description
        rows=CompatibilityCatalogTests.fixture()
        for row in rows:
            row['variants']={kind:{'keywords':kind,'positions':{str(i):{key:f'{kind}/{row["number"]}/{i}/{key}' for key in ('general','positive','difficulties','practical')} for i in range(1,9)}} for kind in ('love','general','parent')}
        with patch.dict(os.environ,CompatibilityCatalogTests.encoded(rows)):
            read_arcana_catalog.cache_clear();texts=set()
            for kind in ('love','general','parent'):
                for n in range(1,23):
                    for i in range(1,9):
                        text=compatibility_description(i,n,kind);texts.add(text)
                        self.assertIn(f'{kind}/{n}/{i}/general',text)
                        self.assertIn('Практичний орієнтир.',text)
            self.assertEqual(len(texts),528)
    def test_partial_kind_catalog_is_rejected(self):
        from compatibility_catalog import read_arcana_catalog
        rows=CompatibilityCatalogTests.fixture();rows[0]['variants']={'love':{}}
        with patch.dict(os.environ,CompatibilityCatalogTests.encoded(rows)):
            read_arcana_catalog.cache_clear()
            with self.assertRaises(ValueError):read_arcana_catalog()
    def test_forecast_practical_is_optional_but_validated_and_formatted(self):
        from test_forecast_descriptions import fixture,encoded
        from forecast_catalog import read_forecast_catalog,forecast_description
        rows=fixture()
        rows[0]['forecasts']['day']['practical']='Synthetic practical action'
        with patch.dict(os.environ,encoded(rows)):
            read_forecast_catalog.cache_clear();text=forecast_description('day',1)
            self.assertIn('Практичний орієнтир. Synthetic practical action',text)
            result=bot.instagram_nickname_link('sendMessage',{'text':text})
            self.assertEqual(len([e for e in result['entities'] if e['type']=='bold']),6)
        rows[0]['forecasts']['day']['practical']=123
        with patch.dict(os.environ,encoded(rows)):
            read_forecast_catalog.cache_clear()
            with self.assertRaises(ValueError):read_forecast_catalog()
