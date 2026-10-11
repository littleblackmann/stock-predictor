"""Explain a saved model decision without changing probabilities or signals."""
import math


def describe_prediction(prediction):
    up = float(prediction.get('up_prob', .5))
    signal = prediction.get('prediction', -1)
    metrics = prediction.get('eval_metrics', {})
    if signal in (0, 1):
        return ('偏多' if signal == 1 else '偏空',
                '歷史命中率與機率誤差均優於基準，仍需持續驗證')
    reasons = []
    if abs(up - .5) < .05:
        title = '接近五五波 · 暫觀望'
        reasons.append('上漲機率接近 50%，未達明確方向門檻')
    else:
        title = ('模型偏多' if up > .5 else '模型偏空') + '（驗證不足）'
    if metrics:
        if metrics.get('accuracy', 0) <= metrics.get('baseline_accuracy', 0):
            reasons.append('歷史命中率未超過多數方向基準')
        if metrics.get('brier', 1) >= metrics.get('baseline_brier', 0):
            reasons.append('機率誤差未優於基準（Brier 越低越好）')
    if not reasons:
        reasons.append('歷史驗證不足，暫不列為明確方向訊號')
    return title, '；'.join(reasons)


def probability_correct(row):
    """Retrospective 50% comparison, distinct from an issued direction signal."""
    if row.get('evaluation_status') != 'final' or row.get('model_version') == 'legacy':
        return None
    if row.get('actual') not in ('up', 'down'):
        return None
    try:
        up = float(row['up_prob'])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(up) or not 0 <= up <= 1 or up == .5:
        return None
    return ('up' if up > .5 else 'down') == row['actual']
