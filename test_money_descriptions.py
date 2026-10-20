import base64
import hashlib
import json
import lzma
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from money_catalog import read_money_catalog, money_description
from catalog import CONTACTS
from payments import Store, Prices
from bot import handle
from test_payments import Fake, callback
from test_invitations import message


def fixture():
    return [dict(number=i,title=f'Тема {i}',directions=f'Напрямки {i}',focus=f'Акцент {i}')
            for i in range(1,23)]


def encoded(entries):
    raw=json.dumps(entries,ensure_ascii=False).encode()
    return {'MONEY_XZ_PARTS':'1','MONEY_XZ_B64_1':base64.b64encode(lzma.compress(raw)).decode(),
            'MONEY_SHA256':hashlib.sha256(raw).hexdigest()}


class MoneyCatalogTests(unittest.TestCase):
    def tearDown(self): read_money_catalog.cache_clear()
    def test_all_22_descriptions_and_contacts(self):
        with patch.dict(os.environ,encoded(fixture())):
            read_money_catalog.cache_clear()
            for i in range(1,23):
                text=money_description(i)
                self.assertIn(f'Аркан {i} · Тема {i}',text)
                self.assertIn(f'Напрямки {i}',text)
                self.assertIn(f'Ваш акцент. Акцент {i}',text)
                self.assertIn(CONTACTS,text)
    def test_invalid_catalog_fails_closed(self):
        duplicate=fixture(); duplicate[-1]['number']=1
        empty=fixture(); empty[0]['directions']=''
        corrupt=encoded(fixture()); corrupt['MONEY_SHA256']='bad'
        for env in [encoded(duplicate),encoded(empty),encoded(fixture()[:-1]),corrupt]:
            with patch.dict(os.environ,env):
                read_money_catalog.cache_clear()
                with self.assertRaises(ValueError): read_money_catalog()


class MoneyReadingFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
        self.loader=patch('money_catalog.read_money_catalog',return_value={e['number']:e for e in fixture()})
        self.loader.start()
    def tearDown(self):
        self.loader.stop(); self.store.close(); self.temp.cleanup()
    def activate(self):
        invite,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
        return invite
    def test_correct_reading_follows_date_and_name_changes(self):
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        handle(self.api,message('/money'),self.store,self.prices)
        handle(self.api,message('Надія'),self.store,self.prices)
        self.assertIn('Аркан 1 · Тема 1',self.api.calls[-1][1]['text'])
        self.assertNotIn('готується',self.api.calls[-1][1]['text'])
        handle(self.api,message('15.03.1989'),self.store,self.prices)
        handle(self.api,message('Ірина'),self.store,self.prices)
        self.assertIn('Аркан 6 · Тема 6',self.api.calls[-1][1]['text'])
    def test_public_expired_revoked_and_other_users_never_load(self):
        with patch('bot.money_description') as private:
            handle(self.api,message('/money'),self.store,self.prices)
            private.assert_not_called()
            invite=self.activate(); self.store.set_current_birth(7,'16.09.1998')
            self.store.set_money_name(7,'Надія'); self.store.set_section(7,'money')
            handle(self.api,callback('section:money',user=8),self.store,self.prices)
            private.assert_not_called()
            with patch('payments.time.time',return_value=self.store.membership_until(7)):
                handle(self.api,callback('section:money'),self.store,self.prices)
                private.assert_not_called()
            self.store.revoke_invitation(99,invite)
            handle(self.api,callback('section:money'),self.store,self.prices)
            private.assert_not_called()
    def test_catalog_failure_preserves_result_without_private_error(self):
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        self.store.set_money_name(7,'Надія')
        with patch('bot.money_description',side_effect=ValueError('private details')):
            handle(self.api,callback('section:money'),self.store,self.prices)
        text=self.api.calls[-1][1]['text']
        self.assertIn('Ваш аркан грошового призначення: 1.',text)
        self.assertIn('тимчасово недоступні',text)
        self.assertNotIn('private details',text)


if __name__=='__main__': unittest.main()
