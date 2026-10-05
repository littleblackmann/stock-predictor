"""Versioned short-term predictions with completed-session scoring."""
import json
import logging
import math
import uuid
from collections import defaultdict
from datetime import date, timedelta

from data.data_paths import PREDICTION_LOG as LOG_PATH, COOLDOWN_PATH
from data.market_time import completed_history, taipei_now
from data.record_store import FIELDS, locked, read_rows, write_rows

logger = logging.getLogger(__name__)


class PredictionLogger:
    @staticmethod
    def load_all():
        with locked(LOG_PATH):
            return read_rows(LOG_PATH)

    @staticmethod
    def migrate_header_if_needed():
        PredictionLogger.load_all()
        return 0

    @staticmethod
    def append(result):
        now = result.get('created_at') or taipei_now().isoformat()
        with locked(LOG_PATH):
            rows = read_rows(LOG_PATH)
            for pred in result.get('horizons', [result.get('prediction', {})]):
                horizon = str(pred.get('horizon', 1))
                target = pred.get('target_date', result.get('target_date', ''))
                identity = (result['symbol'], result.get('data_date', ''), target, horizon, pred.get('model_version', ''))
                # One immutable prediction per source session/horizon/version.
                if any((r['symbol'], r['data_date'], r['target_date'], r['horizon'], r['model_version']) == identity for r in rows):
                    continue
                row = dict.fromkeys(FIELDS, '')
                row.update(prediction_date=now[:10], symbol=result['symbol'],
                           predicted={1:'up',0:'down',-1:'uncertain'}.get(pred.get('prediction'), 'uncertain'),
                           up_prob=f"{pred.get('up_prob', .5):.4f}",
                           down_prob=f"{pred.get('down_prob', .5):.4f}",
                           raw_up_prob=f"{pred.get('raw_up_prob', .5):.4f}",
                           gpt_3day=PredictionLogger._format_forecast(result.get('forecast_3d', [])),
                           record_id=uuid.uuid4().hex, created_at=now,
                           data_date=result.get('data_date', ''), target_date=target,
                           horizon=horizon, model_version=pred.get('model_version', 'legacy'),
                           evaluation_status='pending')
                rows.append(row)
            write_rows(LOG_PATH, rows)

    @staticmethod
    def backfill_actuals():
        snapshot = PredictionLogger.load_all()
        pending = [r for r in snapshot if r['model_version'] != 'legacy' and r['evaluation_status'] != 'final']
        if not pending:
            return 0
        import yfinance as yf
        by_symbol = defaultdict(list)
        for row in pending:
            by_symbol[row['symbol']].append(row)
        updates = {}
        now = taipei_now()
        for symbol, rows in by_symbol.items():
            try:
                start = min(date.fromisoformat(r['data_date']) for r in rows)
                try:
                    hist = yf.Ticker(symbol).history(start=start.isoformat(),
                        end=(now.date()+timedelta(days=1)).isoformat(), auto_adjust=True, repair=True)
                except Exception:
                    from data.yfinance_adapter import YFinanceAdapter
                    hist = YFinanceAdapter.fetch_chart(symbol, (now.date()-start).days+5)
                if hist.empty:
                    continue
                hist = completed_history(hist, now)
                prices = {d.date():float(p) for d,p in zip(hist.index,hist['Close']) if math.isfinite(float(p)) and float(p)>0}
                for row in rows:
                    base = date.fromisoformat(row['data_date'])
                    target = date.fromisoformat(row['target_date'])
                    # Exact sessions only: absent/suspended/delayed prices are not
                    # silently replaced with another day's price.
                    if base not in prices or target not in prices:
                        continue
                    ret = (prices[target]/prices[base]-1)*100
                    actual = 'up' if ret > 0 else 'down'
                    updates[row['record_id']] = {'actual':actual,'actual_return':f'{ret:.4f}',
                        'correct':str(row['predicted']==actual) if row['predicted'] in ('up','down') else '',
                        'evaluation_status':'final'}
            except Exception:
                logger.warning('回填 %s 失敗，保留待驗證狀態', symbol, exc_info=True)
        if updates:
            with locked(LOG_PATH):
                rows = read_rows(LOG_PATH)
                for row in rows:
                    if row['record_id'] in updates:
                        row.update(updates[row['record_id']])
                write_rows(LOG_PATH, rows)
        return len(updates)

    @staticmethod
    def _format_forecast(forecast):
        if not isinstance(forecast, list):
            return str(forecast or '')[:300]
        return ' / '.join(f"{x.get('day','')}:{x.get('trend','')}" for x in forecast if isinstance(x,dict))

    @staticmethod
    def delete_rows(indices):
        with locked(LOG_PATH):
            rows = read_rows(LOG_PATH)
            # Preserve an undoable snapshot before an explicit UI deletion.
            import shutil
            shutil.copy2(LOG_PATH, str(LOG_PATH)+'.before-delete.bak')
            write_rows(LOG_PATH, [r for i,r in enumerate(rows) if i not in set(indices)])

    @staticmethod
    def get_stats(horizon=1):
        rows = PredictionLogger.load_all()
        evaluated = [r for r in rows if r['evaluation_status']=='final' and r['horizon']==str(horizon) and r['correct'] in ('True','False')]
        by_symbol = defaultdict(lambda:{'total':0,'correct':0})
        for r in evaluated:
            s=by_symbol[r['symbol']];s['total']+=1;s['correct']+=r['correct']=='True'
        count=sum(r['correct']=='True' for r in evaluated)
        return {'total':len(evaluated),'correct':count,'accuracy':count/len(evaluated) if evaluated else 0,
                'legacy_total':sum(r['model_version']=='legacy' for r in rows),
                'uncertain':sum(r['horizon']==str(horizon) and r['predicted']=='uncertain' for r in rows),
                'by_symbol':{s:{**v,'accuracy':v['correct']/v['total']} for s,v in by_symbol.items()}}

    @staticmethod
    def check_auto_retrain_candidates(**kwargs):
        # The new engine refreshes on data fingerprint changes, so a noisy 20-row
        # accuracy threshold no longer starts concurrent training or paid calls.
        return []

    @staticmethod
    def mark_retrained(symbol):
        pass
