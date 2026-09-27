"""Mountable stdlib HTTP surface. Local files only; all methods are read-only."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote

from .model import LANES, Reader, stamp

STATIC = Path(__file__).with_name('static')
PERIODS = {'1H': 3600, '6H': 21600, '24H': 86400, '7D': 604800, '30D': 2592000, 'ALL': None}
HEADERS = {
    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}


class Dashboard:
    def __init__(self, reader=None):
        self.reader = reader or Reader()

    def response(self, method, target):
        """Returns status, headers, bytes; has no connection to an execution engine."""
        parsed = urlsplit(target)
        if parsed.path != '/dashboard' and not parsed.path.startswith(('/dashboard/', '/api/dashboard/')):
            return None
        headers = dict(HEADERS)
        if method not in ('GET', 'HEAD'):
            headers['Allow'] = 'GET, HEAD'
            return 405, dict(headers, **{'Content-Type': 'application/json'}), b'{"error":"read_only"}'
        if parsed.path in ('/dashboard', '/dashboard/', '/dashboard/app.js', '/dashboard/style.css'):
            name = {'/dashboard/app.js': 'app.js', '/dashboard/style.css': 'style.css'}.get(parsed.path, 'index.html')
            mime = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css; charset=utf-8'}[name]
            return 200, dict(headers, **{'Content-Type': mime}), (STATIC/name).read_bytes()
        status = 200
        try:
            params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=16)
            if any(len(v) != 1 or len(v[0]) > 120 for v in params.values()):
                raise ValueError('query')
            query = {k: v[0] for k, v in params.items()}
            route = parsed.path.removeprefix('/api/dashboard/')
            allowed = {'portfolio': set(), 'lanes': set(), 'system': set(), 'analytics': set(),
                       'equity': {'period', 'series', 'limit'},
                       'positions': {'lane', 'q', 'limit', 'offset'},
                       'trades': {'lane', 'q', 'outcome', 'strategy', 'from', 'to', 'limit', 'offset'}}
            if route.startswith('lanes/') and route[6:] in LANES:
                allowed[route] = set()
            if route.startswith('positions/'):
                allowed[route] = set()
            if route not in allowed:
                return 404, dict(headers, **{'Content-Type': 'application/json'}), b'{"error":"not_found"}'
            if set(query)-allowed[route]:
                raise ValueError('query')
            view = self.reader.view()
            data = dict(mode=view['mode'], state=view['state'])
            if route in ('portfolio', 'system'):
                data['data'] = view[route]
            elif route == 'analytics':
                data.update(data=view['daily'][-31:], total_days=len(view['daily']),
                            coverage='recorded UTC entry/settlement days; zero-activity days are not inferred',
                            pnl_definition='net completed-lifecycle outcomes assigned to settlement day; excludes open partial realizations and shared costs; not daily equity change')
            elif route == 'lanes':
                data['data'] = list(view['lanes'].values())
            elif route.startswith('lanes/'):
                data['data'] = view['lanes'][route[6:]]
            elif route.startswith('positions/'):
                found = [p for p in view['positions'] if p['id'] == unquote(route[10:])]
                if not found:
                    status, data = 404, dict(error='not_found')
                else:
                    data['data'] = found[0]
            elif route == 'equity':
                series, period = query.get('series', 'portfolio'), query.get('period', 'ALL')
                if series not in view['history'] or period not in PERIODS:
                    raise ValueError('chart_query')
                limit = int(query.get('limit', '240'))
                if not 2 <= limit <= 500:
                    raise ValueError('limit')
                points = view['history'][series]
                end = stamp(view['portfolio']['as_of']) if view['portfolio']['as_of'] else self.reader.clock()
                start = end-PERIODS[period] if PERIODS[period] else float('-inf')
                filtered = [p for p in points if stamp(p['at']) >= start]
                # Preserve actual samples. Never smooth, interpolate or bridge unknowns.
                shown = filtered[-limit:]
                data.update(data=shown, series=series, unit='USD equity' if series=='portfolio' else 'USD cumulative net P&L',
                            sample_count=len(filtered), displayed_count=len(shown), truncated=len(filtered)>limit,
                            reference='500.00' if series=='portfolio' else '0.00',
                            periods=[p for p, duration in PERIODS.items() if duration is None or points and end-stamp(points[0]['at']) >= duration])
            else:
                lane, outcome = query.get('lane'), query.get('outcome')
                if lane and lane not in LANES or outcome and outcome not in ('winner', 'loser', 'breakeven'):
                    raise ValueError('filter')
                limit, offset = int(query.get('limit', '25')), int(query.get('offset', '0'))
                if not 1 <= limit <= 100 or not 0 <= offset <= 5000:
                    raise ValueError('pagination')
                after = stamp(query['from']) if query.get('from') else float('-inf')
                before = stamp(query['to']) if query.get('to') else float('inf')
                if after > before:
                    raise ValueError('date_range')
                rows = [p for p in view['positions'] if p['state'] == ('OPEN' if route=='positions' else 'SETTLED')]
                rows = [p for p in rows if (not lane or p['lane']==lane)
                        and (not outcome or p['outcome']==outcome)
                        and query.get('q', '').casefold() in (p['asset']+' '+p['id']).casefold()
                        and query.get('strategy', '').casefold() in ((p['strategy_id'] or '')+' '+str(p['identities']['source_sha'] or '')).casefold()
                        and after <= stamp(p['settled_at'] or p['entered_at']) <= before]
                rows.sort(key=lambda p: (p['settled_at'] or p['entered_at'], p['id']), reverse=True)
                data.update(data=rows[offset:offset+limit], total=len(rows) if view['portfolio']['epoch'] else None,
                            offset=offset, limit=limit, next_offset=offset+limit if offset+limit<len(rows) else None,
                            as_of=view['portfolio']['as_of'])
        except (ValueError, TypeError, KeyError, OverflowError):
            status, data = 400, dict(error='invalid_request_or_source', state='FAIL_CLOSED')
        except OSError:
            status, data = 503, dict(error='local_state_unavailable', state='UNAVAILABLE')
        raw = json.dumps(data, separators=(',', ':'), allow_nan=False).encode()
        return status, dict(headers, **{'Content-Type': 'application/json'}), raw

    def serve(self, handler):
        result = self.response(handler.command, handler.path)
        if result is None:
            return False
        status, headers, body = result
        handler.send_response(status)
        for key, value in headers.items():
            handler.send_header(key, value)
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        if handler.command != 'HEAD':
            handler.wfile.write(body)
        return True
