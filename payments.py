"""Transactional purchase ledger. Rights belong to (Telegram user, date, product)."""
import os
import secrets
import sqlite3
import time
import hashlib
import hmac
import re
import calendar
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from catalog import FREE

class PaymentError(ValueError):
    pass

def normalize_phone(value):
    value = re.sub(r'[\s()\-]', '', str(value))
    if value.startswith('00'): value = '+' + value[2:]
    if not value.startswith('+'): value = '+' + value
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', value):
        raise PaymentError('Вкажіть номер з кодом країни, наприклад +380XXXXXXXXX.')
    return value

def next_month(timestamp):
    current = datetime.fromtimestamp(timestamp,ZoneInfo('Europe/Kyiv'))
    year = current.year + (current.month == 12)
    month = current.month % 12 + 1
    return int(current.replace(year=year,month=month,
        day=min(current.day,calendar.monthrange(year,month)[1])).timestamp())

class Prices:
    def __init__(self, single=None, bundle=None):
        self.single = self._price(os.getenv('POSITION_PRICE_XTR', '') if single is None else single)
        self.bundle = self._price(os.getenv('BUNDLE_PRICE_XTR', '') if bundle is None else bundle)

    @staticmethod
    def _price(value):
        if value in ('', None): return None
        value = int(value)
        if not 1 <= value <= 10000: raise ValueError('Ціна Stars має бути цілим числом від 1 до 10000.')
        return value

    def amount(self, product):
        value = self.bundle if product == 'all' else self.single
        if value is None: raise PaymentError('Оплату ще не налаштовано. Зверніться до @Lakshmi_775.')
        return value

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, birth_date TEXT NOT NULL,
                product TEXT NOT NULL, amount INTEGER NOT NULL, created INTEGER NOT NULL,
                approved_at INTEGER, consent_version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS charges (
                charge_id TEXT PRIMARY KEY, order_id TEXT REFERENCES orders(id),
                user_id INTEGER NOT NULL, currency TEXT NOT NULL, amount INTEGER NOT NULL,
                state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS orders_owner ON orders(user_id, birth_date);
            CREATE INDEX IF NOT EXISTS charges_order ON charges(order_id, state);
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS invitations (
                id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, phone_hash TEXT NOT NULL,
                birth_date TEXT NOT NULL, created_by INTEGER NOT NULL, expires INTEGER NOT NULL,
                user_id INTEGER, redeemed INTEGER, revoked INTEGER);
            CREATE INDEX IF NOT EXISTS invitations_owner ON invitations(user_id, birth_date);
            CREATE TABLE IF NOT EXISTS invitation_pending (
                user_id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL, expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS access_extensions (
                request_key TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                invitation_id TEXT NOT NULL REFERENCES invitations(id), previous_until INTEGER NOT NULL,
                access_until INTEGER NOT NULL, created INTEGER NOT NULL);
        ''')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO state VALUES ('invite_hash_key',?)", (secrets.token_hex(32),))
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(invitations)')}
        if 'access_until' not in columns:
            self.db.execute('ALTER TABLE invitations ADD COLUMN access_until INTEGER')
        # Existing invitations adopt the monthly policy from their original activation time.
        with self.db:
            for row in self.db.execute('SELECT id,redeemed FROM invitations WHERE redeemed IS NOT NULL AND access_until IS NULL').fetchall():
                self.db.execute('UPDATE invitations SET access_until=? WHERE id=?',(next_month(row['redeemed']),row['id']))
        try: os.chmod(self.path, 0o600)
        except OSError: pass

    def close(self): self.db.close()

    def _owned(self, user_id, birth_date):
        if self.membership_until(user_id) > int(time.time()):
            return set(range(1,34))
        rows = self.db.execute('''SELECT o.product FROM orders o JOIN charges c ON c.order_id=o.id
            WHERE o.user_id=? AND o.birth_date=? AND c.state='paid' ''', (user_id, birth_date))
        products = {r['product'] for r in rows}
        return set(range(1,34)) if 'all' in products else FREE | {int(x) for x in products}

    def owned(self, user_id, birth_date):
        return self._owned(user_id, birth_date)

    def has(self, user_id, birth_date, number):
        return number in self.owned(user_id, birth_date)

    def create_order(self, user_id, birth_date, product, amount):
        if product != 'all' and (not product.isdigit() or int(product) not in set(range(1,34)) - FREE):
            raise PaymentError('Цю позицію купувати не потрібно.')
        owned = self._owned(user_id, birth_date)
        if (product == 'all' and len(owned) == 33) or (product != 'all' and int(product) in owned):
            raise PaymentError('Цей доступ уже відкрито. Повторна оплата не потрібна.')
        oid = secrets.token_urlsafe(18)
        with self.db:
            self.db.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,NULL,?)',
                (oid,user_id,birth_date,product,amount,int(time.time()),'1'))
        return oid

    def order(self, oid):
        return self.db.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()

    def approve(self, oid, user_id, currency, amount, now=None):
        now = int(time.time()) if now is None else now
        self.db.execute('BEGIN IMMEDIATE')
        try:
            order = self.order(oid)
            if not order or order['user_id'] != user_id or currency != 'XTR' or amount != order['amount']:
                raise PaymentError('Рахунок не відповідає покупці. Відкрийте новий рахунок у боті.')
            if now - order['created'] > 1800:
                raise PaymentError('Термін рахунку минув. Відкрийте позицію ще раз.')
            owned = self._owned(user_id, order['birth_date'])
            if ((order['product'] == 'all' and len(owned) == 33) or
                (order['product'] != 'all' and int(order['product']) in owned)):
                raise PaymentError('Цей доступ уже відкрито. Повторна оплата не потрібна.')
            pending = self.db.execute('''SELECT id FROM orders WHERE user_id=? AND birth_date=?
                AND id<>? AND approved_at>? AND NOT EXISTS
                (SELECT 1 FROM charges WHERE order_id=orders.id)''',
                (user_id,order['birth_date'],oid,now-600)).fetchone()
            if pending:
                raise PaymentError('Інша оплата для цієї дати ще обробляється. Спробуйте через кілька хвилин.')
            self.db.execute('UPDATE orders SET approved_at=? WHERE id=?', (now,oid))
            self.db.commit()
            return dict(order)
        except Exception:
            self.db.rollback(); raise

    def record_payment(self, oid, user_id, currency, amount, charge_id):
        if not charge_id: raise PaymentError('Платіж не містить ідентифікатора.')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            prior = self.db.execute('SELECT * FROM charges WHERE charge_id=?', (charge_id,)).fetchone()
            if prior:
                if prior['user_id'] != user_id: raise PaymentError('Платіж належить іншому користувачу.')
                self.db.commit()
                return prior['state'], self.order(prior['order_id'])
            order = self.order(oid)
            valid = bool(order and order['user_id'] == user_id and currency == 'XTR'
                         and order['amount'] == amount and order['approved_at'] is not None)
            duplicate = False
            if valid:
                owned = self._owned(user_id,order['birth_date'])
                duplicate = ((order['product'] == 'all' and len(owned) == 33) or
                             (order['product'] != 'all' and int(order['product']) in owned))
            state = 'paid' if valid and not duplicate else 'refund_pending'
            reason = '' if state == 'paid' else ('duplicate' if duplicate else 'invalid_order')
            self.db.execute('INSERT INTO charges VALUES (?,?,?,?,?,?,?,?)',
                (charge_id,order['id'] if order else None,user_id,currency,amount,state,reason,int(time.time())))
            self.db.commit()
            return state, order
        except Exception:
            self.db.rollback(); raise

    def pending_refunds(self):
        return self.db.execute("SELECT * FROM charges WHERE state='refund_pending' AND currency='XTR'").fetchall()

    def mark_refunded(self, charge_id, user_id):
        with self.db:
            self.db.execute("UPDATE charges SET state='refunded' WHERE charge_id=? AND user_id=?",
                            (charge_id,user_id))

    def dates(self, user_id):
        return [r[0] for r in self.db.execute('''SELECT DISTINCT o.birth_date FROM orders o
            JOIN charges c ON c.order_id=o.id WHERE o.user_id=? AND c.state='paid'
            ORDER BY o.birth_date''',(user_id,))]

    def _phone_hash(self, phone):
        key = self.db.execute("SELECT value FROM state WHERE key='invite_hash_key'").fetchone()[0]
        return hmac.new(bytes.fromhex(key), normalize_phone(phone).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def create_invitation(self, owner_id, phone, birth_date='', now=None):
        # birth_date remains a compatibility argument; new grants cover all dates.
        now = int(time.time()) if now is None else now
        phone_hash = self._phone_hash(phone)
        token, iid = secrets.token_urlsafe(24), secrets.token_hex(6)
        with self.db:
            self.db.execute('''INSERT INTO invitations
                (id,token_hash,phone_hash,birth_date,created_by,expires) VALUES (?,?,?,?,?,?)''',
                (iid,self._token_hash(token),phone_hash,'',owner_id,now+7*86400))
        return iid, token

    def begin_invitation(self, user_id, token, now=None):
        now = int(time.time()) if now is None else now
        token_hash = self._token_hash(token)
        row = self.db.execute('SELECT * FROM invitations WHERE token_hash=?', (token_hash,)).fetchone()
        if not row or row['revoked'] is not None:
            raise PaymentError('Це запрошення недоступне. Зверніться до @Lakshmi_775.')
        if row['user_id'] is not None:
            if row['user_id'] != user_id:
                raise PaymentError('Це запрошення недоступне для Вашого акаунту.')
            return ''
        if row['expires'] <= now: raise PaymentError('Термін запрошення минув. Попросіть нове посилання.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO invitation_pending VALUES (?,?,?)',
                            (user_id,token_hash,now+600))
        return None

    def redeem_invitation(self, user_id, contact, now=None):
        now = int(time.time()) if now is None else now
        if contact.get('user_id') != user_id:
            raise PaymentError('Натисніть кнопку «Поділитися своїм номером». Чужий контакт не підходить.')
        phone_hash = self._phone_hash(contact.get('phone_number',''))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('''SELECT i.*, p.expires AS pending_expires FROM invitations i
                JOIN invitation_pending p ON p.token_hash=i.token_hash WHERE p.user_id=?''', (user_id,)).fetchone()
            if not row or row['pending_expires'] <= now:
                raise PaymentError('Спочатку відкрийте своє персональне посилання ще раз.')
            if row['revoked'] is not None or (row['user_id'] is None and row['expires'] <= now):
                raise PaymentError('Запрошення більше не діє. Зверніться до @Lakshmi_775.')
            if row['user_id'] not in (None,user_id) or not hmac.compare_digest(row['phone_hash'],phone_hash):
                raise PaymentError('Це запрошення недоступне для Вашого номера або акаунту.')
            # A second unredeemed link must not restart the free month for an existing member.
            prior = self.db.execute('SELECT 1 FROM invitations WHERE user_id=? AND redeemed IS NOT NULL AND id<>?',
                                    (user_id,row['id'])).fetchone()
            if prior and row['user_id'] is None:
                raise PaymentError('Ваш пробний місяць уже активовано раніше. Перевірте /access.')
            self.db.execute('''UPDATE invitations SET user_id=?, redeemed=COALESCE(redeemed,?),
                access_until=COALESCE(access_until,?) WHERE id=?''',
                (user_id,now,next_month(now),row['id']))
            self.db.execute('DELETE FROM invitation_pending WHERE user_id=?', (user_id,))
            self.db.commit()
            return ''
        except Exception:
            self.db.rollback(); raise

    def revoke_invitation(self, owner_id, iid):
        with self.db:
            return self.db.execute('UPDATE invitations SET revoked=? WHERE id=? AND created_by=? AND revoked IS NULL',
                                   (int(time.time()),iid,owner_id)).rowcount == 1

    def membership_until(self, user_id):
        row = self.db.execute('''SELECT MAX(access_until) FROM invitations
            WHERE user_id=? AND redeemed IS NOT NULL AND revoked IS NULL''',(user_id,)).fetchone()
        return row[0] or 0

    def had_membership(self, user_id):
        return bool(self.db.execute('SELECT 1 FROM invitations WHERE user_id=? AND redeemed IS NOT NULL',
                                   (user_id,)).fetchone())

    def section(self,user_id):
        row = self.db.execute('SELECT value FROM state WHERE key=?',('section:'+str(user_id),)).fetchone()
        return row[0] if row and row[0] in ('portrait','karma','social','money') else 'portrait'

    def set_section(self,user_id,section):
        if section not in ('portrait','karma','social','money'): raise ValueError('Unknown section')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',('section:'+str(user_id),section))

    def current_birth(self,user_id):
        row = self.db.execute('SELECT value FROM state WHERE key=?',('birth:'+str(user_id),)).fetchone()
        return row[0] if row else None

    def set_current_birth(self,user_id,birth):
        from portrait import calculate
        calculate(birth)
        with self.db:
            if self.current_birth(user_id) != birth:
                self.db.execute('DELETE FROM state WHERE key=?',('money_name:'+str(user_id),))
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',('birth:'+str(user_id),birth))

    def forget_birth(self,user_id):
        with self.db:
            self.db.execute('DELETE FROM state WHERE key=?',('birth:'+str(user_id),))
            self.db.execute('DELETE FROM state WHERE key=?',('money_name:'+str(user_id),))

    def money_name(self,user_id):
        row = self.db.execute('SELECT value FROM state WHERE key=?',('money_name:'+str(user_id),)).fetchone()
        return row[0] if row else None

    def set_money_name(self,user_id,name):
        from portrait import normalize_money_name
        if not self.current_birth(user_id): raise ValueError('Спочатку введіть дату народження.')
        name = normalize_money_name(name)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',('money_name:'+str(user_id),name))

    def forget_money_name(self,user_id):
        with self.db:
            self.db.execute('DELETE FROM state WHERE key=?',('money_name:'+str(user_id),))

    def extend_membership(self, owner_id, user_id, request_key, now=None):
        now = int(time.time()) if now is None else now
        if not isinstance(user_id,int) or user_id <= 0 or not request_key:
            raise PaymentError('Вкажіть числовий Telegram ID отримувача.')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            prior = self.db.execute('SELECT * FROM access_extensions WHERE request_key=?',(request_key,)).fetchone()
            if prior:
                if prior['owner_id'] != owner_id or prior['user_id'] != user_id:
                    raise PaymentError('Цю команду вже виконано для іншого акаунту.')
                self.db.commit()
                return prior['access_until']
            row = self.db.execute('''SELECT * FROM invitations WHERE user_id=? AND created_by=?
                AND redeemed IS NOT NULL AND revoked IS NULL ORDER BY access_until DESC LIMIT 1''',
                (user_id,owner_id)).fetchone()
            if not row:
                raise PaymentError('Активованого запрошення для цього ID не знайдено або його відкликано. '
                                   'Перевірте ID. Новий користувач спочатку має активувати персональне запрошення.')
            previous = row['access_until'] or 0
            until = next_month(max(previous,now))
            self.db.execute('UPDATE invitations SET access_until=? WHERE id=?',(until,row['id']))
            self.db.execute('INSERT INTO access_extensions VALUES (?,?,?,?,?,?,?)',
                            (request_key,owner_id,user_id,row['id'],previous,until,now))
            self.db.commit()
            return until
        except Exception:
            self.db.rollback(); raise

    def offset(self):
        row = self.db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
        return int(row[0]) if row else 0

    def set_offset(self, offset):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES ('offset',?)",(str(offset),))
