import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from portrait import calculate_karma, calculate
from payments import Store, Prices
from bot import handle, main_menu
from render import draw_karma
from test_payments import Fake, callback
from test_invitations import message

class KarmaFormulaTests(unittest.TestCase):
    def test_nadia_example(self):
        self.assertEqual(calculate_karma('16.09.1998'),
                         {'positive':[3,21,2,14,18],'negative':[7,11,4,4,4]})
    def test_first_positive_is_portrait_p4_and_second_uses_p3(self):
        p,_=calculate('28.11.1999')
        result=calculate_karma('28.11.1999')
        self.assertEqual(result['positive'],[p['П4'],12,7,17,9])
        self.assertEqual(result['negative'],[5,22,17,5,5])
    def test_all_zero_differences_become_22(self):
        self.assertEqual(calculate_karma('01.01.1000'),
                         {'positive':[2,2,4,2,10],'negative':[22,22,22,22,22]})
    def test_negative_third_is_difference_not_sum(self):
        self.assertEqual(calculate_karma('01.01.2000')['negative'],[22,1,21,1,1])
    def test_invalid_and_future_dates(self):
        for value in ['31.02.2000','2000-01-01','01.01.9999']:
            with self.assertRaises(ValueError): calculate_karma(value)
    def test_results_stay_in_22_arcana(self):
        for month in range(1,13):
            for day in range(1,29):
                result=calculate_karma(f'{day:02}.{month:02}.1998')
                self.assertTrue(all(1<=n<=22 for numbers in result.values() for n in numbers))

class KarmaFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
    def tearDown(self): self.store.close(); self.temp.cleanup()
    def activate(self,user=7):
        _,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(user,token)
        self.store.redeem_invitation(user,{'user_id':user,'phone_number':'+380991234567'})
    def test_section_and_multiple_dates_for_member(self):
        self.activate()
        handle(self.api,callback('section:karma'),self.store,self.prices)
        for birth in ['16.09.1998','01.01.2000']:
            handle(self.api,message(birth),self.store,self.prices)
            method,data,file=self.api.calls[-1]
            self.assertEqual(method,'sendPhoto')
            self.assertIn('Карма +/− · '+birth,data['caption'])
            self.assertEqual(file,('photo',draw_karma(calculate_karma(birth)),'karma.png'))
    def test_public_user_cannot_choose_full_karma(self):
        handle(self.api,callback('section:karma'),self.store,self.prices)
        self.assertIn('місячного доступу',self.api.calls[-1][1]['text'])
        self.assertEqual(self.store.section(7),'portrait')
    def test_expiry_between_section_selection_and_date(self):
        self.activate(); handle(self.api,message('/karma'),self.store,self.prices)
        with patch('payments.time.time',return_value=self.store.membership_until(7)):
            handle(self.api,message('16.09.1998'),self.store,self.prices)
            text=self.api.calls[-1][1]['text']
            self.assertIn('100 грн',text); self.assertNotIn('ПП5:',text)
    def test_mode_is_account_scoped_and_survives_restart(self):
        self.activate(); self.store.set_section(7,'karma')
        self.assertEqual(self.store.section(8),'portrait')
        path=self.store.path; self.store.close(); self.store=Store(path)
        self.assertEqual(self.store.section(7),'karma')
        handle(self.api,message('/portrait'),self.store,self.prices)
        self.assertEqual(self.store.section(7),'portrait')
    def test_home_resets_mode_and_menu_marks_karma_ready(self):
        self.activate(); self.store.set_section(7,'karma')
        handle(self.api,message('/menu'),self.store,self.prices)
        self.assertEqual(self.store.section(7),'portrait')
        buttons=[b for row in main_menu()['inline_keyboard'] for b in row]
        karma=next(b for b in buttons if b.get('callback_data')=='section:karma')
        self.assertNotIn('Незабаром',karma['text'])
    def test_portrait_callback_leaves_karma_mode(self):
        self.activate(); self.store.set_section(7,'karma')
        handle(self.api,callback('menu:16.09.1998'),self.store,self.prices)
        self.assertEqual(self.store.section(7),'portrait')
    def test_png_download_requires_current_membership(self):
        self.activate()
        handle(self.api,callback('karma_png:16.09.1998'),self.store,self.prices)
        method,data,file=self.api.calls[-1]
        self.assertEqual(method,'sendDocument'); self.assertEqual(file[2],'karma.png')
        self.api.calls.clear()
        with patch('payments.time.time',return_value=self.store.membership_until(7)):
            handle(self.api,callback('karma_png:16.09.1998'),self.store,self.prices)
        self.assertFalse(any(c[0]=='sendDocument' for c in self.api.calls))
        self.assertIn('100 грн',self.api.calls[-1][1]['text'])
    def test_one_date_is_shared_between_portrait_and_karma(self):
        self.activate()
        handle(self.api,message('16.09.1998'),self.store,self.prices)
        self.assertEqual(self.store.current_birth(7),'16.09.1998')
        handle(self.api,callback('section:karma'),self.store,self.prices)
        self.assertIn('Карма +/− · 16.09.1998',self.api.calls[-1][1]['caption'])
        self.api.calls.clear()
        handle(self.api,callback('section:portrait'),self.store,self.prices)
        photo=next(c for c in self.api.calls if c[0]=='sendPhoto')
        self.assertIn('Ваш портрет · 16.09.1998',photo[1]['caption'])
        self.assertFalse(any('Завантажити PNG' in str(c[1]) for c in self.api.calls))
    def test_new_date_updates_old_position_buttons(self):
        self.activate()
        handle(self.api,message('16.09.1998'),self.store,self.prices)
        handle(self.api,message('01.01.2000'),self.store,self.prices)
        handle(self.api,callback('position:16.09.1998:21'),self.store,self.prices)
        self.assertIn('01.01.2000',self.api.calls[-1][1]['text'])
        self.assertNotIn('16.09.1998',self.api.calls[-1][1]['text'])
    def test_current_date_is_private_persistent_and_invalid_input_keeps_it(self):
        self.store.set_current_birth(7,'16.09.1998')
        self.assertIsNone(self.store.current_birth(8))
        handle(self.api,message('31.02.2000'),self.store,self.prices)
        self.assertEqual(self.store.current_birth(7),'16.09.1998')
        path=self.store.path; self.store.close(); self.store=Store(path)
        self.assertEqual(self.store.current_birth(7),'16.09.1998')
        handle(self.api,message('/forgetdate'),self.store,self.prices)
        self.assertIsNone(self.store.current_birth(7))
    def test_cached_date_never_bypasses_karma_access_check(self):
        self.store.set_current_birth(7,'16.09.1998')
        handle(self.api,callback('section:karma'),self.store,self.prices)
        self.assertFalse(any(c[0]=='sendPhoto' for c in self.api.calls))
        self.assertIn('місячного доступу',self.api.calls[-1][1]['text'])
    def test_karma_buttons_have_no_png_download(self):
        self.activate(); self.store.set_current_birth(7,'16.09.1998')
        handle(self.api,message('/karma'),self.store,self.prices)
        data=self.api.calls[-1][1]
        self.assertNotIn('Завантажити PNG',str(data))

if __name__=='__main__': unittest.main()
