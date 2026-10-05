"""Bounded, resumable downloads of immutable GitHub release assets."""
import hashlib
import http.client
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request


def download_asset(url, destination, opener, *, expected_size=0, expected_sha256=None,
                   progress=None, status=None, attempts=5, delay=time.sleep,
                   bytes_per_second=0):
    from resource_budget import RateLimiter
    limiter = RateLimiter(bytes_per_second)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = destination.with_suffix('.json')
    total = int(expected_size or 0)
    etag = None
    if metadata.exists():
        try:
            saved = json.loads(metadata.read_text(encoding='utf-8'))
            if saved['url'] == url:
                etag = saved.get('etag')
                total = total or int(saved.get('total', 0))
        except (OSError, ValueError, KeyError):
            pass

    def announce(message):
        if status:
            status(message)

    for attempt in range(attempts):
        offset = destination.stat().st_size if destination.exists() else 0
        if total and offset == total:
            break
        if total and offset > total:
            destination.write_bytes(b'')
            offset = 0
        headers = {'User-Agent': 'StockPredictor-Updater/1.7.3', 'Accept-Encoding': 'identity'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
            if etag:
                headers['If-Range'] = etag
            announce(f'繼續下載：已保留 {offset / 1024 / 1024:.1f} MB')
        try:
            with opener(Request(url, headers=headers), timeout=45) as response:
                code = response.getcode()
                if code == 206:
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if not match or int(match[1]) != offset or int(match[2]) < offset or int(match[2]) >= int(match[3]):
                        raise ValueError('下載來源回傳錯誤的續傳範圍')
                    remote_total = int(match[3])
                    mode = 'ab'
                elif code == 200:
                    # A server may ignore Range or replace an asset (If-Range).
                    offset = 0
                    remote_total = int(response.headers.get('Content-Length', 0))
                    mode = 'wb'
                else:
                    raise ValueError(f'下載來源回應異常：HTTP {code}')
                if total and remote_total and total != remote_total:
                    raise ValueError('更新包大小與版本資訊不符，請重新檢查更新')
                total = total or remote_total
                etag = response.headers.get('ETag')
                metadata.write_text(json.dumps({'url': url, 'total': total, 'etag': etag}), encoding='utf-8')
                with destination.open(mode) as stream:
                    if progress:
                        progress(offset, total)
                    while True:
                        try:
                            chunk = response.read(64 * 1024)
                        except http.client.IncompleteRead as error:
                            if error.partial:
                                stream.write(error.partial)
                            raise
                        if not chunk:
                            break
                        stream.write(chunk)
                        limiter.consume(len(chunk))
                        offset += len(chunk)
                        if total and offset > total:
                            raise ValueError('下載內容超過更新包大小')
                        if progress:
                            progress(offset, total)
                if total and offset != total:
                    raise ConnectionError(f'下載中斷：{offset}/{total} bytes')
            break
        except (URLError, TimeoutError, ConnectionError, http.client.HTTPException) as error:
            if isinstance(error, HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt + 1 == attempts:
                raise ConnectionError('下載連線多次中斷，已保留進度；請再次更新以續傳') from error
            announce(f'連線中斷，正在重試（{attempt + 1}/{attempts - 1}）；下載進度會保留')
            delay(min(2 ** attempt, 8))

    announce('正在確認下載大小與 SHA-256…')
    if total and destination.stat().st_size != total:
        raise ValueError('更新包下載不完整')
    if expected_sha256:
        with destination.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual.lower() != expected_sha256.lower():
            destination.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            raise ValueError('更新包 SHA-256 不符，已移除損毀下載；請重新更新')
    if progress:
        progress(destination.stat().st_size, total)
    return destination
