from logkit import templating as T

GOKIT = ("ts=2026-09-05T15:18:46.94Z caller=logging.go:56 method=Get id=03fe sock=03fe "
         "err=null took=1.2ms")
GOKIT_ERR = ('ts=2026-09-05T15:21:00Z caller=logging.go:56 method=Get id=03fe sock=03fe '
             'err="database connection refused" took=3s')


def test_logfmt_keeps_code_keys_and_masks_values():
    assert T.template(GOKIT) == "caller=logging.go:56 method=Get sock=<v> err=null"


def test_kept_keys_mask_numbers_but_keep_outcomes():
    a = T.template("ts=x caller=logging.go:27 method=List result=7 err=null took=1ms")
    b = T.template("ts=x caller=logging.go:27 method=List result=0 err=null took=1ms")
    assert a == b and "result=<n>" in a
    assert "result=false" in T.template("ts=x caller=logging.go:29 method=Authorise result=false took=1ms")


def test_a_failing_request_is_a_different_template():
    assert T.template(GOKIT) != T.template(GOKIT_ERR)
    assert "err=database connection refused" in T.template(GOKIT_ERR)


def test_repeats_share_a_template():
    a = T.template("Opened connection [connectionId{localValue:72, serverValue:83}] to carts-db:27017")
    b = T.template("Opened connection [connectionId{localValue:9, serverValue:11}] to carts-db:27017")
    assert a == b


def test_levels():
    assert T.level(GOKIT) == 1.0
    assert T.level(GOKIT_ERR) == 3.0
    assert T.level('time="x" level=warning msg="Error forwarding"') == 2.0
    assert T.level("2026-09-05T15:19:47.900+0000 E NETWORK  [thread1] x") == 3.0
    assert T.level("2026-09-05 15:18:47.970  INFO [orders,a,b,false] ok") == 1.0
    assert T.level("***aborting after fassert() failure") == 4.0
    assert T.level("Error: connect ECONNREFUSED 1.2.3.4:80") == 3.0


def test_frames_and_generic():
    assert T.is_frame("\tat org.x.SubscriptionState.assignedState(SubscriptionState.java:1)")
    assert T.is_frame("    at Request.handler (/app/node_modules/x.js:12:5)")
    assert not T.is_frame("Order response: ok")
    assert T.is_generic("request timed out after 3000 ms, retrying")
    assert not T.is_generic("Failed to write to interim file")
