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
from karma_catalog import read_karma_catalog, negative_description
from payments import Store, Prices
from test_payments import Fake, callback

def fixture():
    return [dict(number=n, title=f'Тема {n}', theme=f'Сюжет {n}',
                 problems=f'Труднощі {n}', blocks=f'Блоки {n}', positive=f'Ресурс {n}')
            for n in range(1,23)]

def encoded(entries):
    raw = json.dumps(entries, ensure_ascii=False).encode()
    return {'KARMA_MINUS_XZ_PARTS':'1',
            'KARMA_MINUS_XZ_B64_1':base64.b64encode(lzma.compress(raw)).decode(),
            'KARMA_MINUS_SHA256':hashlib.sha256(raw).hexdigest()}

class KarmaCatalogTests(unittest.TestCase):
    def tearDown(self):
        read_karma_catalog.cache_clear()

    def test_private_encoded_catalog_and_all_22_descriptions(self):
        with patch.dict(os.environ,encoded(fixture())):
            read_karma_catalog.cache_clear()
            self.assertEqual(set(read_karma_catalog()),set(range(1,23)))
            for n in range(1,23):
                text=negative_description(1,n,'16.09.1998')
                self.assertIn(f'Аркан {n} · Тема {n}',text)
                self.assertIn('@lakshmi_775',text)
                self.assertNotIn('\u2014',text)
                self.assertTrue(all(len(c.encode('utf-16-le'))//2<=3900 for c in chunks(text)))

    def test_corrupt_and_incomplete_catalogs_fail_closed(self):
        bad_cases=[]
        bad=encoded(fixture()); bad['KARMA_MINUS_SHA256']='0'*64; bad_cases.append(bad)
        bad_cases.append(encoded(fixture()[:-1]))
        duplicate=fixture(); duplicate[-1]['number']=1; bad_cases.append(encoded(duplicate))
        missing=fixture(); missing[0]['theme']=''; bad_cases.append(encoded(missing))
        for variables in bad_cases:
            with self.subTest(sha=variables['KARMA_MINUS_SHA256']):
                read_karma_catalog.cache_clear()
                with patch.dict(os.environ,variables),self.assertRaises(ValueError):
                    read_karma_catalog()

class KarmaDescriptionFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
        self.catalog_patch=patch('karma_catalog.read_karma_catalog',return_value={e['number']:e for e in fixture()})
        self.catalog_patch.start()

    def tearDown(self):
        self.catalog_patch.stop(); self.store.close(); self.temp.cleanup()

    def activate(self):
        invite,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
        return invite

    def test_five_buttons_and_correct_position_to_arcana_mapping(self):
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        handle(self.api,callback('section:karma'),self.store,self.prices)
        data=self.api.calls[-1][1]
        buttons=[b for row in data['reply_markup']['inline_keyboard'] for b in row
                 if b.get('callback_data','').startswith('karma_minus:')]
        self.assertEqual([b['text'] for b in buttons],
                         ['➖ 1 · 7','➖ 2 · 11','➖ 3 · 4','➖ 4 · 4','➖ 5 · 4'])
        for i,(button,arcanum) in enumerate(zip(buttons,[7,11,4,4,4]),1):
            handle(self.api,callback(button['callback_data']),self.store,self.prices)
            text=self.api.calls[-1][1]['text']
            self.assertIn(f'Позиція {i}',text)
            self.assertIn(f'Аркан {arcanum} · Тема {arcanum}',text)

    def test_old_buttons_recompute_for_current_date(self):
        self.activate(); self.store.set_current_birth(7,'01.01.2000')
        handle(self.api,callback('karma_minus:16.09.1998:1'),self.store,self.prices)
        text=self.api.calls[-1][1]['text']
        self.assertIn('01.01.2000',text); self.assertIn('Аркан 22 ·',text)
        self.assertNotIn('16.09.1998',text)
        self.assertEqual(self.store.section(7),'karma')

    def test_public_expired_and_revoked_users_never_read_private_content(self):
        with patch('bot.negative_description') as private:
            handle(self.api,callback('karma_minus:16.09.1998:1'),self.store,self.prices)
            private.assert_not_called()
            invite=self.activate()
            with patch('payments.time.time',return_value=self.store.membership_until(7)):
                handle(self.api,callback('karma_minus:16.09.1998:1'),self.store,self.prices)
                private.assert_not_called()
                self.assertIn('100 грн',self.api.calls[-1][1]['text'])
            self.store.revoke_invitation(99,invite)
            handle(self.api,callback('karma_minus:16.09.1998:1'),self.store,self.prices)
            private.assert_not_called()

    def test_invalid_callbacks_do_not_load_content(self):
        self.activate()
        with patch('bot.negative_description') as private:
            for suffix in ['0','6','-1','all','1:22','', '1.5']:
                handle(self.api,callback('karma_minus:16.09.1998:'+suffix),self.store,self.prices)
            private.assert_not_called()

    def test_another_sender_cannot_use_the_account(self):
        self.activate()
        update=callback('karma_minus:16.09.1998:1')
        update['callback_query']['from']['id']=8
        with patch('bot.negative_description') as private:
            handle(self.api,update,self.store,self.prices)
            private.assert_not_called()

    def test_catalog_failure_is_reported_without_leaking_content(self):
        self.activate()
        with patch('bot.negative_description',side_effect=ValueError('private details')):
            handle(self.api,callback('karma_minus:16.09.1998:1'),self.store,self.prices)
        self.assertIn('тимчасово недоступні',self.api.calls[-1][1]['text'])
        self.assertNotIn('private details',str(self.api.calls))

if __name__=='__main__':
    unittest.main()

