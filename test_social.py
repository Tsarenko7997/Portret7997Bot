import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from portrait import calculate_social
from payments import Store, Prices
from bot import handle, main_menu
from test_payments import Fake, callback
from test_invitations import message

class SocialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
    def tearDown(self): self.store.close(); self.temp.cleanup()
    def activate(self):
        _,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
    def test_formula_boundaries_and_full_unreduced_date_digits(self):
        for birth,expected in [('16.09.1998',21),('28.11.1999',18),
                               ('02.01.1990',22),('03.01.1990',1),('29.09.1999',4)]:
            self.assertEqual(calculate_social(birth),expected)
        for birth in ['31.02.2000','2000-01-01','01.01.9999']:
            with self.assertRaises(ValueError): calculate_social(birth)
    def test_cached_date_and_new_date_use_social_section(self):
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        handle(self.api,callback('section:social'),self.store,self.prices)
        self.assertIn('Ваш аркан: 21.',self.api.calls[-1][1]['text'])
        handle(self.api,message('28.11.1999'),self.store,self.prices)
        self.assertIn('Ваш аркан: 18.',self.api.calls[-1][1]['text'])
        self.assertEqual(self.store.current_birth(7),'28.11.1999')
        self.assertEqual(self.store.section(7),'social')
        handle(self.api,callback('section:karma'),self.store,self.prices)
        self.assertIn('28.11.1999',self.api.calls[-1][1]['caption'])
    def test_public_and_expired_users_get_only_numeric_social(self):
        handle(self.api,message('/social'),self.store,self.prices)
        self.assertIn('Розрахунок доступний усім',self.api.calls[-1][1]['text'])
        self.activate(); handle(self.api,message('/social'),self.store,self.prices)
        with patch('payments.time.time',return_value=self.store.membership_until(7)):
            handle(self.api,message('16.09.1998'),self.store,self.prices)
            self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
            self.assertIn('Ваш аркан: 21.',self.api.calls[-1][1]['text'])

    def test_section_persists_and_is_private_to_account(self):
        self.store.set_section(7,'social'); path=self.store.path
        self.store.close(); self.store=Store(path)
        self.assertEqual(self.store.section(7),'social')
        self.assertEqual(self.store.section(8),'portrait')
        self.activate(); handle(self.api,message('16.09.1998'),self.store,self.prices)
        handle(self.api,message('31.02.2000'),self.store,self.prices)
        self.assertEqual(self.store.current_birth(7),'16.09.1998')
    def test_menu_exposes_numerical_social_section(self):
        buttons=[b for row in main_menu()['inline_keyboard'] for b in row]
        social=next(b for b in buttons if b.get('callback_data')=='section:social')
        self.assertEqual(social['text'],'👫 Соціальне призначення')

if __name__=='__main__': unittest.main()

