use super::{EdlSession, PartitionFlash, PartitionFlashError};
use qdl::types::{FirehoseConfiguration, QdlBackend, QdlDevice, QdlReadWrite};
use std::io::{self, BufRead, Cursor, Read, Write};
use std::path::PathBuf;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU64, Ordering},
    mpsc,
};

const ACK: &[u8] = b"<data><response value=\"ACK\" /></data>";
const NAK: &[u8] = b"<data><response value=\"NAK\" /></data>";
const LABELS: [&str; 3] = ["vendor_boot_a", "vbmeta_a", "boot_a"];
const STARTS: [u64; 3] = [64, 80, 96];
const CAPACITIES: [u64; 3] = [2, 4, 2];

#[derive(Clone, Debug, PartialEq)]
enum Event {
    Partition(String),
    Start,
    Program(u64, usize),
    Payload(Vec<u8>),
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Fault {
    CommandWrite(usize),
    PartialPayload(usize),
    DisconnectedPayload(usize),
    CommandNak(usize),
    CommandTimeout(usize),
    FinalNak(usize),
    FinalTimeout(usize),
    GptDisconnect,
    GptTimeout,
}

struct AckGate {
    entered: mpsc::Sender<()>,
    release: Mutex<mpsc::Receiver<()>>,
}

type Events = Arc<Mutex<Vec<Event>>>;

/// Respond to actual Firehose read/program XML, including ACK/raw-data/ACK.
struct Transport {
    disk: Vec<u8>,
    sector_size: usize,
    responses: Cursor<Vec<u8>>,
    events: Events,
    program_count: usize,
    fault: Option<Fault>,
    payload_remaining: usize,
    final_ack_gate: Option<AckGate>,
}

impl Read for Transport {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        self.responses.read(buf)
    }
}

impl BufRead for Transport {
    fn fill_buf(&mut self) -> io::Result<&[u8]> {
        if self.program_count == 1
            && self.payload_remaining == 0
            && let Some(gate) = self.final_ack_gate.take()
        {
            gate.entered
                .send(())
                .map_err(|_| io::ErrorKind::BrokenPipe)?;
            gate.release
                .lock()
                .unwrap()
                .recv_timeout(std::time::Duration::from_secs(5))
                .map_err(|_| io::ErrorKind::TimedOut)?;
        }
        let bytes = self.responses.fill_buf()?;
        if bytes.is_empty() {
            return Err(io::ErrorKind::TimedOut.into());
        }
        Ok(bytes)
    }

    fn consume(&mut self, amount: usize) {
        self.responses.consume(amount);
    }
}

impl Write for Transport {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.payload_remaining > 0 {
            assert!(bytes.len() <= self.payload_remaining);
            if self.fault == Some(Fault::DisconnectedPayload(self.program_count)) {
                return Err(io::ErrorKind::BrokenPipe.into());
            }
            let accepted = if self.fault == Some(Fault::PartialPayload(self.program_count)) {
                137
            } else {
                bytes.len()
            };
            self.events
                .lock()
                .unwrap()
                .push(Event::Payload(bytes[..accepted].to_vec()));
            self.payload_remaining -= accepted;
            if self.payload_remaining == 0 {
                self.responses = Cursor::new(match self.fault {
                    Some(Fault::FinalNak(n)) if n == self.program_count => NAK.to_vec(),
                    Some(Fault::FinalTimeout(n)) if n == self.program_count => Vec::new(),
                    _ => ACK.to_vec(),
                });
            }
            return Ok(accepted);
        }

        assert_eq!(
            self.responses.position() as usize,
            self.responses.get_ref().len()
        );
        let xml = std::str::from_utf8(bytes).unwrap();
        let document = roxmltree::Document::parse(xml).unwrap();
        let command = document.root_element().first_element_child().unwrap();
        match command.tag_name().name() {
            "read" => {
                match self.fault {
                    Some(Fault::GptDisconnect) => return Err(io::ErrorKind::BrokenPipe.into()),
                    Some(Fault::GptTimeout) => return Ok(bytes.len()),
                    _ => {}
                }
                let start: usize = command.attribute("start_sector").unwrap().parse().unwrap();
                let sectors: usize = command
                    .attribute("num_partition_sectors")
                    .unwrap()
                    .parse()
                    .unwrap();
                let mut response = ACK.to_vec();
                response.extend_from_slice(
                    &self.disk[start * self.sector_size..(start + sectors) * self.sector_size],
                );
                response.extend_from_slice(ACK);
                self.responses = Cursor::new(response);
            }
            "program" => {
                let start = command.attribute("start_sector").unwrap().parse().unwrap();
                let sectors = command
                    .attribute("num_partition_sectors")
                    .unwrap()
                    .parse()
                    .unwrap();
                self.events
                    .lock()
                    .unwrap()
                    .push(Event::Program(start, sectors));
                self.program_count += 1;
                if self.fault == Some(Fault::CommandWrite(self.program_count)) {
                    return Err(io::ErrorKind::BrokenPipe.into());
                }
                self.responses = Cursor::new(match self.fault {
                    Some(Fault::CommandNak(n)) if n == self.program_count => NAK.to_vec(),
                    Some(Fault::CommandTimeout(n)) if n == self.program_count => Vec::new(),
                    _ => ACK.to_vec(),
                });
                self.payload_remaining = sectors * self.sector_size;
            }
            other => panic!("unexpected Firehose command: {other}"),
        }
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl QdlReadWrite for Transport {}

struct Fixture {
    dir: PathBuf,
    images: [PathBuf; 3],
    session: EdlSession,
    events: Events,
}

impl Fixture {
    fn new(sector_size: usize, omit_second: bool, fault: Option<Fault>) -> Self {
        Self::with_gate(sector_size, omit_second, fault, None)
    }

