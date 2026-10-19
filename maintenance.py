"""Owner-only server CLI for consistent backups and full Stars refunds."""
import argparse
import sqlite3
from pathlib import Path
from bot import Telegram, load_env, storage_path
from payments import Store, Prices
import os

def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    backup=sub.add_parser('backup');backup.add_argument('destination')
    refund=sub.add_parser('refund');refund.add_argument('charge_id')
    args=parser.parse_args()
    load_env();store=Store(storage_path(Prices()))
    try:
        if args.command=='backup':
            dest=Path(args.destination).resolve()
            if dest==store.path.resolve(): raise SystemExit('Вкажіть інший шлях для резервної копії.')
            dest.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(dest) as db:store.db.backup(db)
            os.chmod(dest,0o600)
            print('Резервну копію створено.')
        else:
            row=store.db.execute('SELECT * FROM charges WHERE charge_id=?',(args.charge_id,)).fetchone()
            if not row:raise SystemExit('Платіж не знайдено.')
            if row['state']=='refunded':raise SystemExit('Платіж уже повернено.')
            if row['currency']!='XTR':raise SystemExit('Для цього платежу автоматичне повернення недоступне.')
            token=os.getenv('TELEGRAM_BOT_TOKEN')
            if not token:raise SystemExit('Токен не налаштовано.')
            Telegram(token).call('refundStarPayment',{'user_id':row['user_id'],
                'telegram_payment_charge_id':row['charge_id']})
            store.mark_refunded(row['charge_id'],row['user_id'])
            print('Stars повернено. Доступ за цим платежем відкликано.')
    finally:store.close()

if __name__=='__main__':main()
