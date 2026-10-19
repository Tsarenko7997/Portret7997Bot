import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from bot import handle, process_refunds, storage_path
from catalog import POSITIONS, FREE, chunks, description, read_catalog
from payments import Store, Prices, PaymentError
from portrait import calculate

DATE='16.09.1998'
OTHER='01.01.2000'

class Fake:
    def __init__(self):self.calls=[]
    def call(self,method,data=None,file=None):
        self.calls.append((method,data,file));return True
    def say(self,chat,text,**kwargs):
        self.calls.append(('sendMessage',{'chat_id':chat,'text':text,**kwargs},None))

def callback(data,user=7):
    return {'callback_query':{'id':'cb','from':{'id':user},'data':data,
                             'message':{'chat':{'id':user,'type':'private'}}}}

class PurchaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'db.sqlite3'
        self.store=Store(self.path);self.prices=Prices(40,1200);self.api=Fake()
    def tearDown(self):self.store.close();self.temp.cleanup()
    def pay(self,product='1',date=DATE,user=7,charge='charge1'):
        amount=self.prices.amount(product)
        oid=self.store.create_order(user,date,product,amount)
        self.store.approve(oid,user,'XTR',amount)
        self.store.record_payment(oid,user,'XTR',amount,charge)
        return oid
    def test_catalog_coverage_and_free_mapping(self):
        self.assertEqual(len(POSITIONS),33)
        self.assertEqual(sum(len(p['arcana']) for p in POSITIONS.values()),726)
        self.assertEqual(POSITIONS[21]['key'],'П21');self.assertEqual(POSITIONS[30]['key'],'П30')
        self.assertEqual(self.store.owned(7,DATE),{21,30})
    def test_individual_is_user_and_date_scoped(self):
        self.pay()
        self.assertTrue(self.store.has(7,DATE,1));self.assertFalse(self.store.has(7,DATE,2))
        self.assertFalse(self.store.has(8,DATE,1));self.assertFalse(self.store.has(7,OTHER,1))
    def test_same_arcanum_other_date_is_not_unlocked(self):
        other='16.10.1998'
        self.assertEqual(calculate(DATE)[0]['П1'],calculate(other)[0]['П1'])
        self.pay();self.assertFalse(self.store.has(7,other,1))
    def test_bundle_is_scoped_and_persists(self):
        self.pay('all');self.store.close();self.store=Store(self.path)
        self.assertEqual(len(self.store.owned(7,DATE)),33)
        self.assertEqual(self.store.owned(7,OTHER),FREE);self.assertEqual(self.store.owned(8,DATE),FREE)
    def test_precheckout_alone_grants_nothing(self):
        oid=self.store.create_order(7,DATE,'1',40);self.store.approve(oid,7,'XTR',40)
        self.assertFalse(self.store.has(7,DATE,1))
    def test_precheckout_rejects_currency_amount_owner_unknown(self):
        oid=self.store.create_order(7,DATE,'1',40)
        for token,uid,currency,amount in [(oid,8,'XTR',40),(oid,7,'UAH',40),(oid,7,'XTR',41),('bad',7,'XTR',40)]:
            with self.assertRaises(PaymentError):self.store.approve(token,uid,currency,amount)
    def test_expired_invoice(self):
        oid=self.store.create_order(7,DATE,'1',40)
        with self.assertRaises(PaymentError):self.store.approve(oid,7,'XTR',40,now=int(time.time())+1801)
    def test_duplicate_update_is_idempotent(self):
        oid=self.pay()
        self.store.record_payment(oid,7,'XTR',40,'charge1')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM charges').fetchone()[0],1)
    def test_already_owned_rejects_new_checkout(self):
        old=self.store.create_order(7,DATE,'1',40);self.pay()
        with self.assertRaises(PaymentError):self.store.approve(old,7,'XTR',40)
        with self.assertRaises(PaymentError):self.store.create_order(7,DATE,'1',40)
    def test_parallel_checkouts_blocked(self):
        one=self.store.create_order(7,DATE,'1',40);two=self.store.create_order(7,DATE,'all',1200)
        self.store.approve(one,7,'XTR',40)
        with self.assertRaises(PaymentError):self.store.approve(two,7,'XTR',1200)
    def test_late_overlapping_payment_refunded(self):
        one=self.store.create_order(7,DATE,'1',40)
        self.store.approve(one,7,'XTR',40)
        self.store.db.execute('UPDATE orders SET approved_at=? WHERE id=?',(int(time.time())-601,one));self.store.db.commit()
        self.pay('all',charge='bundle')
        state,_=self.store.record_payment(one,7,'XTR',40,'late')
        self.assertEqual(state,'refund_pending')
        process_refunds(self.api,self.store)
        self.assertEqual(self.store.pending_refunds(),[])
        self.assertEqual(len(self.store.owned(7,DATE)),33)
    def test_unapproved_or_mismatched_success_never_grants(self):
        oid=self.store.create_order(7,DATE,'1',40)
        for i,(uid,currency,amount) in enumerate([(7,'XTR',40),(8,'XTR',40),(7,'XTR',400),(7,'UAH',40)]):
            status,_=self.store.record_payment(oid,uid,currency,amount,'invalid'+str(i))
            self.assertEqual(status,'refund_pending')
        self.assertEqual(self.store.owned(7,DATE),FREE)
    def test_refund_revokes_only_corresponding_access(self):
        self.pay();self.pay('2',charge='charge2')
        self.store.mark_refunded('charge1',7)
        self.assertFalse(self.store.has(7,DATE,1));self.assertTrue(self.store.has(7,DATE,2))
        self.assertTrue(self.store.has(7,DATE,21))
    def test_bundle_refund_preserves_previous_individual(self):
        self.pay();self.pay('all',charge='bundle');self.store.mark_refunded('bundle',7)
        self.assertEqual(self.store.owned(7,DATE),{1,21,30})
    def test_menu_33_buttons_locks_and_paid_revisit(self):
        self.pay()
        handle(self.api,callback('menu:'+DATE),self.store,self.prices)
        rows=self.api.calls[-1][1]['reply_markup']['inline_keyboard']
        buttons=[b for row in rows for b in row if b['callback_data'].startswith('position:')]
        self.assertEqual(len(buttons),33)
        for n in range(1,34):self.assertEqual('🔒' in buttons[n-1]['text'],n not in {1,21,30})
    def test_locked_description_not_leaked(self):
        handle(self.api,callback('position:'+DATE+':1'),self.store,self.prices)
        body='\n'.join(c[1].get('text','') for c in self.api.calls)
        self.assertNotIn(POSITIONS[1]['arcana']['16']['problems'],body)
        self.assertIn('Погоджуюсь',json.dumps(self.api.calls,ensure_ascii=False))
    def test_free_opens_without_invoice(self):
        for n in (21,30):handle(self.api,callback(f'position:{DATE}:{n}'),self.store,self.prices)
        self.assertFalse(any(c[0]=='sendInvoice' for c in self.api.calls))
        self.assertIn('Позитивні прояви',str(self.api.calls))
    def test_invoice_snapshots_date_user_price(self):
        handle(self.api,callback('invoice:'+DATE+':1'),self.store,self.prices)
        inv=self.api.calls[-1][1]
        self.assertEqual(inv['currency'],'XTR');self.assertEqual(inv['prices'][0]['amount'],40)
        order=self.store.order(inv['payload']);self.assertEqual(order['birth_date'],DATE);self.assertEqual(order['user_id'],7)
    def test_checkout_and_success_workflow(self):
        handle(self.api,callback('invoice:'+DATE+':1'),self.store,self.prices)
        oid=self.api.calls[-1][1]['payload']
        handle(self.api,{'pre_checkout_query':{'id':'pre','from':{'id':7},'invoice_payload':oid,'currency':'XTR','total_amount':40}},self.store,self.prices)
        self.assertTrue(self.api.calls[-1][1]['ok']);self.assertFalse(self.store.has(7,DATE,1))
        handle(self.api,{'message':{'from':{'id':7},'chat':{'id':7,'type':'private'},'successful_payment':{'invoice_payload':oid,'currency':'XTR','total_amount':40,'telegram_payment_charge_id':'telegram1'}}},self.store,self.prices)
        self.assertTrue(self.store.has(7,DATE,1))
        self.assertIn(POSITIONS[1]['arcana']['16']['core'],str(self.api.calls))
    def test_p15_two_results_one_purchase_and_split_safe(self):
        self.pay('15');p,_=calculate(DATE);text=description(15,DATE,p)
        self.assertIn('Результат 1',text);self.assertIn('Результат 2',text)
        for chunk in chunks(text):self.assertLessEqual(len(chunk.encode('utf-16-le'))//2,3900)
    def test_all_descriptions_fit_message_chunks(self):
        for n in range(1,34):
            for value in range(1,23):
                p,_=calculate(DATE);key=POSITIONS[n]['key']
                if key=='П15':p['П15а']=value;p['П15б']=23-value
                else:p[key]=value
                text=description(n,DATE,p)
                self.assertNotIn('—',text)
                for chunk in chunks(text):self.assertLessEqual(len(chunk.encode('utf-16-le'))//2,3900)
    def test_old_callbacks_and_tampered_callbacks_do_not_bypass(self):
        for data in ['calc:'+DATE,'position:'+DATE+':99','position:bad:1','invoice:'+DATE+':21']:
            handle(self.api,callback(data),self.store,self.prices)
        self.assertEqual(self.store.owned(7,DATE),FREE)
        self.assertFalse(any(c[0]=='sendInvoice' for c in self.api.calls))
    def test_disabled_prices_send_no_invoice(self):
        handle(self.api,callback('invoice:'+DATE+':1'),self.store,Prices('',''))
        self.assertFalse(any(c[0]=='sendInvoice' for c in self.api.calls))
    def test_storage_requires_volume_for_railway_payments(self):
        with patch.dict('os.environ',{'RAILWAY_ENVIRONMENT_ID':'prod','DATA_DIR':'/tmp'},clear=True):
            with self.assertRaises(SystemExit):storage_path(self.prices)
        with patch.dict('os.environ',{'RAILWAY_ENVIRONMENT_ID':'prod','RAILWAY_VOLUME_MOUNT_PATH':'/data','DATA_DIR':'/data'},clear=True):
            self.assertEqual(str(storage_path(self.prices)),'/data/purchases.sqlite3')
    def test_durable_offset(self):
        self.store.set_offset(123);self.store.close();self.store=Store(self.path)
        self.assertEqual(self.store.offset(),123)
    def test_private_catalog_configuration_and_integrity(self):
        import lzma,base64,hashlib
        raw=json.dumps(list(POSITIONS.values()),ensure_ascii=False).encode()
        packed=base64.b64encode(lzma.compress(raw)).decode()
        env={'CATALOG_XZ_PARTS':'2','CATALOG_XZ_B64_1':packed[:30000],
             'CATALOG_XZ_B64_2':packed[30000:],'CATALOG_SHA256':hashlib.sha256(raw).hexdigest()}
        with patch.dict('os.environ',env):self.assertEqual(len(read_catalog()),33)
        env['CATALOG_SHA256']='invalid'
        with patch.dict('os.environ',env):
            with self.assertRaises(ValueError):read_catalog()
    def test_payment_persists_if_delivery_fails(self):
        from bot import APIError
        oid=self.store.create_order(7,DATE,'1',40);self.store.approve(oid,7,'XTR',40)
        with patch.object(self.api,'say',side_effect=APIError(0)):
            with self.assertRaises(APIError):
                handle(self.api,{'message':{'from':{'id':7},'chat':{'id':7,'type':'private'},'successful_payment':{'invoice_payload':oid,'currency':'XTR','total_amount':40,'telegram_payment_charge_id':'delivery-fail'}}},self.store,self.prices)
        self.assertTrue(self.store.has(7,DATE,1))
    def test_refund_service_message_without_human_sender(self):
        self.pay()
        handle(self.api,{'message':{'chat':{'id':7,'type':'private'},'refunded_payment':{'telegram_payment_charge_id':'charge1'}}},self.store,self.prices)
        self.assertFalse(self.store.has(7,DATE,1))

if __name__=='__main__':unittest.main()
