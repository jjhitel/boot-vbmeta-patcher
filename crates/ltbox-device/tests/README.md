# Transport fault tests

Run from the repository root; no attached device or network is required:

```text
cargo test -p ltbox-device --test firehose_faults
cargo test -p ltbox-device partition_flash
cargo test -p ltbox-device --test firehose_read
```

`firehose_faults.rs` calls the real qdl read/program functions through the
test-only `support::ScriptedChannel`. A script lists command writes, payload
writes, received byte fragments, I/O errors, EOF, and USB empty packets in wire
order. Unexpected I/O fails the test. A call budget catches accidental infinite
retry loops without hanging the suite. Change the script to place a fault at
the command ACK, payload, or final ACK boundary; assert both the returned error
and the bytes/progress or remaining operations that matter for that scenario.

`src/edl/partition_flash_tests.rs` exercises the real `EdlSession` batch API
using GPT images and a transport that responds to the actual Firehose XML.
Its `Fault` enum targets the first or second program operation. Tests verify
that preflight failures issue no program commands, write failures retain the
start notification, and later partitions remain untouched. The delayed-ACK
case uses a channel gate with bounded waits, rather than a timing-based sleep:
it checks the recorded events before releasing the ACK, then joins the worker.

The cases cover fragmented XML/data, short payload writes, transport disconnects,
NAKs, missing/truncated ACKs, timeouts, EOF, USB ZLPs, and interrupted reads.
Greeting tests preserve loaders that end complete startup logs with a timeout;
that exception must never turn a command's missing ACK into success.

These tests model EDL/Firehose behavior. They do not emulate USB enumeration,
physical device replacement across ADB/Fastboot/EDL, bootloader persistence, or
recovery on real hardware. Cross-mode target identity remains a separate policy
and testing task. A completed payload progress counter does not prove success:
the final ACK is still required.
