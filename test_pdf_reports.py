"""Personal report scope and access, using synthetic dates and readings."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import test_compatibility
import bot
from payments import Prices, Store
from pdf_reports import forecast_periods, unique_karma
from test_invitations import message
from test_payments import Fake, callback


class PDFReportsTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'db')
        self.api=Fake()
        self.prices=Prices('','')
        self.birth='22.01.1980'

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def grant(self,tier):
        _,token=self.store.create_invitation(99,'+380991234567',tier=tier)
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})

    def handle(self,event):
        bot.handle(self.api,event,self.store,self.prices)

    def test_report_scope_and_year_boundary(self):
        periods=forecast_periods(self.birth,date(2026,12,31))
        self.assertEqual([(period,kind,slot) for period,kind,_,slot in periods],
                         [('2026','year',1),('2026','year',2),('12.2026','month',1),('01.2027','month',1)])
        self.assertEqual(unique_karma([7,7,12,7,22,12]),(7,12,22))

    def test_locked_routes_do_not_generate_or_ask_for_personal_data(self):
        with patch.object(bot,'build_full_pdf') as full,patch.object(bot,'build_programs_pdf') as pro:
            for kind in ('full','pro'):
                self.handle(callback('pdf:'+kind))
                self.assertIn('🔒',self.api.calls[-1][1]['text'])
            self.grant('full')
            self.handle(callback('pdf:pro'))
            self.assertIn('🔒',self.api.calls[-1][1]['text'])
        full.assert_not_called()
        pro.assert_not_called()

    def test_full_prompts_for_date_then_name_and_reuses_saved_name(self):
        self.grant('full')
        with patch.object(bot,'build_full_pdf',return_value=b'%PDF-full') as build:
            self.handle(callback('pdf:full'))
            self.assertIn('Надішліть дату',self.api.calls[-1][1]['text'])
            self.handle(message(self.birth))
            self.assertIn('надішліть лише ім’я',self.api.calls[-1][1]['text'])
            self.handle(message('Надія'))
            self.assertEqual(self.api.calls[-1][0],'sendDocument')
            self.assertEqual(self.api.calls[-1][2][1],b'%PDF-full')
            self.assertTrue(self.api.calls[-1][2][2].endswith('.pdf'))
            self.handle(callback('pdf:full'))
            self.assertEqual(build.call_count,2)
            self.assertEqual(build.call_args.args[:2],(self.birth,'Надія'))

    def test_pro_can_export_both_files_and_programs_do_not_need_name(self):
        self.grant('pro')
        self.store.set_current_birth(7,self.birth)
        with patch.object(bot,'build_programs_pdf',return_value=b'%PDF-pro') as build:
            self.handle(callback('pdf:pro'))
        build.assert_called_once_with(self.birth)
        self.assertEqual(self.api.calls[-1][2][1],b'%PDF-pro')
        self.store.set_money_name(7,'Надія')
        with patch.object(bot,'build_full_pdf',return_value=b'%PDF-full'):
            self.handle(callback('pdf:full'))
        self.assertEqual(self.api.calls[-1][2][1],b'%PDF-full')

    def test_expiration_while_waiting_or_rendering_blocks_delivery(self):
        self.grant('full')
        self.store.set_current_birth(7,self.birth)
        self.handle(callback('pdf:full'))
        with patch('bot.time.time',return_value=self.store.membership_until(7)):
            self.handle(message('Надія'))
        self.assertIsNone(self.store.money_name(7))
        self.store.set_money_name(7,'Надія')
        with patch.object(bot,'has_full_access',side_effect=[True,False]),patch.object(
                bot,'build_full_pdf',return_value=b'%PDF-full'):
            self.handle(callback('pdf:full'))
        self.assertFalse(any(method=='sendDocument' for method,_,_ in self.api.calls))
