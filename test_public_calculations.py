import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bot import handle, instagram_nickname_link
from payments import Store, Prices
from test_payments import Fake, callback
from test_invitations import message


class PublicCalculationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
        self.store.set_current_birth(7,'16.09.1998')
    def tearDown(self):
        self.store.close(); self.temp.cleanup()
    def activate(self):
        invite,token=self.store.create_invitation(99,'+380991234567')
        self.store.begin_invitation(7,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':'+380991234567'})
        return invite
    def test_public_karma_has_ten_locked_numeric_buttons_and_safe_caption(self):
        handle(self.api,callback('section:karma'),self.store,self.prices)
        method,data,_=self.api.calls[-1]
        buttons=[b for row in data['reply_markup']['inline_keyboard'] for b in row]
        karma=[b for b in buttons if b.get('callback_data','').startswith(('karma_plus:','karma_minus:'))]
        self.assertEqual(len(karma),10)
        self.assertTrue(all(b['text'].startswith('🔒 ') for b in karma))
        self.assertEqual(karma[0]['text'],'🔒 Плюс 1 · 3')
        caption=instagram_nickname_link(method,data)['caption']
        self.assertLessEqual(len(caption.encode('utf-16-le'))//2,1024)
    def test_public_and_old_callbacks_never_load_private_karma(self):
        with patch('bot.positive_description') as plus,patch('bot.negative_description') as minus:
            for action in ('karma_plus','karma_minus'):
                handle(self.api,callback(action+':16.09.1998:1'),self.store,self.prices)
                self.assertIn('Ваш аркан:',self.api.calls[-1][1]['text'])
                self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
            invite=self.activate(); self.store.revoke_invitation(99,invite)
            handle(self.api,callback('karma_plus:16.09.1998:1'),self.store,self.prices)
            plus.assert_not_called(); minus.assert_not_called()
    def test_money_numeric_result_change_name_and_lock_callback(self):
        with patch('bot.money_description') as private:
            handle(self.api,callback('section:money'),self.store,self.prices)
            handle(self.api,message('Надія'),self.store,self.prices)
            self.assertIn('Ваш аркан грошового призначення: 1.',self.api.calls[-1][1]['text'])
            self.assertIn('locked:money',str(self.api.calls[-1][1]['reply_markup']))
            handle(self.api,callback('locked:money'),self.store,self.prices)
            self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
            handle(self.api,callback('money_name'),self.store,self.prices)
            self.assertIsNone(self.store.money_name(7))
            handle(self.api,message('Ірина'),self.store,self.prices)
            self.assertEqual(self.store.money_name(7),'Ірина')
            private.assert_not_called()
    def test_active_member_opens_private_reading_and_expiry_closes_it(self):
        self.activate(); self.store.set_money_name(7,'Надія')
        with patch('bot.money_description',return_value='PRIVATE MONEY') as private:
            handle(self.api,callback('locked:money'),self.store,self.prices)
            private.assert_called_once_with(1)
            self.assertIn('PRIVATE MONEY',self.api.calls[-1][1]['text'])
            self.assertNotIn('🔒',str(self.api.calls[-1][1]))
            private.reset_mock()
            with patch('payments.time.time',return_value=self.store.membership_until(7)):
                handle(self.api,callback('section:money'),self.store,self.prices)
                private.assert_not_called()
                self.assertNotIn('PRIVATE MONEY',self.api.calls[-1][1]['text'])
    def test_member_access_does_not_transfer_to_other_accounts(self):
        self.activate(); self.store.set_current_birth(8,'16.09.1998'); self.store.set_money_name(8,'Надія')
        with patch('bot.money_description') as private:
            handle(self.api,callback('section:money',user=8),self.store,self.prices)
            private.assert_not_called()
            self.assertIn('🔒 Опис закритий',self.api.calls[-1][1]['text'])
        self.assertEqual(self.store.owned(8,'16.09.1998'),{21,30})
    def test_free_portrait_positions_remain_only_21_and_30(self):
        self.assertEqual(self.store.owned(7,'16.09.1998'),{21,30})
        handle(self.api,callback('menu:16.09.1998'),self.store,self.prices)
        buttons=[b for row in self.api.calls[-1][1]['reply_markup']['inline_keyboard'] for b in row]
        positions=[b for b in buttons if b.get('callback_data','').startswith('position:')]
        self.assertEqual([int(b['text']) for b in positions if '🔒' not in b['text']],[21,30])


if __name__=='__main__': unittest.main()
