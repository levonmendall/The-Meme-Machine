# Declared HTTP body completion and uncertainty

Base: integrated application `ae4d2429`. This correction changes only response
completion/accounting in the original operational Budget wrapper and isolated
parent HTTP transport. It does not activate head refresh or change transport
deadlines, provider limits, admission, financial state or native economic ACKs.

Both paths previously inferred complete EOF from a short/empty read without
checking the native HTTP response's remaining declared Content-Length.
`HTTPResponse.read(n)` can return a short body while `length` remains positive;
`read1(n)` can return an empty body in that same truncated state. In both cases,
the old receipt could release its unread reservation without uncertain debt.
A valid JSON envelope inside a truncated declared body could also be returned.

The shared `http_body_state` projection gives declared length precedence:

- Remaining length zero means complete, even when the caller requested exactly
  that many bytes. The parent stops before attempting another socket read on
  the now-closed native response.
- A positive remaining length plus transport EOF means incomplete. Both paths
  charge every returned body byte before refusing the response, retain
  `HTTPReceipt.eof=False`, and close the unread reservation as uncertain debt.
- A deliberately partial read remains open. A zero-sized read does not assert
  EOF or truncation. Responses without declared length retain the original
  buffered-short-read / read1-empty-read completion rules.
- Complete chunked buffered responses preserve their existing behavior. The
  parent still refuses chunked transport under its original deadline policy;
  this patch does not authorize its chunk-header read loop.

`tests.test_http_response_eof` passed 11 cases in 0.175 seconds using actual
`HTTPResponse`/`SocketIO`, an offline socket, original durable Budget and native
parent Governor/transport. Tests verify valid-JSON truncation is rejected,
partial bytes and uncertain debt remain exact, complete declared/unframed/
chunked behavior is preserved, empty truncation and intentional partial reads,
zero-sized reads, cleanup and the unchanged parent chunked refusal.

The two affected existing Budget and parent transport modules passed all 67
cases in 4.141 seconds under the official Scratch/network guard. No market
provider request, AWS operation or full release validation was performed.
