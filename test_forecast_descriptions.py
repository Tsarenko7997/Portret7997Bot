import base64
import hashlib
import json
import lzma
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bot import handle, instagram_nickname_link
from catalog import chunks
from forecast_catalog import read_forecast_catalog, forecast_description
from payments import Store, Prices
from test_payments import Fake, callback
from test_position_formatting import entity_text


def fixture():
    def fields(label):
        return {k:label+' '+k for k in ('keywords','general','positive','difficulties')}
    entries=[]
    for n in range(1,23):
        year=fields('year')
        year.update(professional=fields('work'),personal=fields('personal'))
        entries.append(dict(number=n,name=f'Тестова назва {n}',forecasts={
            'year':year,'month':fields('month'),'day':fields('day')}))
    return entries


def encoded(entries):
    raw=json.dumps(entries,ensure_ascii=False).encode()
    return dict(FORECAST_XZ_PARTS='1',FORECAST_XZ_B64_1=base64.b64encode(lzma.compress(raw)).decode(),
                FORECAST_SHA256=hashlib.sha256(raw).hexdigest())


class ForecastCatalogTests(unittest.TestCase):
    def tearDown(self): read_forecast_catalog.cache_clear()
    def test_all_periods_and_year_contexts(self):
        with patch.dict(os.environ,encoded(fixture())):
            read_forecast_catalog.cache_clear()
            self.assertEqual(set(read_forecast_catalog()),set(range(1,23)))
            for n in range(1,23):
                for section,slot,label in [('year',1,'work'),('year',2,'personal'),('month',1,'month'),('day',1,'day')]:
                    text=forecast_description(section,n,slot)
                    self.assertIn(f'Аркан {n} ·',text)
                    self.assertIn(label+' positive',text)
                    rendered=instagram_nickname_link('sendMessage',{'text':'📆\n\n'+text})
                    bold=[entity_text(rendered['text'],e) for e in rendered['entities'] if e['type']=='bold']
                    for heading in ('Ключові слова','Загальний опис','Позитивні події','Можливі труднощі'):
                        self.assertIn(heading,bold)
                    self.assertTrue(all(len(x.encode('utf-16-le'))//2<=3900 for x in chunks(text)))
    def test_rejects_incomplete_duplicate_and_corrupt_content(self):
        missing=fixture();del missing[0]['forecasts']['day']
        duplicate=fixture();duplicate[-1]['number']=1
        focus=fixture();del focus[0]['forecasts']['year']['personal']['general']
        bad=encoded(fixture());bad['FORECAST_SHA256']='0'*64
        for env in [encoded(missing),encoded(duplicate),encoded(focus),encoded(fixture()[:-1]),bad]:
            read_forecast_catalog.cache_clear()
            with patch.dict(os.environ,env),self.assertRaises(ValueError): read_forecast_catalog()


class ForecastFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake();self.prices=Prices('','');self.store.set_current_birth(7,'16.09.1998')
        self.loader=patch('forecast_catalog.read_forecast_catalog',return_value={e['number']:e for e in fixture()})
        self.loader.start()
    def tearDown(self):
        self.loader.stop();self.store.close();self.temp.cleanup()
    def activate(self):
        iid,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
        return iid
    def test_all_buttons_and_telegram_payload_limits(self):
        for active in (False,True):
            if active:self.activate()
            for section,count in [('year',20),('month',24),('day',31)]:
                handle(self.api,callback('section:'+section),self.store,self.prices)
                data=self.api.calls[-1][1]
                buttons=[b for row in data['reply_markup']['inline_keyboard'] for b in row
                         if b.get('callback_data','').startswith('forecast:')]
                self.assertEqual(len(buttons),count)
                self.assertTrue(all(len(b['callback_data'].encode())<=64 for b in buttons))
                self.assertTrue(all(('🔒' in b['text']) != active for b in buttons))
                for b in buttons:
                    handle(self.api,callback(b['callback_data']),self.store,self.prices)
                    text=self.api.calls[-1][1]['text']
                    if active:self.assertIn('Позитивні події.',text)
                    else:self.assertIn('🔒 Опис закритий',text)
    def test_year_slots_and_latest_birth_recalculate(self):
        self.activate()
        for slot,n,label in [('1',13,'work'),('2',9,'personal')]:
            handle(self.api,callback(f'forecast:16.09.1998:year:2026:{slot}'),self.store,self.prices)
            text=self.api.calls[-1][1]['text'];self.assertIn(f'Аркан {n} ·',text);self.assertIn(label+' general',text)
        self.store.set_current_birth(7,'01.01.2000')
        handle(self.api,callback('forecast:16.09.1998:month:10.2026:1'),self.store,self.prices)
        text=self.api.calls[-1][1]['text']
        self.assertIn('01.01.2000',text);self.assertNotIn('16.09.1998',text);self.assertIn('Аркан 21 ·',text)
        self.assertEqual(self.store.section(7),'month')
    def test_public_other_expired_and_revoked_never_load_private_text(self):
        data='forecast:16.09.1998:day:23.10.2026:1'
        with patch('bot.forecast_description') as private:
            handle(self.api,callback(data),self.store,self.prices)
            private.assert_not_called()
            iid=self.activate()
            handle(self.api,callback(data,user=8),self.store,self.prices)
            private.assert_not_called()
            with patch('payments.time.time',return_value=self.store.membership_until(7)):
                handle(self.api,callback(data),self.store,self.prices)
            private.assert_not_called()
            self.store.revoke_invitation(99,iid)
            handle(self.api,callback(data),self.store,self.prices)
            private.assert_not_called()
    def test_invalid_callbacks_and_missing_catalog_are_safe(self):
        self.activate()
        with patch('bot.forecast_description') as private:
            for payload in ['forecast:x:bad:2026:1','forecast:x:day:31.02.2026:1',
                            'forecast:x:year:2026:3','forecast:x:day:23.10.2026:2',
                            'forecast:x:day:23.10.2026:1:extra']:
                handle(self.api,callback(payload),self.store,self.prices)
            private.assert_not_called()
        with patch('bot.forecast_description',side_effect=FileNotFoundError):
            handle(self.api,callback('forecast:x:day:23.10.2026:1'),self.store,self.prices)
            self.assertIn('Опис тимчасово недоступний',self.api.calls[-1][1]['text'])


if __name__=='__main__':unittest.main()
