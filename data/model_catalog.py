"""Public OpenRouter model metadata; never sends a user's API key."""
import json
import os
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from datetime import datetime, timezone

from data.data_paths import DATA_ROOT

CATALOG_URL = 'https://openrouter.ai/api/v1/models'
CACHE_PATH = Path(DATA_ROOT) / 'openrouter_models.json'
BUNDLED_PATH = Path(__file__).with_name('openrouter_models.json')
FEATURED = ['openai/gpt-6.1-sol', 'anthropic/claude-sonnet-5.5',
            'anthropic/claude-opus-5.5', 'openai/gpt-6-astra',
            'google/gemini-3.8-flash', 'x-ai/grok-4.7',
            'deepseek/deepseek-v4.1-flash', 'qwen/qwen3.8-max-0902',
            'moonshotai/kimi-k3', 'openai/gpt-6-luna', 'qwen/qwen3.8-flash']


def normalize_models(data):
    models = []
    for m in data:
        model_id = m.get('id', '')
        architecture = m.get('architecture') or {}
        if not model_id or ':batch' in model_id:
            continue
        if 'text' not in architecture.get('input_modalities', []) or architecture.get('output_modalities') != ['text']:
            continue
        pricing = m.get('pricing') or {}
        try:
            prompt, completion = float(pricing['prompt'])*1e6, float(pricing['completion'])*1e6
        except (KeyError, ValueError, TypeError):
            continue
        if prompt < 0 or completion < 0:
            continue
        models.append({'id':model_id, 'name':m.get('name', model_id),
                       'input_price':prompt, 'output_price':completion,
                       'context_length':m.get('context_length', 0),
                       'supported_parameters':m.get('supported_parameters', [])})
    if not models:
        raise ValueError('未取得可用的文字模型，保留原清單')
    return models


def load_catalog():
    for path in (CACHE_PATH, BUNDLED_PATH):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if value.get('models'):
                return value
        except (OSError, ValueError, TypeError):
            pass
    return {'updated_at':'', 'models':[]}


def refresh_catalog():
    request = Request(CATALOG_URL, headers={'User-Agent':'StockPredictor/1.7'})
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read(8*1024*1024))
    value = {'updated_at':__import__('data.market_time',fromlist=['taipei_now']).taipei_now().isoformat(),
             'models':normalize_models(payload['data'])}
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_PATH.parent, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)
    return value


def menu_models(catalog=None):
    catalog = catalog or load_catalog()
    priority = {model:i for i,model in enumerate(FEATURED)}
    ordered = sorted(catalog['models'], key=lambda m:(priority.get(m['id'], 999), m['id']))
    result=[]
    for m in ordered:
        group='精選模型' if m['id'] in priority else '其他文字模型'
        desc=f"每百萬 token：輸入 US${m['input_price']:g}／輸出 US${m['output_price']:g}；以供應商實際計費為準"
        if m['input_price']==0 and m['output_price']==0:
            desc+='；免費端點可能限流'
        result.append((m['id'],m['name'],group,desc))
    return result


def request_options(model_id):
    model=next((m for m in load_catalog()['models'] if m['id']==model_id), {})
    supported=model.get('supported_parameters', [])
    options={'max_tokens':4096}
    if 'response_format' in supported:
        options['response_format']={'type':'json_object'}
    if 'reasoning' in supported:
        options['extra_body']={'reasoning':{'effort':'low','exclude':True}}
    return options
