"""Full/Pro invitation boundaries, upgrades, revocation and legacy migration."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import test_compatibility  # Synthetic catalog for standalone runs.
from payments import Store,Prices,PaymentError,next_month
from bot import handle,has_full_access,has_pro_access,access_text
from test_payments import Fake,callback
from test_invitations import message

PHONE='+380991234567'

class ProAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'db'
        self.store=Store(self.path);self.api=Fake();self.prices=Prices('','')
        self.now=int(time.time())
    def tearDown(self):self.store.close();self.temp.cleanup()
    def invite(self,tier='full',now=None):
        return self.store.create_invitation(99,PHONE,now=self.now if now is None else now,tier=tier)
    def redeem(self,token,now=None,user=7,phone=PHONE):
        now=self.now if now is None else now
        self.store.begin_invitation(user,token,now=now)
        return self.store.redeem_invitation(user,{'user_id':user,'phone_number':phone},now=now)
    def grant(self,tier='full'):
        iid,token=self.invite(tier);self.redeem(token);return iid,token
    def test_default_full_keeps_existing_scope_without_pro(self):
        iid,token=self.grant()
        self.assertEqual(self.store.membership_tier(7),'full')
        self.assertTrue(has_full_access(self.store,7));self.assertFalse(has_pro_access(self.store,7))
        self.assertEqual(self.store.db.execute('SELECT tier FROM invitations WHERE id=?',(iid,)).fetchone()[0],'full')
    def test_first_pro_invite_grants_both_levels(self):
        self.grant('pro')
        self.assertEqual(self.store.membership_until(7),next_month(self.now))
        self.assertEqual(self.store.pro_until(7),next_month(self.now))
        self.assertTrue(has_full_access(self.store,7));self.assertTrue(has_pro_access(self.store,7))
    def test_invalid_tier_rejected_before_invitation_created(self):
        for tier in ('admin','Pro','',None):
            with self.assertRaises(PaymentError):self.invite(tier)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM invitations').fetchone()[0],0)
    def test_upgrade_keeps_original_end_date_and_survives_reopening(self):
        self.grant();until=self.store.membership_until(7)
        iid,token=self.invite('pro');self.redeem(token,now=self.now+300)
        self.assertEqual(self.store.pro_until(7),until)
        self.assertEqual(self.store.membership_until(7),until)
        self.assertEqual(self.store.begin_invitation(7,token,now=self.now+1000),'')
        self.assertEqual(self.store.pro_until(7),until)
    def test_redundant_links_cannot_restart_or_downgrade_membership(self):
        self.grant('pro');until=self.store.membership_until(7)
        for tier in ('full','pro'):
            iid,token=self.invite(tier)
            with self.assertRaises(PaymentError):self.redeem(token,now=self.now+20)
        self.assertEqual(self.store.membership_until(7),until)
        self.assertEqual(self.store.membership_tier(7),'pro')
    def test_expired_full_cannot_get_new_month_via_pro_link(self):
        iid,token=self.grant();until=self.store.membership_until(7)
        iid,token=self.invite('pro',now=until+1)
        with self.assertRaises(PaymentError):self.redeem(token,now=until+2)
        self.assertEqual(self.store.pro_until(7),0)
    def test_revoking_upgrade_restores_remaining_full_and_blocks_pro(self):
        self.grant();iid,token=self.invite('pro');self.redeem(token)
        self.assertTrue(self.store.revoke_invitation(99,iid))
        self.assertTrue(has_full_access(self.store,7));self.assertFalse(has_pro_access(self.store,7))
        self.assertEqual(self.store.membership_tier(7),'full')
    def test_expiry_is_checked_without_restart(self):
        self.grant('pro');until=self.store.pro_until(7)
        self.assertEqual(self.store.membership_tier(7,now=until-1),'pro')
        self.assertIsNone(self.store.membership_tier(7,now=until))
        with patch('bot.time.time',return_value=until):self.assertFalse(has_pro_access(self.store,7))
    def test_plain_renewal_preserves_pro(self):
        self.grant('pro');old=self.store.pro_until(7)
        until=self.store.extend_membership(99,7,'request',now=self.now)
        self.assertEqual(until,next_month(old));self.assertEqual(self.store.pro_until(7),until)
        audit=self.store.db.execute('SELECT * FROM access_extensions').fetchone()
        self.assertEqual((audit['previous_tier'],audit['new_tier']),('pro','pro'))
    def test_explicit_pro_renewal_upgrades_and_is_idempotent(self):
        self.grant();old=self.store.membership_until(7)
        until=self.store.extend_membership(99,7,'request',now=self.now,tier='pro')
        self.assertEqual(until,next_month(old));self.assertEqual(self.store.pro_until(7),until)
        self.assertEqual(self.store.extend_membership(99,7,'request',tier='pro'),until)
        audit=self.store.db.execute('SELECT * FROM access_extensions').fetchone()
        self.assertEqual((audit['previous_tier'],audit['new_tier']),('full','pro'))
    def test_renewal_cannot_reuse_basic_request_for_upgrade(self):
        self.grant();self.store.extend_membership(99,7,'request')
        with self.assertRaises(PaymentError):self.store.extend_membership(99,7,'request',tier='pro')
        self.assertEqual(self.store.pro_until(7),0)
    def test_renew_after_expiry_keeps_tier(self):
        self.grant('pro');now=self.store.pro_until(7)+100
        until=self.store.extend_membership(99,7,'request',now=now)
        self.assertEqual(until,next_month(now))
        self.assertEqual(self.store.membership_tier(7,now=now),'pro')
    def test_pro_requires_correct_contact_and_recipient(self):
        iid,token=self.invite('pro')
        with self.assertRaises(PaymentError):self.redeem(token,phone='+380991234568')
        self.assertEqual(self.store.pro_until(7),0)
        self.redeem(token)
        with self.assertRaises(PaymentError):self.store.begin_invitation(8,token)
    def test_only_owner_can_create_or_renew_pro(self):
        with patch.dict('os.environ',{'BOT_OWNER_ID':'99'}):
            for text in ('/invitepro '+PHONE,'/renewpro 7'):
                handle(self.api,message(text,message_id=1),self.store,self.prices)
                self.assertIn('лише власнику',self.api.calls[-1][1]['text'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM invitations').fetchone()[0],0)
    def test_owner_pro_invite_records_server_side_tier(self):
        original=self.api.call
        with patch.dict('os.environ',{'BOT_OWNER_ID':'99'}),patch.object(self.api,'call',side_effect=lambda method,*args,**kwargs: {'username':'FixtureBot'} if method=='getMe' else original(method,*args,**kwargs)):
            handle(self.api,message('/invitepro '+PHONE,user=99,message_id=1),self.store,self.prices)
        row=self.store.db.execute('SELECT * FROM invitations').fetchone()
        self.assertEqual(row['tier'],'pro')
        self.assertIn('Pro',self.api.calls[-1][1]['text'])
    def test_package_choice_does_not_grant_any_access(self):
        handle(self.api,callback('package:pro'),self.store,self.prices)
        self.assertFalse(has_full_access(self.store,7));self.assertFalse(has_pro_access(self.store,7))
    def test_program_routes_recheck_pro_for_full_and_expired_users(self):
        self.grant()
        for action in ('section:programs','program:1','program_question:1:1','programs'):
            handle(self.api,callback(action),self.store,self.prices)
            self.assertIn('лише в пакеті Pro',self.api.calls[-1][1]['text'])
    def test_pro_missing_catalog_fails_without_exposing_partial_content(self):
        self.grant('pro');handle(self.api,callback('section:programs'),self.store,self.prices)
        self.assertIn('Не вдалося відкрити описи програм',self.api.calls[-1][1]['text'])
        self.assertNotIn('100 грн',access_text(self.store,7))
    def test_migration_preserves_existing_invites_and_audit_records_as_full(self):
        self.store.close()
        db=sqlite3.connect(self.path)
        db.executescript('DROP TABLE invitations; DROP TABLE access_extensions;'
          'CREATE TABLE invitations (id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,phone_hash TEXT NOT NULL,birth_date TEXT NOT NULL,created_by INTEGER NOT NULL,expires INTEGER NOT NULL,user_id INTEGER,redeemed INTEGER,revoked INTEGER,access_until INTEGER);'
          'CREATE TABLE access_extensions (request_key TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,user_id INTEGER NOT NULL,invitation_id TEXT NOT NULL,previous_until INTEGER NOT NULL,access_until INTEGER NOT NULL,created INTEGER NOT NULL);')
        db.execute('INSERT INTO invitations VALUES (?,?,?,?,?,?,?,?,?,?)',('legacy','hash','phone','',99,self.now+100,7,self.now,None,self.now+10000))
        db.execute('INSERT INTO access_extensions VALUES (?,?,?,?,?,?,?)',('old',99,7,'legacy',self.now,self.now+10000,self.now));db.commit();db.close()
        self.store=Store(self.path)
        self.assertEqual(self.store.membership_tier(7),'full');self.assertEqual(self.store.pro_until(7),0)
        audit=self.store.db.execute('SELECT * FROM access_extensions').fetchone();self.assertEqual(audit['new_tier'],'full')
        self.store.close();self.store=Store(self.path)
        self.assertEqual(self.store.membership_tier(7),'full')

if __name__=='__main__':unittest.main()
