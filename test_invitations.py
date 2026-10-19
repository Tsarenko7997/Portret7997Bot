import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bot import handle
from payments import Store, Prices, PaymentError, normalize_phone
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
    def test_owner_and_date_scoped_persistent_access(self):
        iid,token=self.invite(); self.redeem(token)
        self.store.close(); self.store=Store(self.path)
        self.assertEqual(len(self.store.owned(7,DATE)),33)
        self.assertEqual(self.store.owned(7,'16.10.1998'),{21,30})
        self.assertEqual(self.store.owned(8,DATE),{21,30})
        self.assertEqual(self.store.dates(7),[DATE])
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
    def test_activation_expiry_but_grant_permanent(self):
        iid,token=self.store.create_invitation(99,PHONE,DATE,now=100)
        with self.assertRaises(PaymentError): self.store.begin_invitation(7,token,now=100+7*86400)
        self.store.begin_invitation(7,token,now=101)
        self.store.redeem_invitation(7,{'user_id':7,'phone_number':PHONE},now=102)
        self.assertEqual(self.store.begin_invitation(7,token,now=9999999999),DATE)
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
    def test_wrong_birth_date(self):
        with self.assertRaises(ValueError): self.store.create_invitation(99,PHONE,'31.02.2000')
    def test_owner_command_fail_closed(self):
        for owner in ['', '99']:
            with patch.dict('os.environ',{'BOT_OWNER_ID':owner}):
                handle(self.api,message('/invite '+PHONE+' '+DATE),self.store,self.prices)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM invitations').fetchone()[0],0)
    def test_owner_can_issue_and_revoke(self):
        class OwnerAPI(Fake):
            def call(self,method,data=None,file=None):
                if method=='getMe': return {'username':'ExampleBot'}
                return super().call(method,data,file)
        api=OwnerAPI()
        with patch.dict('os.environ',{'BOT_OWNER_ID':'99'}):
            handle(api,message('/invite '+PHONE+' '+DATE,user=99),self.store,self.prices)
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

if __name__=='__main__': unittest.main()