    fn with_gate(
        sector_size: usize,
        omit_second: bool,
        fault: Option<Fault>,
        final_ack_gate: Option<AckGate>,
    ) -> Self {
        static SEQUENCE: AtomicU64 = AtomicU64::new(0);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!(
            "ltbox-partition-flash-{}-{nanos}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&dir).unwrap();
        let images = LABELS.map(|label| dir.join(format!("{label}.img")));
        for (index, image) in images.iter().enumerate() {
            std::fs::write(image, vec![0xa1 + index as u8; sector_size + 1]).unwrap();
        }

        let mut disk = Cursor::new(vec![0; sector_size * 256]);
        let mut gpt = gptman::GPT::new_from(&mut disk, sector_size as u64, [0x11; 16]).unwrap();
        for index in 0..3 {
            if omit_second && index == 1 {
                continue;
            }
            gpt[index as u32 + 1] = gptman::GPTPartitionEntry {
                partition_type_guid: [0x22; 16],
                unique_partition_guid: [index as u8 + 1; 16],
                starting_lba: STARTS[index],
                ending_lba: STARTS[index] + CAPACITIES[index] - 1,
                attribute_bits: 0,
                partition_name: LABELS[index].into(),
            };
        }
        gpt.write_into(&mut disk).unwrap();
        let events = Events::default();
        let transport = Transport {
            disk: disk.into_inner(),
            sector_size,
            responses: Cursor::new(Vec::new()),
            events: Arc::clone(&events),
            program_count: 0,
            fault,
            payload_remaining: 0,
            final_ack_gate,
        };
        let session = EdlSession {
            dev: QdlDevice {
                rw: Box::new(transport),
                fh_cfg: FirehoseConfiguration {
                    storage_sector_size: sector_size,
                    send_buffer_size: sector_size * 2,
                    backend: QdlBackend::Serial,
                    ..FirehoseConfiguration::default()
                },
                reset_on_drop: false,
            },
        };
        Self {
            dir,
            images,
            session,
            events,
        }
    }

    fn flash(&mut self, count: usize) -> Result<(), PartitionFlashError> {
        let requests: Vec<_> = (0..count)
            .map(|index| PartitionFlash {
                label: LABELS[index],
                image: &self.images[index],
                slot: 0,
                lun: 4,
            })
            .collect();
        let events = &self.events;
        self.session.flash_partition_batch(
            &requests,
            &mut Vec::new(),
            |label, _, _| events.lock().unwrap().push(Event::Partition(label.into())),
            || events.lock().unwrap().push(Event::Start),
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        for image in &self.images {
            let _ = std::fs::remove_file(image);
        }
        let _ = std::fs::remove_dir(&self.dir);
    }
}

#[test]
fn second_image_preflight_failure_prevents_all_programs_and_notifications() {
    for invalid in ["missing", "empty", "oversized"] {
        let mut fixture = Fixture::new(512, false, None);
        match invalid {
            "missing" => std::fs::remove_file(&fixture.images[1]).unwrap(),
            "empty" => std::fs::write(&fixture.images[1], []).unwrap(),
            // One byte over capacity requires another full sector on the wire.
            "oversized" => std::fs::write(&fixture.images[1], vec![1; 4 * 512 + 1]).unwrap(),
            _ => unreachable!(),
        }
        let error = fixture.flash(2).unwrap_err();
        assert_eq!(error.partition, LABELS[1], "{invalid}");
        assert!(fixture.events.lock().unwrap().is_empty(), "{invalid}");
    }
}

#[test]
fn missing_second_target_prevents_all_programs_and_notifications() {
    let mut fixture = Fixture::new(512, true, None);
    let error = fixture.flash(2).unwrap_err();
    assert_eq!(error.partition, LABELS[1]);
    assert!(matches!(
        error.source,
        super::EdlError::PartitionNotFound(_)
    ));
    assert!(fixture.events.lock().unwrap().is_empty());
}

#[test]
fn valid_pair_uses_actual_capacity_and_rounded_transfer_lengths_in_order() {
    for sector_size in [512, 4096] {
        let mut fixture = Fixture::new(sector_size, false, None);
        fixture.flash(2).unwrap();
        let mut expected = Vec::new();
        for index in 0..2 {
            let mut padded = vec![0xa1 + index as u8; sector_size + 1];
            padded.resize(sector_size * 2, 0);
            expected.extend([
                Event::Partition(LABELS[index].into()),
                Event::Start,
                Event::Program(STARTS[index], 2),
                Event::Payload(padded),
            ]);
        }
        assert_eq!(*fixture.events.lock().unwrap(), expected);
    }
}

#[test]
fn failed_program_retains_start_notification_and_stops_remaining_writes() {
    for fail_program in [1, 2] {
        let mut fixture = Fixture::new(512, false, Some(Fault::CommandWrite(fail_program)));
        let error = fixture.flash(3).unwrap_err();
        assert_eq!(error.partition, LABELS[fail_program - 1]);
        let events = fixture.events.lock().unwrap();
        assert_eq!(
            events
                .iter()
                .filter(|event| matches!(event, Event::Start))
                .count(),
            fail_program
        );
        let programs: Vec<_> = events
            .iter()
            .filter_map(|event| match event {
                Event::Program(start, _) => Some(*start),
                _ => None,
            })
            .collect();
        assert_eq!(programs, STARTS[..fail_program]);
        assert_eq!(
            events.last(),
            Some(&Event::Program(STARTS[fail_program - 1], 2))
        );
    }
}

fn expected_program(index: usize, payload_bytes: Option<usize>) -> Vec<Event> {
    let mut events = vec![
        Event::Partition(LABELS[index].into()),
        Event::Start,
        Event::Program(STARTS[index], 2),
    ];
    if let Some(length) = payload_bytes {
        let mut payload = vec![0xa1 + index as u8; 513];
        payload.resize(1024, 0);
        payload.truncate(length);
        events.push(Event::Payload(payload));
    }
    events
}

#[test]
fn transport_faults_retain_attempted_partition_and_stop_batch() {
    for operation in [1, 2] {
        for (fault, payload_bytes) in [
            (Fault::PartialPayload(operation), Some(137)),
            (Fault::DisconnectedPayload(operation), None),
            (Fault::CommandNak(operation), None),
            (Fault::CommandTimeout(operation), None),
            (Fault::FinalNak(operation), Some(1024)),
            (Fault::FinalTimeout(operation), Some(1024)),
        ] {
            let mut fixture = Fixture::new(512, false, Some(fault));
            let error = fixture.flash(3).unwrap_err();
            assert_eq!(error.partition, LABELS[operation - 1], "{fault:?}");
            let mut expected = Vec::new();
            for index in 0..operation - 1 {
                expected.extend(expected_program(index, Some(1024)));
            }
            expected.extend(expected_program(operation - 1, payload_bytes));
            assert_eq!(*fixture.events.lock().unwrap(), expected, "{fault:?}");
        }
    }
}

#[test]
fn gpt_transport_faults_prevent_all_write_starts_and_programs() {
    for fault in [Fault::GptDisconnect, Fault::GptTimeout] {
        let mut fixture = Fixture::new(512, false, Some(fault));
        let error = fixture.flash(3).unwrap_err();
        assert_eq!(error.partition, LABELS[0], "{fault:?}");
        assert!(fixture.events.lock().unwrap().is_empty(), "{fault:?}");
    }
}

#[test]
fn delayed_final_ack_blocks_next_partition_until_released() {
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let mut fixture = Fixture::with_gate(
        512,
        false,
        None,
        Some(AckGate {
            entered: entered_tx,
            release: Mutex::new(release_rx),
        }),
    );
    let events = Arc::clone(&fixture.events);
    let worker = std::thread::spawn(move || fixture.flash(2));
    let entered = entered_rx.recv_timeout(std::time::Duration::from_secs(5));
    // Capture before release, but always release and join before asserting so
    // a failed assertion cannot strand a worker waiting for the test thread.
    let while_waiting = events.lock().unwrap().clone();
    let release = release_tx.send(());
    let result = worker.join();
    entered.expect("worker must reach first final ACK");
    release.expect("worker must still be waiting for ACK release");
    result.unwrap().unwrap();
    assert_eq!(while_waiting, expected_program(0, Some(1024)));
    let mut expected = expected_program(0, Some(1024));
    expected.extend(expected_program(1, Some(1024)));
    assert_eq!(*events.lock().unwrap(), expected);
}
