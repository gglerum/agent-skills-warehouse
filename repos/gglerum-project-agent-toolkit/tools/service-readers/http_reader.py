"""Bounded, same-base HTTPS JSON transport. No redirects or raw error bodies."""
import json
import math
import time
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError


class Unavailable(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Reader:
    def __init__(self, base, headers, seconds=120, opener=None):
        p = urlsplit(base)
        if p.scheme != 'https' or not p.hostname or p.username or p.query or p.fragment:
            raise Unavailable('configure a trusted HTTPS base URL without credentials/query/fragment')
        if not math.isfinite(seconds) or seconds <= 0:
            raise Unavailable('invalid operation budget')
        self.base, self.headers = base.rstrip('/'), headers
        self.end = time.monotonic() + seconds
        self.opener = opener or build_opener(NoRedirect)

    def trusted(self, url):
        p, base = urlsplit(url), urlsplit(self.base)
        return (p.scheme == base.scheme and p.netloc == base.netloc and not p.username
                and '..' not in unquote(p.path).split('/')
                and not p.fragment and (p.path == base.path or p.path.startswith(base.path.rstrip('/') + '/')))

    def get(self, path, params=None):
        url = path if path.startswith('https://') else self.base + '/' + path.lstrip('/')
        if params:
            url += ('&' if '?' in url else '?') + urlencode(params)
        if not self.trusted(url):
            raise Unavailable('pagination/request URL leaves configured base')
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise Unavailable('operation deadline exceeded')
        req = Request(url, headers={**self.headers, 'Accept': 'application/json', 'User-Agent': 'project-agent-toolkit/1.0'})
        try:
            with self.opener.open(req, timeout=min(30, remaining)) as response:
                chunks, size = [], 0
                while size <= 4 * 1024 * 1024:
                    if time.monotonic() >= self.end:
                        raise Unavailable('operation deadline exceeded')
                    chunk = response.read1(min(65536, 4 * 1024 * 1024 + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                raw = b''.join(chunks)
            if len(raw) > 4 * 1024 * 1024 or time.monotonic() > self.end:
                raise Unavailable('response limit or deadline exceeded')
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise Unavailable('invalid response object')
            return data
        except HTTPError as error:
            raise Unavailable(f'HTTP {error.code}; check credentials/configuration; no retry performed') from None
        except (URLError, OSError, UnicodeError, json.JSONDecodeError):
            raise Unavailable('request failed or returned invalid JSON; no retry performed') from None

    def sonar_pages(self, path, params, key):
        result, seen, identities, expected = [], set(), set(), None
        for page in range(1, 101):
            data = self.get(path, {**params, 'p': page, 'ps': 100})
            items = data.get(key)
            paging = data.get('paging', {})
            total = paging.get('total', data.get('total'))
            if not isinstance(items, list) or any(not isinstance(i, dict) for i in items) or type(total) is not int or total < 0:
                raise Unavailable('incomplete pagination metadata')
            expected = total if expected is None else expected
            if total != expected:
                raise Unavailable('pagination count changed')
            keys = [item.get('key') for item in items]
            if any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys) or identities.intersection(keys):
                raise Unavailable('missing/repeated item identity')
            identities.update(keys)
            fingerprint = json.dumps(items, sort_keys=True)
            if items and fingerprint in seen:
                raise Unavailable('repeated page')
            seen.add(fingerprint)
            result.extend(items)
            if len(result) >= total:
                if len(result) != total:
                    raise Unavailable('pagination count changed')
                return result
            if not items:
                raise Unavailable('empty page before declared total')
        raise Unavailable('page limit exceeded')

    def dojo_pages(self, path, params):
        result, seen, expected, identities = [], set(), None, set()
        url = '/api/v2/' + path.strip('/') + '/'
        for _ in range(100):
            if url in seen:
                raise Unavailable('repeated pagination URL')
            seen.add(url)
            data = self.get(url, {**params, 'limit': 200} if not result and len(seen) == 1 else None)
            items, count = data.get('results'), data.get('count')
            if not isinstance(items, list) or any(not isinstance(i, dict) for i in items) or type(count) is not int or count < 0:
                raise Unavailable('invalid pagination response')
            expected = count if expected is None else expected
            if count != expected:
                raise Unavailable('pagination count changed')
            ids = [item.get('id') for item in items]
            if any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids) or identities.intersection(ids):
                raise Unavailable('missing/repeated item identity')
            identities.update(ids)
            result.extend(items)
            url = data.get('next')
            if url is None:
                if len(result) != count:
                    raise Unavailable('incomplete pagination')
                return result
            if not isinstance(url, str) or not url or not items:
                raise Unavailable('invalid next page')
        raise Unavailable('page limit exceeded')
