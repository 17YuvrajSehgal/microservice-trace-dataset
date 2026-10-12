#### What is tracing?
- Tracing is a way to follow one request as it moves thorugh the system.
- It shows us each step - how long each step took, and where something went wrong.
- The points we want to trace are called trace points.

##### Key terms:
- `Trace`: The full record of one request, from start to finish.
- `Trace ID`: A unique identifier given to the request.
- `Span`: One step inside a trace. For example, "charge the card" is one span.
- `Span ID`: A unique identifier given to the span.
- `Context Propagation`: The act of passing a trace ID from one service to the next.

#### Why do we need tracing?
- Helps us find slow steps.
- Helps us find services that failed.
- Helps us when the system has many small services (microservices). As one request may touch many services, so trace shows the full path.

#### How it is different from other telemetry?

#### When do we need tracing?
- When we want to optimize our application.
- Debugging.


#### Common tools for tracing:
- Jaeger & Zipkin (tools to store and view traces)
- OpenTelemetry (a standard way to collect traces)


#### EXAMPLE:
Here is a trace for the slow "Buy" request from before.

**Trace ID: a1b2c3**

```
Span                          Start     Duration
-----------------------------------------------------
Buy request (parent)          0 ms      2100 ms
  ├─ Check login              5 ms        40 ms
  ├─ Charge card              50 ms     1900 ms   <-- slow
  │    └─ Call bank API       60 ms     1850 ms
  ├─ Reduce stock             1960 ms     80 ms
  └─ Send confirmation        2045 ms     50 ms
```

**How to read it**

- The whole request took 2100 ms (about 2 seconds).
- The parent span is "Buy request". The others are its children.
- "Charge card" took 1900 ms. That is almost all of the time.
- Inside it, "Call bank API" took 1850 ms. This is the real problem.

**What it tells you**

The site is not slow because of login, stock, or email. The bank API is slow. Now you know where to look.

**How it looks as data**

Each span is stored as a small record. Here is one:

```json
{
  "trace_id": "a1b2c3",
  "span_id": "s4",
  "parent_span_id": "s2",
  "name": "Call bank API",
  "start_time": "10:32:00.060",
  "duration_ms": 1850,
  "status": "OK"
}
```

- `trace_id` is the same for every span in this request. It joins them together.
- `span_id` is the ID of this one step.
- `parent_span_id` points to the step that started this one. This is how the tree is built.

Tools like Jaeger draw this as a bar chart. Each bar is one span. A long bar means a slow step.