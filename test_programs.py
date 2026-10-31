"""Program calculations, private catalog validation and Pro authorization flow."""
import base64
import hashlib
import json
import lzma
import os
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import test_compatibility  # synthetic portrait fixture, no paid text in source control
import bot
from payments import Store,Prices
from portrait import calculate_program
from program_catalog import read_program_catalog,program_description
from render import draw_program
from test_payments import Fake,callback
from test_invitations import message


def fixture():
    data={'programs':{str(n):{'title':f'Test program {n}','overview':f'Test overview {n}',
        'questions':[{'question':f'Test question {n}/{q}','lens':f'Test lens {n}/{q}',
                      'practical':f'Test action {n}/{q}'} for q in range(1,7)]} for n in range(1,22)},
        'arcana':{str(n):{k:f'Test {k} {n}' for k in ('name','keywords','general','positive','difficulties','practical')}
                  for n in range(1,23)}}
    for a in data['arcana'].values():a['facets']={key:f'Test focus {key}' for key in ('communication','money','work','learning','relations','spirit','creativity')}
    raw=json.dumps(data).encode()
    return data,{'PROGRAMS_XZ_PARTS':'1','PROGRAMS_XZ_B64_1':base64.b64encode(lzma.compress(raw)).decode(),
                 'PROGRAMS_SHA256':hashlib.sha256(raw).hexdigest()}


class ProgramCalculations(unittest.TestCase):
    def test_independent_book_examples(self):
        for date,n,expected in [('28.09.1974',1,[7,10,22,16,9,2]),('14.02.1936',2,[16,4,21,18,1,17]),
                                ('13.10.1966',10,[1,20,10,11,20,21]),('09.10.1874',21,[8,9,19,18,7,4])]:
            with self.subTest(date=date,program=n):self.assertEqual(list(calculate_program(date,n).values()),expected)
    def test_each_original_position_is_shifted_independently(self):
        from portrait import calculate,reduce22
        for n in range(1,22):
            base,_=calculate('16.09.1998');result=calculate_program('16.09.1998',n)
            self.assertEqual(result,{i:reduce22(base[f'П{i}']+n) for i in range(1,7)})
        self.assertEqual(calculate_program('16.09.1998',1)[4],4) # recalculating from shifted P1/P2 would give 5
    def test_validation(self):
        for n in (0,22,-1,True,1.0,'1',None):
            with self.assertRaises(ValueError):calculate_program('16.09.1998',n)
        for date in ('31.02.2000','2000-01-01','16.09.2998',''):
            with self.assertRaises(ValueError):calculate_program(date,1)
    def test_render(self):
        blob=draw_program('16.09.1998',1,'Test title',calculate_program('16.09.1998',1))
        self.assertEqual(Image.open(BytesIO(blob)).size,(1414,1640))


class ProgramFlow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db');self.api=Fake();self.prices=Prices('','')
        self.data,env=fixture();self.env=patch.dict(os.environ,env);self.env.start();read_program_catalog.cache_clear()
    def tearDown(self):
        read_program_catalog.cache_clear();self.env.stop();self.store.close();self.temp.cleanup()
    def grant(self,tier='pro'):
        iid,token=self.store.create_invitation(99,'+380991234567',tier=tier)
        self.store.begin_invitation(7,token);self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
        return iid
    def click(self,text):bot.handle(self.api,callback(text),self.store,self.prices)
    def text(self,text):bot.handle(self.api,message(text),self.store,self.prices)
    def test_all_combinations_valid_and_question_specific(self):
        from catalog import chunks
        for n in range(1,22):
            for q in range(1,7):
                for a in range(1,23):
                    value=program_description(n,q,a)
                    self.assertIn(f'Test lens {n}/{q}',value);self.assertIn(f'Test general {a}',value)
                    self.assertTrue(all(len(c.encode('utf-16-le'))//2<=3900 for c in chunks(value)))
    def test_checksum_and_incomplete_catalog_fail_closed(self):
        with patch.dict(os.environ,{'PROGRAMS_SHA256':'bad'}):
            with self.assertRaises(ValueError):read_program_catalog()
        self.data['programs']['1']['questions'].pop()
        raw=json.dumps(self.data).encode()
        with patch.dict(os.environ,{'PROGRAMS_XZ_B64_1':base64.b64encode(lzma.compress(raw)).decode(),'PROGRAMS_SHA256':hashlib.sha256(raw).hexdigest()}):
            with self.assertRaises(ValueError):read_program_catalog()
    def test_full_and_expired_or_revoked_pro_cannot_load_private_catalog(self):
        iid=self.grant('full')
        with patch('bot.read_program_catalog',side_effect=AssertionError('private catalog accessed')),patch('bot.program_entry',side_effect=AssertionError('private entry accessed')):
            for route in ('programs','program:1','program_question:1:1'):
                self.click(route);self.assertIn('лише в пакеті Pro',self.api.calls[-1][1]['text'])
        self.store.revoke_invitation(99,iid)
    def test_stale_pro_buttons_recheck_expiry_and_revocation(self):
        iid=self.grant();self.store.set_current_birth(7,'16.09.1998')
        with patch('bot.time.time',return_value=self.store.pro_until(7)+1):
            self.click('program_question:1:1');self.assertIn('лише в пакеті Pro',self.api.calls[-1][1]['text'])
        self.store.revoke_invitation(99,iid)
        self.click('program:1');self.assertIn('лише в пакеті Pro',self.api.calls[-1][1]['text'])
    def test_menu_has_exactly_21_numbered_buttons(self):
        self.grant();self.click('programs')
        buttons=[b for row in self.api.calls[-1][1]['reply_markup']['inline_keyboard'] for b in row]
        self.assertEqual([b['text'] for b in buttons if b['callback_data'].startswith('program:')],list(map(str,range(1,22))))
    def test_birth_prompt_resume_and_six_questions(self):
        self.grant();self.click('program:2');self.assertIn('дату народження',self.api.calls[-1][1]['text'])
        self.text('16.09.1998')
        self.assertTrue(any(c[0]=='sendPhoto' for c in self.api.calls))
        self.assertIn('Test question 2/6',self.api.calls[-1][1]['text'])
        buttons=[b for row in self.api.calls[-1][1]['reply_markup']['inline_keyboard'] for b in row]
        self.assertEqual([b['text'] for b in buttons if b['callback_data'].startswith('program_question:')],list('123456'))
        self.click('program_question:2:1');self.assertIn('Аркан 18',self.api.calls[-1][1]['text'])
    def test_old_buttons_follow_new_birth_and_forget_clears_selection(self):
        self.grant();self.store.set_current_birth(7,'16.09.1998');self.click('program_question:1:1')
        self.text('01.01.2000');self.click('program_question:1:1')
        self.assertIn('Аркан 2',self.api.calls[-1][1]['text']);self.assertIn('01.01.2000',self.api.calls[-1][1]['text'])
        self.store.forget_birth(7);self.assertIsNone(self.store.program_selection(7))
    def test_invalid_callbacks_ignored(self):
        self.grant()
        for route in ('program:0','program:22','program:abc','program_question:1:0','program_question:1:7','program_question:22:1','program_question:1:1:2'):
            self.click(route)
        self.assertFalse(any(c[0]=='sendPhoto' for c in self.api.calls))
    def test_bold_utf16_offsets(self):
        value='Програма 1 · Test\n\nПитання 1 · Test\n\nВідповідь. Test\n\nПозитивні прояви. Test'
        result=bot.instagram_nickname_link('sendMessage',{'text':value})
        self.assertEqual(len(result['entities']),4)

if __name__=='__main__':unittest.main()
