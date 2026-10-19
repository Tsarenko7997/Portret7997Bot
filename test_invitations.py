import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bot import handle
from payments import Store, Prices, PaymentError, normalize_phone, next_month
from datetime import datetime
from zoneinfo import ZoneInfo
from test_payments import Fake, callback

DATE='16.09.1998'
PHONE='+380991234567'

def message(text='', user=7, **extra):
    return {'message':{'chat':{'id':user,'type':'private'},'from':{'id':user},'text':text,**extra}}

class InvitationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'db'
        self.store=Store(self.path)
        self.api=Fake()
        self.prices=Prices('','')
    def tearDown(self):
        self.store.close(); self.temp.cleanup()
    def invite(self): return self.store.create_invitation(99,PHONE,DATE)
    def redeem(self, token, user=7, phone=PHONE):
        self.store.begin_invitation(user,token)
        return self.store.redeem_invitation(user,{'user_id':user,'phone_number':phone})
    def test_public_only_two_positions(self):
        self.assertEqual(self.store.owned(7,DATE),{21,30})
    def test_account_scoped_unlimited_dates_persistent_access(self):
        iid,token=self.invite(); self.redeem(token)
        self.store.close(); self.store=Store(self.path)
        self.assertEqual(len(self.store.owned(7,DATE)),33)
        self.assertEqual(len(self.store.owned(7,'16.10.1998')),33)
        self.assertEqual(self.store.owned(8,DATE),{21,30})
        self.assertGreater(self.store.membership_until(7),0)
    def test_forwarded_link_wrong_phone_cannot_consume(self):
        iid,token=self.invite()
        with self.assertRaises(PaymentError): self.redeem(token,8,'+380661234567')
        self.assertEqual(self.store.owned(8,DATE),{21,30})
        self.redeem(token)
        with self.assertRaises(PaymentError): self.store.begin_invitation(8,token)
    def test_other_contact_rejected(self):
        iid,token=self.invite(); self.store.begin_invitation(7,token)
        for contact in [{'user_id':8,'phone_number':PHONE},{'phone_number':PHONE}]:
            with self.assertRaises(PaymentError): self.store.redeem_invitation(7,contact)
    def test_second_account_even_with_same_phone_cannot_redeem(self):
        iid,token=self.invite()
        self.store.begin_invitation(7,token); self.store.begin_invitation(8,token)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':PHONE})
        with self.assertRaises(PaymentError): self.store.redeem_invitation(8,{'user_id':8,'phone_number':PHONE})
    def test_activation_expiry_and_reopening_never_restarts_month(self):
        iid,token=self.store.create_invitation(99,PHONE,DATE,now=100)
        with self.assertRaises(PaymentError): self.store.begin_invitation(7,token,now=100+7*86400)
        self.store.begin_invitation(7,token,now=101)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':PHONE},now=102)
        until=self.store.membership_until(7)
        self.assertEqual(until,next_month(102))
        self.assertEqual(self.store.begin_invitation(7,token,now=9999999999),'')
        self.assertEqual(self.store.membership_until(7),until)
    def test_pending_expires(self):
        iid,token=self.invite(); self.store.begin_invitation(7,token,now=100)
        with self.assertRaises(PaymentError): self.store.redeem_invitation(7,{'user_id':7,'phone_number':PHONE},now=701)
    def test_revoked_before_activation(self):
        iid,token=self.invite(); self.store.begin_invitation(7,token)
        self.assertTrue(self.store.revoke_invitation(99,iid))
        with self.assertRaises(PaymentError): self.store.redeem_invitation(7,{'user_id':7,'phone_number':PHONE})
    def test_revoke_removes_grant_and_history(self):
        iid,token=self.invite(); self.redeem(token)
        self.assertFalse(self.store.revoke_invitation(7,iid))
        self.assertTrue(self.store.revoke_invitation(99,iid))
        self.assertEqual(self.store.owned(7,DATE),{21,30}); self.assertEqual(self.store.dates(7),[])
        with self.assertRaises(PaymentError): self.store.begin_invitation(7,token)
    def test_no_plaintext_phone_or_link_token_stored(self):
        iid,token=self.invite()
        dump='\n'.join(self.store.db.iterdump())
        self.assertNotIn(PHONE,dump); self.assertNotIn(token,dump)
    def test_normalization(self):
        self.assertEqual(normalize_phone('380 (99) 123-45-67'),PHONE)
        self.assertEqual(normalize_phone('00380991234567'),PHONE)
        for bad in ['0991234567','x380991234567','+0000000000']:
            with self.assertRaises(PaymentError): normalize_phone(bad)
    def test_invite_needs_no_birth_date(self):
        iid,token=self.store.create_invitation(99,PHONE)
        self.redeem(token)
        self.assertEqual(len(self.store.owned(7,'01.01.2000')),33)
    def test_owner_command_fail_closed(self):
        for owner in ['', '99']:
            with patch.dict('os.environ',{'BOT_OWNER_ID':owner}):
                handle(self.api,message('/invite '+PHONE),self.store,self.prices)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM invitations').fetchone()[0],0)
    def test_owner_can_issue_and_revoke(self):
        class OwnerAPI(Fake):
            def call(self,method,data=None,file=None):
                if method=='getMe': return {'username':'ExampleBot'}
                return super().call(method,data,file)
        api=OwnerAPI()
        with patch.dict('os.environ',{'BOT_OWNER_ID':'99'}):
            handle(api,message('/invite '+PHONE,user=99),self.store,self.prices)
            row=self.store.db.execute('SELECT * FROM invitations').fetchone()
            self.assertIsNotNone(row)
            self.assertIn('https://t.me/ExampleBot?start=gift_',api.calls[-1][1]['text'])
            handle(api,message('/revoke '+row['id'],user=99),self.store,self.prices)
            self.assertIsNotNone(self.store.db.execute('SELECT revoked FROM invitations').fetchone()[0])
    def test_native_contact_flow_unlocks_menu(self):
        iid,token=self.invite()
        handle(self.api,message('/start gift_'+token),self.store,self.prices)
        self.assertTrue(self.api.calls[-1][1]['reply_markup']['keyboard'][0][0]['request_contact'])
        handle(self.api,message(contact={'phone_number':PHONE,'user_id':7}),self.store,self.prices)
        self.assertIn('необмеженої кількості дат',self.api.calls[-1][1]['text'])
        handle(self.api,callback('menu:'+DATE),self.store,self.prices)
        buttons=self.api.calls[-1][1]['reply_markup']['inline_keyboard']
        numbers=[b for r in buttons for b in r if b['callback_data'].startswith('position:')]
        self.assertEqual(len(numbers),33); self.assertTrue(all('🔒' not in b['text'] for b in numbers))
    def test_cancel_and_forwarded_contact_no_access(self):
        iid,token=self.invite(); self.store.begin_invitation(7,token)
        handle(self.api,message(contact={'phone_number':PHONE,'user_id':7},forward_origin={'type':'user'}),self.store,self.prices)
        self.assertEqual(self.store.owned(7,DATE),{21,30})
        handle(self.api,message('/cancel'),self.store,self.prices)
        with self.assertRaises(PaymentError): self.store.redeem_invitation(7,{'phone_number':PHONE,'user_id':7})
    def test_myid_does_not_grant_admin(self):
        handle(self.api,message('/myid'),self.store,self.prices)
        self.assertIn('7',self.api.calls[-1][1]['text'])
        self.assertEqual(self.store.owned(7,DATE),{21,30})
    def test_grant_blocks_payment_for_already_open_content(self):
        iid,token=self.invite(); self.redeem(token)
        with self.assertRaises(PaymentError): self.store.create_order(7,DATE,'all',100)

    def test_expired_access_relocks_every_date_and_old_buttons(self):
        iid,token=self.invite(); self.redeem(token)
        until=self.store.membership_until(7)
        with patch('payments.time.time',return_value=until):
            for birth in [DATE,'01.01.2000','16.10.1998']:
                self.assertEqual(self.store.owned(7,birth),{21,30})
            handle(self.api,callback('position:'+DATE+':22'),self.store,self.prices)
            text=self.api.calls[-1][1]['text']
            self.assertIn('100 грн',text)
            self.assertIn('місяць повного доступу завершився',text)
            self.assertIn('@Lakshmi_775',text)
            self.assertIn('Ваш Telegram ID: 7',text)
    def test_reentry_shows_expired_prompt(self):
        iid,token=self.invite(); self.redeem(token)
        with patch('payments.time.time',return_value=self.store.membership_until(7)):
            handle(self.api,message('/start'),self.store,self.prices)
            self.assertIn('100 грн',self.api.calls[-1][1]['text'])
            handle(self.api,message('/access'),self.store,self.prices)
            self.assertIn('100 грн',self.api.calls[-1][1]['text'])
    def test_second_link_does_not_restart_free_month(self):
        iid,token=self.invite(); self.redeem(token)
        until=self.store.membership_until(7)
        iid2,token2=self.invite()
        self.store.begin_invitation(7,token2)
        with self.assertRaises(PaymentError):
            self.store.redeem_invitation(7,{'user_id':7,'phone_number':PHONE})
        self.assertEqual(self.store.membership_until(7),until)
    def test_calendar_month_clamps_day_and_preserves_kyiv_time(self):
        tz=ZoneInfo('Europe/Kyiv')
        for start,end in [((2026,1,31,15),(2026,2,28,15)),
                          ((2024,1,31,15),(2024,2,29,15)),
                          ((2026,12,19,12),(2027,1,19,12)),
                          ((2026,3,19,12),(2026,4,19,12))]:
            self.assertEqual(next_month(int(datetime(*start,tzinfo=tz).timestamp())),
                             int(datetime(*end,tzinfo=tz).timestamp()))
    def test_legacy_invite_migration_keeps_activation_start(self):
        iid,token=self.invite(); self.redeem(token)
        redeemed=self.store.db.execute('SELECT redeemed FROM invitations WHERE id=?',(iid,)).fetchone()[0]
        self.store.db.execute('UPDATE invitations SET access_until=NULL,birth_date=? WHERE id=?',(DATE,iid))
        self.store.db.commit(); self.store.close(); self.store=Store(self.path)
        self.assertEqual(self.store.membership_until(7),next_month(redeemed))

    def test_manual_extension_starts_now_if_expired(self):
        iid,token=self.invite(); self.redeem(token)
        old=self.store.membership_until(7); now=old+3*86400
        until=self.store.extend_membership(99,7,'renew:99:10',now=now)
        self.assertEqual(until,next_month(now))
        self.assertEqual(self.store.membership_until(7),until)
        with patch('payments.time.time',return_value=now):
            self.assertEqual(len(self.store.owned(7,DATE)),33)
            self.assertEqual(len(self.store.owned(7,'01.01.2000')),33)
    def test_early_extension_preserves_remaining_days_and_survives_restart(self):
        iid,token=self.invite(); self.redeem(token)
        old=self.store.membership_until(7)
        until=self.store.extend_membership(99,7,'renew:99:11',now=old-100)
        self.assertEqual(until,next_month(old))
        self.store.close(); self.store=Store(self.path)
        self.assertEqual(self.store.membership_until(7),until)
    def test_repeated_update_extends_only_once(self):
        iid,token=self.invite(); self.redeem(token)
        until=self.store.extend_membership(99,7,'renew:99:12')
        self.assertEqual(self.store.extend_membership(99,7,'renew:99:12'),until)
        self.assertEqual(self.store.membership_until(7),until)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM access_extensions').fetchone()[0],1)
    def test_extension_rejects_unknown_user_revoked_and_wrong_owner(self):
        iid,token=self.invite(); self.redeem(token)
        for owner,user in [(99,8),(98,7)]:
            with self.assertRaises(PaymentError): self.store.extend_membership(owner,user,'bad')
        self.store.revoke_invitation(99,iid)
        with self.assertRaises(PaymentError): self.store.extend_membership(99,7,'revoked')
        self.assertEqual(self.store.owned(7,DATE),{21,30})
    def test_extension_audit_and_revocation(self):
        iid,token=self.invite(); self.redeem(token)
        before=self.store.membership_until(7)
        until=self.store.extend_membership(99,7,'renew:99:15')
        row=self.store.db.execute('SELECT * FROM access_extensions').fetchone()
        self.assertEqual((row['owner_id'],row['user_id'],row['previous_until'],row['access_until']),(99,7,before,until))
        self.store.revoke_invitation(99,iid)
        self.assertEqual(self.store.owned(7,DATE),{21,30})
    def test_only_owner_can_use_renew_command(self):
        iid,token=self.invite(); self.redeem(token)
        before=self.store.membership_until(7)
        with patch.dict('os.environ',{'BOT_OWNER_ID':'99'}):
            handle(self.api,message('/renew 7',message_id=20),self.store,self.prices)
            self.assertEqual(self.store.membership_until(7),before)
            handle(self.api,message('/renew 7',user=99,message_id=21),self.store,self.prices)
            self.assertEqual(self.store.membership_until(7),next_month(before))
            self.assertEqual(self.api.calls[-1][1]['chat_id'],99)
            self.assertIn('акаунту 7',self.api.calls[-1][1]['text'])
            handle(self.api,message('/renew 7',user=99,message_id=21),self.store,self.prices)
            self.assertEqual(self.store.membership_until(7),next_month(before))
    def test_disabled_owner_and_bad_renew_input_do_not_change_access(self):
        iid,token=self.invite(); self.redeem(token)
        before=self.store.membership_until(7)
        with patch.dict('os.environ',{'BOT_OWNER_ID':''}):
            handle(self.api,message('/renew 7',user=99,message_id=22),self.store,self.prices)
        with patch.dict('os.environ',{'BOT_OWNER_ID':'99'}):
            for text in ['/renew','/renew @person','/renew -7','/renew 0','/renew 7 2']:
                handle(self.api,message(text,user=99,message_id=23),self.store,self.prices)
        self.assertEqual(self.store.membership_until(7),before)

if __name__=='__main__': unittest.main()
