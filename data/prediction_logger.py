"""Versioned short-term predictions with completed-session scoring."""
import json
import logging
import math
import uuid
from collections import defaultdict
from datetime import date, timedelta

from data.data_paths import PREDICTION_LOG as LOG_PATH, COOLDOWN_PATH
from data.market_time import completed_history, taipei_now, FINAL_DATA_TIME
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
    def backfill_actuals(details=False):
        """Use exact completed sessions; keep legacy estimates out of new stats.

        The default integer result remains compatible with older callers.
        Manual updates request a report so a failed fetch cannot look successful.
        """
        snapshot = PredictionLogger.load_all()
        report = {'updated': 0, 'updated_legacy': 0, 'waiting': 0,
                  'missing_data': 0, 'fetch_failed': 0, 'invalid': 0, 'rows': {}}
        import yfinance as yf
        by_symbol = defaultdict(list)
        updates = {}
        now = taipei_now()
        calendar = None
        for row in snapshot:
            legacy = row['model_version'] == 'legacy'
            if (not legacy and row['evaluation_status'] == 'final') or (legacy and PredictionLogger._has_actual(row)):
                continue
            try:
                if legacy:
                    # v1.6 recorded only the query date. Preserve its original
                    # next-session convention, explicitly marked as an estimate.
                    if calendar is None:
                        from data.holiday_checker import get_calendar
                        calendar = get_calendar()
                        calendar.refresh()
                    query = date.fromisoformat(row['prediction_date'])
                    base = query
                    for _ in range(31):
                        if calendar.is_trading_day(base):
                            break
                        base -= timedelta(days=1)
                    else:
                        raise ValueError('cannot establish legacy base session')
                    target = calendar.next_trading_day_after(query)
                else:
                    base = date.fromisoformat(row['data_date'])
                    target = date.fromisoformat(row['target_date'])
                if target <= base or not row['symbol']:
                    raise ValueError('invalid prediction dates or symbol')
                if target > now.date() or (target == now.date() and now.time() < FINAL_DATA_TIME):
                    report['waiting'] += 1
                    report['rows'][row['record_id']] = '尚未到完整收盤時間'
                    continue
                by_symbol[row['symbol']].append((row, base, target))
            except (ValueError, TypeError):
                report['invalid'] += 1
                report['rows'][row['record_id']] = '紀錄日期不完整，原資料保留'

        def price_map(hist):
            if hist is None or hist.empty or 'Close' not in hist:
                return {}
            hist = completed_history(hist, now)
            return {d.date(): float(p) for d, p in zip(hist.index, hist['Close'])
                    if math.isfinite(float(p)) and float(p) > 0}

        for symbol, rows in by_symbol.items():
            primary, fallback = {}, {}
            start = min(base for _, base, _ in rows)
            try:
                primary = price_map(yf.Ticker(symbol).history(start=start.isoformat(),
                    end=(now.date()+timedelta(days=1)).isoformat(), auto_adjust=True,
                    repair=True, timeout=15))
            except Exception:
                logger.warning('回填 %s 主來源暫不可用，嘗試備援', symbol)
            if any(base not in primary or target not in primary for _, base, target in rows):
                try:
                    from data.yfinance_adapter import YFinanceAdapter
                    fallback = price_map(YFinanceAdapter.fetch_chart(symbol, (now.date()-start).days+5))
                except Exception:
                    logger.warning('回填 %s 備援暫不可用，保留待驗證狀態', symbol)
            for row, base, target in rows:
                # Never mix adjustment factors from different responses, nor
                # substitute another session for a missing/suspended price.
                prices = primary if base in primary and target in primary else fallback
                if base not in prices or target not in prices:
                    reason = 'missing_data' if primary or fallback else 'fetch_failed'
                    report[reason] += 1
                    report['rows'][row['record_id']] = ('缺少指定交易日行情，稍後可重試' if reason == 'missing_data'
                                                        else '行情取得失敗，請檢查連線後重試')
                    continue
                ret = (prices[target]/prices[base]-1)*100
                actual = 'up' if ret > 0 else 'down'
                legacy = row['model_version'] == 'legacy'
                updates[row['record_id']] = {'actual':actual,'actual_return':f'{ret:.4f}',
                    'correct':str(row['predicted']==actual) if row['predicted'] in ('up','down') else '',
                    'evaluation_status':'legacy' if legacy else 'final'}
                if legacy:
                    updates[row['record_id']].update(data_date=base.isoformat(), target_date=target.isoformat())
                    report['updated_legacy'] += 1
        if updates:
            with locked(LOG_PATH):
                rows = read_rows(LOG_PATH)
                if report['updated_legacy']:
                    import shutil
                    from pathlib import Path
                    backup = str(LOG_PATH) + '.pre-v1.7.5-backfill.bak'
                    if not Path(backup).exists():
                        shutil.copy2(LOG_PATH, backup)
                for row in rows:
                    if row['record_id'] in updates:
                        row.update(updates[row['record_id']])
                write_rows(LOG_PATH, rows)
        report['updated'] = len(updates)
        return report if details else report['updated']

    @staticmethod
    def _has_actual(row):
        try:
            return row.get('actual') in ('up', 'down') and math.isfinite(float(row.get('actual_return', '')))
        except (ValueError, TypeError):
            return False

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
        from data.prediction_summary import probability_correct
        current = [r for r in rows if r['model_version'] != 'legacy' and r['horizon']==str(horizon)]
        evaluated = [r for r in current if r['evaluation_status']=='final' and r['correct'] in ('True','False')]
        probability_scores = [v for r in current if (v := probability_correct(r)) is not None]
        by_symbol = defaultdict(lambda:{'total':0,'correct':0})
        for r in evaluated:
            s=by_symbol[r['symbol']];s['total']+=1;s['correct']+=r['correct']=='True'
        count=sum(r['correct']=='True' for r in evaluated)
        return {'total':len(evaluated),'correct':count,'accuracy':count/len(evaluated) if evaluated else 0,
                'legacy_total':sum(r['model_version']=='legacy' for r in rows),
                'uncertain':sum(r['horizon']==str(horizon) and r['predicted']=='uncertain' for r in rows),
                'probability_total':len(probability_scores), 'probability_correct':sum(probability_scores),
                'probability_accuracy':sum(probability_scores)/len(probability_scores) if probability_scores else 0,
                'by_symbol':{s:{**v,'accuracy':v['correct']/v['total']} for s,v in by_symbol.items()}}

    @staticmethod
    def check_auto_retrain_candidates(**kwargs):
        # The new engine refreshes on data fingerprint changes, so a noisy 20-row
        # accuracy threshold no longer starts concurrent training or paid calls.
        return []

    @staticmethod
    def mark_retrained(symbol):
        pass
