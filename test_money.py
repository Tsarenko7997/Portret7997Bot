import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from portrait import calculate_money, normalize_money_name, NAME_VALUES
from payments import Store, Prices
from bot import handle, main_menu
from test_payments import Fake, callback
from test_invitations import message

class MoneyFormulaTests(unittest.TestCase):
    def test_author_examples(self):
        self.assertEqual(calculate_money('16.09.1998','Надія'),
                         {'name':'Надія','name_sum':25,'name_arcanum':3,'arcanum':1})
        self.assertEqual(calculate_money('15.03.1989','Ірина'),
                         {'name':'Ірина','name_sum':18,'name_arcanum':18,'arcanum':6})
    def test_table_matches_every_supplied_ukrainian_column(self):
        rows=['АБВГҐДЕЄЖ','ЗИІЇЙКЛМН','ОПРСТУФХЦ','ЧШЩЬЮЯ']
        self.assertEqual(len(NAME_VALUES),33)
        for row in rows:
            self.assertEqual([NAME_VALUES[c] for c in row],list(range(1,len(row)+1)))
    def test_case_compound_names_and_apostrophes(self):
        self.assertEqual(calculate_money('16.09.1998','надія')['arcanum'],1)
        self.assertEqual(normalize_money_name('  Анна-Марія  '),'Анна-Марія')
        for apostrophe in ["'",'’','ʼ']:
            self.assertEqual(calculate_money('16.09.1998','Мар'+apostrophe+'яна')['name_sum'],
                             calculate_money('16.09.1998','Маряна')['name_sum'])
        self.assertEqual(calculate_money('16.09.1998','Ґ')['name_sum'],5)
    def test_invalid_names_dates_and_22_boundary(self):
        for name in ['','---','Nadiia','Надеждаы','Надія123','<Надія>','Н'*101]:
            with self.assertRaises(ValueError): calculate_money('16.09.1998',name)
        with self.assertRaises(ValueError): calculate_money('31.02.2000','Надія')
        self.assertEqual(calculate_money('16.09.1998','ННГ')['name_arcanum'],22)

class MoneyFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
    def tearDown(self): self.store.close(); self.temp.cleanup()
    def activate(self):
        _,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
    def test_date_then_name_and_cached_result(self):
        self.activate(); handle(self.api,message('/money'),self.store,self.prices)
        handle(self.api,message('16.09.1998'),self.store,self.prices)
        self.assertIn('Надішліть лише ім’я',self.api.calls[-1][1]['text'])
        handle(self.api,message('Надія'),self.store,self.prices)
        text=self.api.calls[-1][1]['text']
        self.assertNotIn('Аркан імені',text)
        self.assertIn('Ваш аркан грошового призначення: 1.',text)
        handle(self.api,callback('section:social'),self.store,self.prices)
        self.assertIn('Ваш аркан: 21.',self.api.calls[-1][1]['text'])
        handle(self.api,callback('section:money'),self.store,self.prices)
        self.assertIn('Ім’я: Надія',self.api.calls[-1][1]['text'])
    def test_changing_date_resets_name_and_invalid_input_keeps_it(self):
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        handle(self.api,callback('section:money'),self.store,self.prices)
        handle(self.api,message('Надія'),self.store,self.prices)
        handle(self.api,message('Nadiia'),self.store,self.prices)
        self.assertEqual(self.store.money_name(7),'Надія')
        handle(self.api,message('31.02.2000'),self.store,self.prices)
        self.assertEqual(self.store.current_birth(7),'16.09.1998')
        self.assertEqual(self.store.money_name(7),'Надія')
        handle(self.api,message('15.03.1989'),self.store,self.prices)
        self.assertIsNone(self.store.money_name(7))
        handle(self.api,message('Ірина'),self.store,self.prices)
        self.assertIn('Ваш аркан грошового призначення: 6.',self.api.calls[-1][1]['text'])
    def test_name_is_persistent_account_private_and_can_be_changed_or_forgotten(self):
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        self.store.set_money_name(7,'Надія'); self.store.set_section(7,'money')
        path=self.store.path; self.store.close(); self.store=Store(path)
        self.assertEqual(self.store.money_name(7),'Надія'); self.assertIsNone(self.store.money_name(8))
        handle(self.api,callback('money_name'),self.store,self.prices)
        self.assertIsNone(self.store.money_name(7))
        handle(self.api,message('Ірина'),self.store,self.prices)
        self.assertEqual(self.store.money_name(7),'Ірина')
        handle(self.api,message('/forgetdate'),self.store,self.prices)
        self.assertIsNone(self.store.current_birth(7)); self.assertIsNone(self.store.money_name(7))
    def test_public_expired_and_other_accounts_cannot_compute_or_store_name(self):
        handle(self.api,callback('section:money'),self.store,self.prices)
        self.assertIn('місячного доступу',self.api.calls[-1][1]['text'])
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        handle(self.api,callback('section:money'),self.store,self.prices)
        with patch('payments.time.time',return_value=self.store.membership_until(7)):
            handle(self.api,message('Надія'),self.store,self.prices)
            self.assertIsNone(self.store.money_name(7))
            self.assertIn('100 грн',self.api.calls[-1][1]['text'])
        self.store.set_current_birth(8,'16.09.1998')
        handle(self.api,callback('section:money',user=8),self.store,self.prices)
        self.assertNotIn('Ваш аркан грошового',self.api.calls[-1][1]['text'])
    def test_menu_marks_money_ready(self):
        buttons=[b for row in main_menu()['inline_keyboard'] for b in row]
        self.assertEqual(next(b['text'] for b in buttons if b.get('callback_data')=='section:money'),
                         'Грошове призначення')

if __name__=='__main__': unittest.main()

