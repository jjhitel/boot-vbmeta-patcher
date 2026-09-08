mod support;
use std::io::{self, Cursor};
use support::{ScriptedChannel, Step, bytes, command, payload};
const ACK: &[u8] = b"<data><response value=\"ACK\"/></data>";
const NAK: &[u8] = b"<data><response value=\"NAK\"/></data>";
const DATA: &[u8] = b"abcdefgh";

fn program(channel: &mut ScriptedChannel) -> (anyhow::Result<()>, Vec<(u64, u64)>) {
    let mut progress = Vec::new();
    let mut starts = 0;
    let result = qdl::firehose_program_storage_with_callbacks(
        channel,
        &mut Cursor::new(DATA),
        "test",
        2,
        0,
        0,
        "0",
        |done, total| progress.push((done, total)),
        || starts += 1,
    );
    assert_eq!(starts, 1);
    (result, progress)
}
fn read(channel: &mut ScriptedChannel) -> anyhow::Result<Vec<u8>> {
    let mut out = Vec::new();
    qdl::firehose_read_storage(channel, &mut out, 2, 0, 0, 0)?;
    Ok(out)
}
fn assert_rejected(result: anyhow::Result<impl std::fmt::Debug>) {
    let error = result.expect_err("missing ACK or incomplete transfer must fail");
    assert!(
        !format!("{error:#}").contains("guard exhausted"),
        "operation failed only because the fixture stopped an infinite loop: {error:#}"
    );
}
#[test]
fn fragmented_program_acks_preserve_progress() {
    let mut ch = ScriptedChannel::new(vec![
        command("program"),
        bytes(&ACK[..13]),
        bytes(&ACK[13..]),
        payload(DATA),
        bytes(&ACK[..29]),
        bytes(&ACK[29..]),
    ]);
    let (result, progress) = program(&mut ch);
    result.unwrap();
    assert_eq!(progress, [(0, 8), (8, 8)]);
    ch.assert_finished();
}
#[test]
fn fragmented_read_xml_and_raw_payload_preserve_bytes() {
    let mut ch = ScriptedChannel::new(vec![
        command("read"),
        bytes(&ACK[..8]),
        bytes(&ACK[8..]),
        bytes(&DATA[..1]),
        bytes(&DATA[1..5]),
        bytes(&DATA[5..]),
        bytes(&ACK[..30]),
        bytes(&ACK[30..]),
    ]);
    assert_eq!(read(&mut ch).unwrap(), DATA);
    ch.assert_finished();
}
#[test]
fn partial_program_payload_write_never_reports_completion() {
    let mut ch = ScriptedChannel::new(vec![
        command("program"),
        bytes(ACK),
        Step::Payload(DATA.to_vec(), Ok(3)),
    ]);
    let (result, progress) = program(&mut ch);
    assert_rejected(result);
    assert_eq!(progress, [(0, 8)]);
    ch.assert_finished();
}
#[test]
fn command_and_payload_disconnects_propagate() {
    for operation in ["program", "read"] {
        let mut ch = ScriptedChannel::new(vec![Step::Command(
            operation,
            Err(io::Error::new(io::ErrorKind::BrokenPipe, "disconnected")),
        )]);
        let result = if operation == "program" {
            program(&mut ch).0
        } else {
            read(&mut ch).map(|_| ())
        };
        assert_eq!(
            result
                .unwrap_err()
                .downcast_ref::<io::Error>()
                .unwrap()
                .kind(),
            io::ErrorKind::BrokenPipe
        );
        ch.assert_finished();
    }
    let mut ch = ScriptedChannel::new(vec![
        command("program"),
        bytes(ACK),
        Step::Payload(
            DATA.to_vec(),
            Err(io::Error::new(io::ErrorKind::BrokenPipe, "disconnected")),
        ),
    ]);
    let (result, progress) = program(&mut ch);
    assert_rejected(result);
    assert_eq!(progress, [(0, 8)]);
    let mut ch = ScriptedChannel::new(vec![
        command("read"),
        bytes(ACK),
        bytes(&DATA[..3]),
        Step::Error(io::ErrorKind::ConnectionReset),
    ]);
    assert_rejected(read(&mut ch));
    ch.assert_finished();
}
#[test]
fn command_and_final_naks_reject_both_operations() {
    for operation in ["program", "read"] {
        for final_ack in [false, true] {
            let mut steps = vec![command(operation)];
            if final_ack {
                steps.extend([
                    bytes(ACK),
                    if operation == "program" {
                        payload(DATA)
                    } else {
                        bytes(DATA)
                    },
                ]);
            }
            steps.push(bytes(NAK));
            let mut ch = ScriptedChannel::new(steps);
            assert_rejected(if operation == "program" {
                program(&mut ch).0
            } else {
                read(&mut ch).map(|_| ())
            });
            ch.assert_finished();
        }
    }
}
fn missing_ack(operation: &'static str, prefix: &[u8], final_ack: bool) {
    let mut steps = vec![command(operation)];
    if final_ack {
        steps.extend([
            bytes(ACK),
            if operation == "program" {
                payload(DATA)
            } else {
                bytes(DATA)
            },
        ]);
    }
    if !prefix.is_empty() {
        steps.push(bytes(prefix));
    }
    steps.push(Step::Error(io::ErrorKind::TimedOut));
    // If a command timeout is wrongly accepted, allow the transfer to expose false success.
    if !final_ack {
        steps.extend([
            if operation == "program" {
                payload(DATA)
            } else {
                bytes(DATA)
            },
            bytes(ACK),
        ]);
    }
    let mut ch = ScriptedChannel::new(steps);
    assert_rejected(if operation == "program" {
        program(&mut ch).0
    } else {
        read(&mut ch).map(|_| ())
    });
}
#[test]
fn no_response_timeout_rejects_both_ack_phases() {
    for op in ["program", "read"] {
        for final_ack in [false, true] {
            missing_ack(op, b"", final_ack);
        }
    }
}
#[test]
fn truncated_ack_then_timeout_is_not_ack() {
    for op in ["program", "read"] {
        for final_ack in [false, true] {
            missing_ack(op, b"<data><response value=\"ACK\"/>", final_ack);
        }
    }
}
#[test]
fn log_only_then_timeout_is_not_ack() {
    for op in ["program", "read"] {
        for final_ack in [false, true] {
            missing_ack(op, b"<data><log value=\"waiting\"/></data>", final_ack);
        }
    }
}
#[test]
fn greeting_end_log_is_not_command_ack() {
    missing_ack(
        "program",
        b"<data><log value=\"INFO: End of supported functions\"/></data>",
        true,
    );
}
#[test]
fn eof_during_ack_is_rejected_without_retry_loop() {
    let mut ch = ScriptedChannel::new(vec![command("program"), Step::Eof]);
    assert_rejected(program(&mut ch).0);
}
#[test]
fn eof_during_raw_read_is_rejected_without_retry_loop() {
    let mut ch = ScriptedChannel::new(vec![
        command("read"),
        bytes(ACK),
        bytes(&DATA[..3]),
        Step::Eof,
    ]);
    assert_rejected(read(&mut ch));
}

