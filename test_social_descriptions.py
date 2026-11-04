"""Private social catalog and live membership boundaries; synthetic content only."""
import base64,hashlib,json,lzma,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_compatibility
import bot
from catalog import chunks
from social_catalog import read_social_catalog,social_description
from payments import Store,Prices
from test_payments import Fake,callback
from test_invitations import message


def fixture():
    data={'intro':'🌍 СОЦІАЛЬНЕ ПРИЗНАЧЕННЯ\n\nPrivate test introduction',
          'entries':{str(n):{'heading':f'{n} ЕНЕРГІЯ · Test {n}','text':f'Private reading {n}\n\n🔑 Ваш орієнтир: Test action {n}'} for n in range(1,23)}}
    raw=json.dumps(data,ensure_ascii=False).encode()
    return data,{'SOCIAL_XZ_PARTS':'1','SOCIAL_SHA256':hashlib.sha256(raw).hexdigest(),
                 'SOCIAL_XZ_B64_1':base64.b64encode(lzma.compress(raw)).decode()}


class SocialDescriptions(unittest.TestCase):
    def setUp(self):
        self.data,env=fixture();self.env=patch.dict(os.environ,env);self.env.start();read_social_catalog.cache_clear()
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db');self.api=Fake();self.prices=Prices('','')
    def tearDown(self):
        read_social_catalog.cache_clear();self.env.stop();self.store.close();self.temp.cleanup()
    def grant(self,tier='full'):
        iid,token=self.store.create_invitation(99,'+380991234567',tier=tier)
        self.store.begin_invitation(7,token);self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'});return iid
    def click(self,data):bot.handle(self.api,callback(data),self.store,self.prices)
    def test_all_22_energies(self):
        for n in range(1,23):
            text=social_description(n)
            self.assertIn(f'{n} ЕНЕРГІЯ · Test {n}',text);self.assertIn(f'Private reading {n}',text)
            self.assertEqual(text.count('🔑 Ваш орієнтир:'),1)
        for n in (0,23,True,'1',None):
            with self.assertRaises(ValueError):social_description(n)
    def test_invalid_checksum_fails_closed(self):
        with patch.dict(os.environ,{'SOCIAL_SHA256':'bad'}):
            with self.assertRaises(ValueError):read_social_catalog()
    def test_incomplete_catalog_fails_closed(self):
        self.data['entries'].pop('22');raw=json.dumps(self.data).encode()
        with patch.dict(os.environ,{'SOCIAL_SHA256':hashlib.sha256(raw).hexdigest(),'SOCIAL_XZ_B64_1':base64.b64encode(lzma.compress(raw)).decode()}):
            with self.assertRaises(ValueError):read_social_catalog()
    def test_public_never_loads_private_description(self):
        self.store.set_current_birth(7,'16.09.1998')
        with patch('bot.social_description',side_effect=AssertionError('Private reading accessed')):
            self.click('section:social')
        text=self.api.calls[-1][1]['text'];self.assertIn('Ваш аркан: 21.',text);self.assertIn('🔒 Опис закритий',text)
        self.assertNotIn('Private',text)
    def test_full_and_pro_get_right_description(self):
        self.grant();self.store.set_current_birth(7,'16.09.1998');self.click('section:social')
        self.assertIn('Private reading 21',self.api.calls[-1][1]['text'])
        self.assertNotIn('готується',self.api.calls[-1][1]['text'])
        self.grant('pro');self.click('section:social');self.assertIn('Private reading 21',self.api.calls[-1][1]['text'])
    def test_expired_and_revoked_access_are_rechecked(self):
        iid=self.grant();self.store.set_current_birth(7,'16.09.1998')
        with patch('bot.time.time',return_value=self.store.membership_until(7)):
            self.click('locked:social');self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
        self.store.revoke_invitation(99,iid);self.click('section:social');self.assertNotIn('Private',self.api.calls[-1][1]['text'])
    def test_changed_birth_and_navigation(self):
        self.grant();self.store.set_section(7,'social')
        bot.handle(self.api,message('02.01.1990'),self.store,self.prices)
        self.assertIn('Private reading 22',self.api.calls[-1][1]['text'])
        bot.handle(self.api,message('03.01.1990'),self.store,self.prices)
        self.assertIn('1 ЕНЕРГІЯ · Test 1',self.api.calls[-1][1]['text'])
        self.assertIn('reply_markup',self.api.calls[-1][1])
    def test_bold_utf16_offsets_and_contact_link(self):
        value=social_description(22)+'\n\n'+bot.INSTAGRAM_URL
        result=bot.instagram_nickname_link('sendMessage',{'text':value})
        bold=[value for entity in result['entities'] if entity['type']=='bold'
              for value in [result['text'].encode('utf-16-le')[2*entity['offset']:2*(entity['offset']+entity['length'])].decode('utf-16-le')]]
        self.assertEqual(len(bold),3);self.assertEqual(bold[0],'🌍 СОЦІАЛЬНЕ ПРИЗНАЧЕННЯ')
        self.assertTrue(bold[1].startswith('22 ЕНЕРГІЯ'));self.assertTrue(bold[2].startswith('🔑 Ваш орієнтир:'))
        self.assertTrue(any(e['type']=='text_link' for e in result['entities']))
    def test_long_text_is_split_safely(self):
        with patch('bot.social_description',return_value='Довгий опис. '*800):
            self.grant();self.store.set_current_birth(7,'16.09.1998');self.click('section:social')
        messages=[data for method,data,file in self.api.calls if method=='sendMessage']
        self.assertGreater(len(messages),1)
        self.assertTrue(all(len(m['text'].encode('utf-16-le'))//2<=3900 for m in messages))
        self.assertTrue('reply_markup' in messages[-1]);self.assertFalse(any('reply_markup' in m for m in messages[:-1]))

if __name__=='__main__':unittest.main()
