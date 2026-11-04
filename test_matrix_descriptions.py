"""Approved count/line/triangle rules and access boundaries; synthetic text only."""
import base64,hashlib,json,lzma,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_compatibility
import bot
from portrait import matrix_patterns,calculate_matrix
from matrix_catalog import VARIANTS,LINE_IDS,read_matrix_catalog,matrix_digit_description
from payments import Store,Prices
from test_payments import Fake,callback
from test_invitations import message


def fixture():
    data={'digits':{str(d):{'title':f'Test digit {d}','intro':'Test intro',
          'variants':{key:f'Only count {d}/{key}' for key in variants}} for d,variants in VARIANTS.items()},
          'lines':{key:{'title':f'Test {key}','text':f'Only line {key}'} for key in LINE_IDS},
          'triangles':{key:{'title':f'Test {key}','text':f'Only triangle {key}'} for key in ('altruism','personal')}}
    raw=json.dumps(data).encode()
    env={'MATRIX_XZ_PARTS':'1','MATRIX_SHA256':hashlib.sha256(raw).hexdigest(),
         'MATRIX_XZ_B64_1':base64.b64encode(lzma.compress(raw)).decode()}
    return data,env


class MatrixRules(unittest.TestCase):
    def test_all_equal_complete_lines_are_selected(self):
        result=matrix_patterns(dict.fromkeys(range(1,10),1))
        self.assertEqual(set(result['selected_lines']),set(LINE_IDS))
    def test_incomplete_maximum_is_not_called_filled(self):
        counts=dict.fromkeys(range(1,10),1);counts[1]=0;counts[4]=10;counts[7]=10
        result=matrix_patterns(counts)
        self.assertEqual(result['lines']['h147']['total'],20)
        self.assertFalse(result['lines']['h147']['complete']);self.assertEqual(result['selected_lines'],[])
    def test_triangle_correction_uses_eight_not_six(self):
        counts=dict.fromkeys(range(1,10),1);counts[6]=30
        result=matrix_patterns(counts)
        self.assertEqual(result['triangles']['personal']['digits'],(5,3,8,9))
        self.assertEqual(result['selected_triangles'],['altruism','personal'])
        counts[8]=0
        self.assertEqual(matrix_patterns(counts)['selected_triangles'],['altruism'])
    def test_triangles_require_every_digit_and_compare_repetitions(self):
        counts=dict.fromkeys(range(1,10),1);counts[9]=4
        result=matrix_patterns(counts)
        self.assertEqual(result['selected_triangles'],['personal'])
        self.assertEqual(result['triangles']['personal']['total'],7)
        counts[5]=0;self.assertEqual(matrix_patterns(counts)['selected_triangles'],[])
    def test_worksheet_example(self):
        result=matrix_patterns(calculate_matrix('16.09.1998')['counts'])
        self.assertEqual(result['selected_lines'],['d159'])
        self.assertEqual(result['selected_triangles'],['altruism'])
    def test_bad_counts(self):
        for counts in ({1:1},dict.fromkeys(range(1,10),-1),dict.fromkeys(range(1,10),True)):
            with self.assertRaises(ValueError):matrix_patterns(counts)


class MatrixReadings(unittest.TestCase):
    def setUp(self):
        self.data,env=fixture();self.env=patch.dict(os.environ,env);self.env.start();read_matrix_catalog.cache_clear()
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db');self.api=Fake();self.prices=Prices('','')
    def tearDown(self):
        self.store.close();self.temp.cleanup();self.env.stop();read_matrix_catalog.cache_clear()
    def grant(self,tier='full'):
        iid,token=self.store.create_invitation(99,'+380991234567',tier=tier)
        self.store.begin_invitation(7,token);self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
        return iid
    def click(self,action):bot.handle(self.api,callback(action),self.store,self.prices)
    def test_all_31_variants_and_open_ranges(self):
        self.assertEqual(sum(len(d['variants']) for d in self.data['digits'].values()),31)
        for d,variants in VARIANTS.items():
            for key in variants:
                self.assertIn(f'Only count {d}/{key}',matrix_digit_description(d,int(key.rstrip('+'))))
            self.assertIn(f'Only count {d}/{variants[-1]}',matrix_digit_description(d,12))
        self.assertNotIn('Only count',matrix_digit_description(1,0))
    def test_invalid_hash_and_partial_catalog(self):
        with patch.dict(os.environ,{'MATRIX_SHA256':'invalid'}):
            with self.assertRaises(ValueError):read_matrix_catalog()
        self.data['digits']['1']['variants'].pop('2');raw=json.dumps(self.data).encode()
        with patch.dict(os.environ,{'MATRIX_SHA256':hashlib.sha256(raw).hexdigest(),'MATRIX_XZ_B64_1':base64.b64encode(lzma.compress(raw)).decode()}):
            with self.assertRaises(ValueError):read_matrix_catalog()
    def test_public_cannot_load_private_content_and_stale_revoked_access(self):
        self.store.set_current_birth(7,'16.09.1998')
        with patch('bot.read_matrix_catalog',side_effect=AssertionError('private catalog accessed')),patch('bot.matrix_digit_description',side_effect=AssertionError('private text accessed')):
            for action in ('matrix_digit:1','matrix_lines','matrix_triangles'):
                self.click(action);self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
        iid=self.grant();self.store.revoke_invitation(99,iid)
        self.click('matrix_digit:1');self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
    def test_full_and_pro_readings(self):
        self.grant();self.store.set_current_birth(7,'16.09.1998')
        self.click('matrix_digit:1');self.assertIn('Only count 1/3+',self.api.calls[-1][1]['text'])
        self.click('matrix_lines');self.assertIn('Only line d159',self.api.calls[-1][1]['text']);self.assertNotIn('Only line h147',self.api.calls[-1][1]['text'])
        self.click('matrix_triangles');self.assertIn('Only triangle altruism',self.api.calls[-1][1]['text']);self.assertNotIn('Only triangle personal',self.api.calls[-1][1]['text'])
    def test_equal_triangle_descriptions_and_expiry(self):
        self.grant('pro');self.store.set_current_birth(7,'16.09.1998')
        with patch('bot.calculate_matrix',return_value={'counts':dict.fromkeys(range(1,10),1)}):
            self.click('matrix_triangles');text=self.api.calls[-1][1]['text']
            self.assertIn('Only triangle altruism',text);self.assertIn('Only triangle personal',text);self.assertIn('однакову',text)
        with patch('bot.time.time',return_value=self.store.membership_until(7)):
            self.click('matrix_lines');self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
    def test_latest_birth_in_old_buttons_and_no_birth(self):
        self.grant();self.click('matrix_digit:2');self.assertIn('Надішліть дату',self.api.calls[-1][1]['text'])
        bot.handle(self.api,message('16.09.1998'),self.store,self.prices);self.click('matrix_digit:2')
        self.assertIn('Only count 2/1',self.api.calls[-1][1]['text'])
        bot.handle(self.api,message('20.03.2024'),self.store,self.prices);self.click('matrix_digit:2')
        self.assertIn('Only count 2/3+',self.api.calls[-1][1]['text']);self.assertIn('20.03.2024',self.api.calls[-1][1]['text'])
    def test_invalid_callbacks_are_ignored(self):
        self.grant();self.store.set_current_birth(7,'16.09.1998')
        for action in ('matrix_digit:0','matrix_digit:10','matrix_digit:a','matrix_lines:evil','matrix_triangles:1'):
            self.click(action)
        self.assertFalse(any(c[0]=='sendMessage' for c in self.api.calls))

if __name__=='__main__':unittest.main()
