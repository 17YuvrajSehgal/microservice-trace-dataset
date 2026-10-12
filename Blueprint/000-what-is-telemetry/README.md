#### What is Telemetry
Telemetry is data that a system sends about itself – it tells us what the system is doing.

#### Why do we need Telemetry?
- We cannot watch everything in a system by looking at it.
- Telemetry helps us to see what is happening in a system, what is slow, broken, or busy.

#### Types of Telemetry
- `Logs`
  - Text records of events.
  - Example: "2026-10-05 10:32 User 42 failed to log in."
  - Good for: knowing exactly what happened at a point in time.

- `Metrics`
  - Numbers measured over time.
  - Example: CPU usage, memory usage, requests per second, error rate.
  - Good for: seeing the overall health and spotting trends.

- `Traces`
  - The path of one request across many services.
  - Good for: finding which step is slow or broken.


- Other:
  - `Events`: Records of something important that happened. For example, "user bought an item".
  - `Profiles`: how which lines of code use the most CPU or memory. Good for tuning speed.


#### How they work together

Let's say your site is slow.

- A **metric** shows that response time went up at 10:30.
- A **trace** shows that the payment step is the slow part.
- A **log** shows the error message from the payment service.

Each type answers a different question.

**Quick comparison**

| Type | Question it answers |
|---|---|
| Metrics | Is something wrong? |
| Traces | Where is it wrong? |
| Logs | Why is it wrong? |

**Common tool**

OpenTelemetry is a standard way to collect all of these types. Many tools can read its data.
