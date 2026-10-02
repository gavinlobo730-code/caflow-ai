# Finding one request — the id, the log line and what a person has to do

A CA who says "it failed at 11:05" can now be traced to one request. This page is how, and the steps that
only a person with the Render and Sentry dashboards can take (ops-11).

## What is wired

- **Every response carries `X-Request-ID`.** A caller may send one (support can ask a CA to, or a proxy may add
  one); it is used only if the WHOLE value is 8 to 64 letters, digits, `.`, `_` or `-` (a line break anywhere
  in it, the last character included, disqualifies it). Anything else is replaced by a generated
  16-character id and never written anywhere. The header is readable by the web app
  (`expose_headers`).
- **One line per request whose message is JSON**, on the logger `caflow.access`. The log's own format puts
  `LEVEL:logger:` in front of every message, so the physical line is
  `INFO:caflow.access:{"event":"request","request_id":"…","firm_id":"…","method":"GET","route":"/api/clients/{client_id}","status":200,"duration_ms":41.7}`
  (`WARNING` from a 5xx, never `ERROR`).
  `route` is the template the router matched, or `<unmatched>`; the path and the query string are never
  logged (a token can be in either). `firm_id` is the firm's internal id and is absent until the caller has
  been authenticated. There is no name, email, GSTIN, PAN, user id, IP address or header in it.
- **Every other log line written during the request carries `[request_id=… firm_id=…]`** after its message, so
  a traceback is found by the same id.
- **A server-side failure names the id in its message**: `Internal server error (reference 3f2a9c1b8d3e7a60)`.
  The body stays `{success, data, error}`; the id is inside `error`. The web app also appends the reference
  to any 5xx it reads off a response header.
- **Sentry events carry the tags `request_id` and `firm_id`.** Nothing that `send_default_pii` governs was
  turned on to do it.
- **A successful `/health` or `/ready` writes no line** (they are polled every few seconds); one that fails is
  logged. The id header is still returned.
- **gunicorn's own access line is off** (`--access-logfile` was removed from `apps/api/Dockerfile`): it was
  the raw request line, path and query string included, once per request.

## Finding a request

1. Get the id from the CA's screen (`… (reference 3f2a9c1b8d3e7a60)`), or from a browser's network panel
   (`X-Request-ID` on the failed response), or from Sentry (tag `request_id`).
2. In Render's log search for the id. The access line gives route, status and duration. If the request
   failed, the error record just before it carries the id too: its FIRST line ends `[request_id=… firm_id=…]`
   and the traceback follows on the lines after it, which do not repeat the id (search the id, then read down).
3. With no id, search `"status":500` (or `"status":5`) together with the firm's id and the time.

## What a person has to do

- **After the deploy**: `curl -i https://practicesync-api.onrender.com/health` and check an `x-request-id`
  header is present; then `curl -i -H 'X-Request-ID: my-trace-0001' …` and check the same value comes back.
  Search Render's log for `my-trace-0001`: a successful `/health` writes no line, so make the check against
  any route that does (an unmatched path is enough: `curl -i …/nothing-here` writes one line with
  `"route":"<unmatched>"`).
- **A log drain** (Render → Settings → Log Streams) if retention matters. Platform retention is limited and
  the exact figure is not recorded here; check it in the dashboard. Only the message is JSON, behind the fixed
  prefix `LEVEL:caflow.access:`, so a drain that indexes `request_id`, `firm_id`, `route` and `status` as fields
  has to skip that prefix (parse from the first `{`) or match the substring.
- **Sentry**: nothing to configure. To confirm, force an error in staging and look for the two tags.
