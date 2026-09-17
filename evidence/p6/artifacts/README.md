# Captured artifacts

These logs are redacted outputs from actual replay runs. They were captured
against product SHA
`2710abb4e10d1ac473f007e94f00001d267a77ea` with the evidence replay scripts at
capture SHA `f5b0fd601dcbe7bb5ae28b7e79f1c8a6d7ccb25f`. The evidence branch may
gain later documentation/artifact commits; those commits are not product SHAs
under test.

`$CHECKOUT` and `$TESTROOT` are placeholders used to remove private absolute
paths from logs. The matrix records the real checkout cwd and the scripts create
all runtime roots under a disposable temporary directory. UUID entry/event
identifiers are generated test values; no credentials, tokens, customer data,
or host configuration from a real user directory is included.

`full-suite.log` records the final landed product test suite: 94 tests passed.
The route-specific logs retain expected intermediate nonzero exits, such as
restore collision exit `3`, alongside the final successful replay marker.
