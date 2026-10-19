import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from portrait import calculate_matrix
from render import draw_matrix
from payments import Store, Prices
from bot import handle, main_menu
from test_payments import Fake, callback
from test_invitations import message


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
    def tearDown(self):
        self.store.close(); self.temp.cleanup()
    def activate(self):
        _,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
    def test_both_worksheet_examples_including_constant(self):
        first=calculate_matrix('16.09.1998')
        self.assertEqual(first['numbers'],[43,7,2,41,5])
        self.assertEqual(first['counts'],{1:3,2:1,3:1,4:2,5:1,6:1,7:1,8:1,9:3})
        second=calculate_matrix('20.03.2024')
        self.assertEqual(second['numbers'],[13,4,19,32,5])
        self.assertEqual(second['counts'],{1:2,2:4,3:3,4:2,5:1,6:0,7:0,8:0,9:1})
    def test_boundary_and_fixed_constant_not_day_multiplier(self):
        self.assertEqual(calculate_matrix('31.12.1999')['numbers'],[35,8,2,33,6])
        self.assertEqual(calculate_matrix('01.01.2000')['numbers'],[4,4,19,23,5])
        self.assertEqual(calculate_matrix('28.11.1999')['numbers'],[40,4,2,38,11])
        for value in ['31.02.2000','2000-01-01','01.01.9999']:
            with self.assertRaises(ValueError): calculate_matrix(value)
    def test_cached_date_new_date_and_cross_section(self):
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        handle(self.api,callback('section:matrix'),self.store,self.prices)
        self.assertEqual(self.api.calls[-1][0],'sendPhoto')
        self.assertIn('43 − 2 = 41',self.api.calls[-1][1]['caption'])
        handle(self.api,message('20.03.2024'),self.store,self.prices)
        self.assertIn('13 + 19 = 32',self.api.calls[-1][1]['caption'])
        self.assertEqual(self.store.section(7),'matrix')
        handle(self.api,callback('section:social'),self.store,self.prices)
        self.assertIn('20.03.2024',self.api.calls[-1][1]['text'])
    def test_first_date_invalid_date_and_persistence(self):
        self.activate(); handle(self.api,message('/matrix'),self.store,self.prices)
        self.assertIn('Надішліть дату',self.api.calls[-1][1]['text'])
        handle(self.api,message('16.09.1998'),self.store,self.prices)
        handle(self.api,message('31.02.2000'),self.store,self.prices)
        self.assertEqual(self.store.current_birth(7),'16.09.1998')
        path=self.store.path; self.store.close(); self.store=Store(path)
        self.assertEqual(self.store.section(7),'matrix')
        self.assertEqual(self.store.section(8),'portrait')
    def test_access_checked_on_button_and_new_date(self):
        handle(self.api,message('/matrix'),self.store,self.prices)
        self.assertIn('місячного доступу',self.api.calls[-1][1]['text'])
        self.assertFalse(any(c[0]=='sendPhoto' for c in self.api.calls))
        self.activate(); handle(self.api,message('/matrix'),self.store,self.prices)
        with patch('payments.time.time',return_value=self.store.membership_until(7)):
            handle(self.api,message('16.09.1998'),self.store,self.prices)
            self.assertIn('100 грн',self.api.calls[-1][1]['text'])
            self.assertFalse(any(c[0]=='sendPhoto' for c in self.api.calls))
    def test_ready_menu_and_square_render(self):
        buttons=[b for row in main_menu()['inline_keyboard'] for b in row]
        self.assertEqual(next(b['text'] for b in buttons if b.get('callback_data')=='section:matrix'),'Матриця')
        png=draw_matrix('16.09.1998',calculate_matrix('16.09.1998'))
        with Image.open(BytesIO(png)) as im:
            self.assertEqual(im.size,(1200,1200))
            self.assertEqual(im.format,'PNG')


if __name__=='__main__': unittest.main()
