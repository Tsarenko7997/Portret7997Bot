"""Transactional purchase ledger. Rights belong to (Telegram user, date, product)."""
import os
import secrets
import sqlite3
import time
from pathlib import Path
from catalog import FREE

class PaymentError(ValueError):
    pass

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
        ''')
        try: os.chmod(self.path, 0o600)
        except OSError: pass

    def close(self): self.db.close()

    def _owned(self, user_id, birth_date):
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

    def offset(self):
        row = self.db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
        return int(row[0]) if row else 0

    def set_offset(self, offset):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES ('offset',?)",(str(offset),))
