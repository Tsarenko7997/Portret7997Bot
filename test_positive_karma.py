import base64
import hashlib
import json
import lzma
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bot import handle
from catalog import chunks
from karma_catalog import read_positive_karma_catalog, positive_description
from payments import Store, Prices
from test_payments import Fake, callback

def fixture():
    return [dict(number=n,title=f'Плюсова тема {n}',resource=f'Ресурс {n}',
                 expression=f'Прояви {n}',balance=f'Баланс {n}') for n in range(1,23)]

def encoded(entries):
    raw=json.dumps(entries,ensure_ascii=False).encode()
    return {'KARMA_PLUS_XZ_PARTS':'1',
            'KARMA_PLUS_XZ_B64_1':base64.b64encode(lzma.compress(raw)).decode(),
            'KARMA_PLUS_SHA256':hashlib.sha256(raw).hexdigest()}

class PositiveCatalogTests(unittest.TestCase):
    def tearDown(self): read_positive_karma_catalog.cache_clear()

    def test_all_22_private_entries_and_safe_messages(self):
        with patch.dict(os.environ,encoded(fixture())):
            read_positive_karma_catalog.cache_clear()
            self.assertEqual(set(read_positive_karma_catalog()),set(range(1,23)))
            for n in range(1,23):
                text=positive_description(1,n,'16.09.1998')
                self.assertIn(f'Аркан {n} · Плюсова тема {n}',text)
                self.assertIn('@lakshmi_775',text)
                self.assertNotIn('\u2014',text)
                self.assertTrue(all(len(c.encode('utf-16-le'))//2<=3900 for c in chunks(text)))

    def test_bad_hash_missing_field_and_duplicate_rejected(self):
        bad=encoded(fixture()); bad['KARMA_PLUS_SHA256']='0'*64
        missing=fixture(); missing[0]['resource']=''
        duplicate=fixture(); duplicate[-1]['number']=1
        for variables in [bad,encoded(missing),encoded(duplicate),encoded(fixture()[:-1])]:
            read_positive_karma_catalog.cache_clear()
            with patch.dict(os.environ,variables),self.assertRaises(ValueError):
                read_positive_karma_catalog()

class PositiveFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
        self.loader=patch('karma_catalog.read_positive_karma_catalog',return_value={e['number']:e for e in fixture()})
        self.loader.start()

    def tearDown(self):
        self.loader.stop(); self.store.close(); self.temp.cleanup()

    def activate(self):
        invite,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
        return invite

    def test_positive_buttons_precede_negative_and_use_correct_arcana(self):
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        handle(self.api,callback('section:karma'),self.store,self.prices)
        data=self.api.calls[-1][1]
        buttons=[b for row in data['reply_markup']['inline_keyboard'] for b in row]
        plus=[b for b in buttons if b.get('callback_data','').startswith('karma_plus:')]
        minus=[b for b in buttons if b.get('callback_data','').startswith('karma_minus:')]
        self.assertEqual([b['text'] for b in plus],
                         ['➕ 3','➕ 21','➕ 2','➕ 14','➕ 18'])
        self.assertEqual(len(minus),5)
        self.assertLess(buttons.index(plus[-1]),buttons.index(minus[0]))
        self.assertNotIn('готуються',data['caption'])
        for i,(button,n) in enumerate(zip(plus,[3,21,2,14,18]),1):
            handle(self.api,callback(button['callback_data']),self.store,self.prices)
            text=self.api.calls[-1][1]['text']
            self.assertIn(f'Плюсова карма · Позиція {i}',text)
            self.assertIn(f'Аркан {n} · Плюсова тема {n}',text)

    def test_old_buttons_recompute_positive_not_negative_for_latest_date(self):
        self.activate(); self.store.set_current_birth(7,'01.01.2000')
        handle(self.api,callback('karma_plus:16.09.1998:1'),self.store,self.prices)
        text=self.api.calls[-1][1]['text']
        self.assertIn('01.01.2000',text); self.assertIn('Аркан 2 ·',text)
        self.assertNotIn('16.09.1998',text); self.assertNotIn('Аркан 22 ·',text)
        self.assertEqual(self.store.section(7),'karma')

    def test_public_expired_revoked_and_other_accounts_cannot_load_content(self):
        with patch('bot.positive_description') as private:
            handle(self.api,callback('karma_plus:16.09.1998:1'),self.store,self.prices)
            private.assert_not_called()
            invite=self.activate()
            handle(self.api,callback('karma_plus:16.09.1998:1',user=8),self.store,self.prices)
            private.assert_not_called()
            with patch('payments.time.time',return_value=self.store.membership_until(7)):
                handle(self.api,callback('karma_plus:16.09.1998:1'),self.store,self.prices)
                private.assert_not_called()
                self.assertIn('100 грн',self.api.calls[-1][1]['text'])
            self.store.revoke_invitation(99,invite)
            handle(self.api,callback('karma_plus:16.09.1998:1'),self.store,self.prices)
            private.assert_not_called()

    def test_malformed_callbacks_for_both_rows_do_not_raise_or_read(self):
        self.activate()
        with patch('bot.positive_description') as plus,patch('bot.negative_description') as minus:
            for action in ['karma_plus','karma_minus']:
                for suffix in ['0','6','-1','all','1:22','', '1.5','²']:
                    handle(self.api,callback(f'{action}:16.09.1998:{suffix}'),self.store,self.prices)
            plus.assert_not_called(); minus.assert_not_called()

    def test_positive_failure_does_not_return_negative_text(self):
        self.activate()
        with patch('bot.positive_description',side_effect=ValueError('private details')),patch('bot.negative_description') as minus:
            handle(self.api,callback('karma_plus:16.09.1998:1'),self.store,self.prices)
            minus.assert_not_called()
        self.assertIn('Описи плюсової карми тимчасово недоступні',self.api.calls[-1][1]['text'])
        self.assertNotIn('private details',str(self.api.calls))

if __name__=='__main__': unittest.main()

