use super::{EdlSession, PartitionFlash, PartitionFlashError};
use qdl::types::{FirehoseConfiguration, QdlBackend, QdlDevice, QdlReadWrite};
use std::io::{self, BufRead, Cursor, Read, Write};
use std::path::PathBuf;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU64, Ordering},
};

const ACK: &[u8] = b"<data><response value=\"ACK\" /></data>";
const LABELS: [&str; 3] = ["vendor_boot_a", "vbmeta_a", "boot_a"];
const STARTS: [u64; 3] = [64, 80, 96];
const CAPACITIES: [u64; 3] = [2, 4, 2];

#[derive(Debug, PartialEq)]
enum Event {
    Partition(String),
    Start,
    Program(u64, usize),
    Payload(Vec<u8>),
}

type Events = Arc<Mutex<Vec<Event>>>;

/// Respond to actual Firehose read/program XML, including ACK/raw-data/ACK.
struct Transport {
    disk: Vec<u8>,
    sector_size: usize,
    responses: Cursor<Vec<u8>>,
    events: Events,
    program_count: usize,
    fail_program: Option<usize>,
    payload_remaining: usize,
}

impl Read for Transport {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        self.responses.read(buf)
    }
}

impl BufRead for Transport {
    fn fill_buf(&mut self) -> io::Result<&[u8]> {
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
            self.events
                .lock()
                .unwrap()
                .push(Event::Payload(bytes.to_vec()));
            self.payload_remaining -= bytes.len();
            if self.payload_remaining == 0 {
                self.responses = Cursor::new(ACK.to_vec());
            }
            return Ok(bytes.len());
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
                if self.fail_program == Some(self.program_count) {
                    return Err(io::ErrorKind::BrokenPipe.into());
                }
                self.responses = Cursor::new(ACK.to_vec());
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
    fn new(sector_size: usize, omit_second: bool, fail_program: Option<usize>) -> Self {
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
            fail_program,
            payload_remaining: 0,
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
        let mut fixture = Fixture::new(512, false, Some(fail_program));
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