#[test]
fn usb_empty_packet_between_raw_fragments_is_accepted() {
    use qdl::types::{QdlBackend, QdlChan};
    let mut ch = ScriptedChannel::new(vec![
        command("read"),
        bytes(ACK),
        bytes(&DATA[..3]),
        Step::EmptyPacket,
        bytes(&DATA[3..]),
        bytes(ACK),
    ]);
    ch.mut_fh_config().backend = QdlBackend::Usb;
    assert_eq!(read(&mut ch).unwrap(), DATA);
    ch.assert_finished();
}

#[test]
fn usb_empty_packet_before_ack_is_accepted() {
    use qdl::types::{QdlBackend, QdlChan};
    let mut ch = ScriptedChannel::new(vec![
        command("program"),
        Step::EmptyPacket,
        bytes(ACK),
        payload(DATA),
        bytes(ACK),
    ]);
    ch.mut_fh_config().backend = QdlBackend::Usb;
    program(&mut ch).0.unwrap();
    ch.assert_finished();
}

#[test]
fn repeated_usb_empty_packets_are_rejected() {
    use qdl::types::{QdlBackend, QdlChan};
    for raw in [false, true] {
        let mut steps = vec![command("read")];
        if raw {
            steps.push(bytes(ACK));
        }
        steps.push(Step::Eof);
        let mut ch = ScriptedChannel::new(steps);
        ch.mut_fh_config().backend = QdlBackend::Usb;
        assert_rejected(read(&mut ch));
    }
}

#[test]
fn interrupted_raw_read_retries_without_losing_bytes() {
    let mut ch = ScriptedChannel::new(vec![
        command("read"),
        bytes(ACK),
        bytes(&DATA[..3]),
        Step::Error(io::ErrorKind::Interrupted),
        bytes(&DATA[3..]),
        bytes(ACK),
    ]);
    assert_eq!(read(&mut ch).unwrap(), DATA);
    ch.assert_finished();
}

#[test]
fn greeting_complete_log_allows_timeout_without_command_ack() {
    for suffix in ["", "\r\n", " \t\n"] {
        let log = format!("<data><log value=\"hello\"/></data>{suffix}");
        let mut ch = ScriptedChannel::new(vec![
            bytes(log.as_bytes()),
            Step::Error(io::ErrorKind::TimedOut),
        ]);
        qdl::firehose_read_greeting(&mut ch).unwrap();
        ch.assert_finished();
    }
}

#[test]
fn greeting_end_marker_completes_without_timeout() {
    let mut ch = ScriptedChannel::new(vec![bytes(
        b"<data><log value=\"INFO: End of supported functions\"/></data>",
    )]);
    qdl::firehose_read_greeting(&mut ch).unwrap();
    ch.assert_finished();
}

#[test]
fn greeting_partial_xml_before_timeout_is_rejected() {
    let mut ch = ScriptedChannel::new(vec![
        bytes(b"<data><log value=\"hello\"/></data>"),
        bytes(b"<data><log"),
        Step::Error(io::ErrorKind::TimedOut),
    ]);
    assert_rejected(qdl::firehose_read_greeting(&mut ch));
    ch.assert_finished();
}
