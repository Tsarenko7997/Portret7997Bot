import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from portrait import calculate_forecast
from payments import Store, Prices
from bot import handle, main_menu, instagram_nickname_link
from test_payments import Fake, callback
from test_invitations import message


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
    def tearDown(self):
        self.store.close(); self.temp.cleanup()
    def test_owner_formula_examples(self):
        rows=calculate_forecast('15.03.1989','year',date(2026,10,23))
        self.assertEqual(next(r for r in rows if r[0]=='2024'),('2024',4,22))
        self.assertEqual(calculate_forecast('16.09.1998','year',date(2026,10,23))[3],('2026',13,9))
        self.assertEqual(calculate_forecast('16.09.1998','month',date(2026,10,23))[6],('10.2026',14))
        self.assertEqual(calculate_forecast('16.09.1998','day',date(2026,10,23))[5],('23.10.2026',15))
    def test_windows_cross_year_and_leap_day(self):
        years=calculate_forecast('16.09.1998','year',date(2026,10,23))
        self.assertEqual((len(years),years[0][0],years[-1][0]),(10,'2023','2032'))
        months=calculate_forecast('16.09.1998','month',date(2026,1,31))
        self.assertEqual((len(months),months[0][0],months[6][0],months[-1][0]),
                         (24,'07.2025','01.2026','06.2027'))
        days=calculate_forecast('16.09.1998','day',date(2024,2,29))
        self.assertEqual((len(days),days[0][0],days[5][0],days[-1][0]),
                         (31,'24.02.2024','29.02.2024','25.03.2024'))
        self.assertEqual(len(set(r[0] for r in days)),31)
    def test_reduction_and_validation(self):
        # Day 31 becomes П1=9; 9+12+10=31 => 9.
        self.assertEqual(calculate_forecast('31.12.1999','month',date(2026,12,1))[6],('12.2026',9))
        for section in ('year','month','day'):
            rows=calculate_forecast('29.12.1999',section,date(2026,12,31))
            self.assertTrue(all(1<=number<=22 for row in rows for number in row[1:]))
            with self.assertRaises(ValueError):
                calculate_forecast('31.02.1998',section,date(2026,10,23))
        with self.assertRaises(ValueError):
            calculate_forecast('16.09.1998','unknown',date(2026,10,23))
    def test_navigation_new_birth_and_public_lock(self):
        self.store.set_current_birth(7,'16.09.1998')
        for section in ('year','month','day'):
            handle(self.api,callback('section:'+section),self.store,self.prices)
            data=self.api.calls[-1][1]
            self.assertIn('16.09.1998',data['text'])
            self.assertIn('🔒 Опис закритий',data['text'])
            self.assertIn('поточний період',data['text'])
            self.assertLess(len(instagram_nickname_link('sendMessage',data)['text'].encode('utf-16-le'))//2,4096)
            self.assertEqual(self.store.section(7),section)
        handle(self.api,message('15.03.1989'),self.store,self.prices)
        self.assertIn('Прогноз на день · 15.03.1989',self.api.calls[-1][1]['text'])
        handle(self.api,message('31.02.1998'),self.store,self.prices)
        self.assertEqual(self.store.current_birth(7),'15.03.1989')
        handle(self.api,callback('locked:day'),self.store,self.prices)
        self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
        buttons=[b for row in main_menu()['inline_keyboard'] for b in row]
        self.assertEqual(next(b['text'] for b in buttons if b.get('callback_data')=='section:day'),'📆 Прогноз на день')
        self.assertNotIn('Незабаром',str(buttons))
        self.assertEqual(self.store.section(8),'portrait')
    def test_kyiv_date_and_access_expiry(self):
        class Midnight(datetime):
            @classmethod
            def now(cls,tz=None):
                return datetime(2026,12,31,22,30,tzinfo=timezone.utc).astimezone(tz)
        _,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
        self.store.set_current_birth(7,'16.09.1998')
        with patch('bot.datetime',Midnight):
            handle(self.api,message('/day'),self.store,self.prices)
        data=self.api.calls[-1][1]
        self.assertIn('01.01.2027 12 ← поточний період',data['text'])
        self.assertIn('Детальні описи прогнозів готуються',data['text'])
        self.assertNotIn('🔒',data['text'])
        with patch('payments.time.time',return_value=self.store.membership_until(7)):
            handle(self.api,message('/day'),self.store,self.prices)
        self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
    def test_missing_birth_prompts_and_persists_forecast(self):
        for section in ('year','month','day'):
            handle(self.api,message('/'+section),self.store,self.prices)
            self.assertIn('Надішліть дату народження',self.api.calls[-1][1]['text'])
            self.assertEqual(self.store.section(7),section)
        path=self.store.path; self.store.close(); self.store=Store(path)
        self.assertEqual(self.store.section(7),'day')


if __name__=='__main__': unittest.main()
