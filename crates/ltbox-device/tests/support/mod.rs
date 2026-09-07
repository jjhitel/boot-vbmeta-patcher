use qdl::types::{FirehoseConfiguration, QdlBackend, QdlChan};
use std::{
    collections::VecDeque,
    io::{self, BufRead, Read, Write},
};

#[derive(Debug)]
pub enum Step {
    Bytes(Vec<u8>),
    Error(io::ErrorKind),
    Eof,
    EmptyPacket,
    Command(&'static str, io::Result<usize>),
    Payload(Vec<u8>, io::Result<usize>),
}

pub fn bytes(value: &[u8]) -> Step {
    Step::Bytes(value.to_vec())
}
pub fn command(name: &'static str) -> Step {
    Step::Command(name, Ok(usize::MAX))
}
pub fn payload(value: &[u8]) -> Step {
    Step::Payload(value.to_vec(), Ok(value.len()))
}

/// A synchronous wire script. Each fragment is exposed separately; EOF persists.
/// The guard converts an accidental retry loop into an identifiable test failure.
pub struct ScriptedChannel {
    steps: VecDeque<Step>,
    config: FirehoseConfiguration,
    pub events: Vec<String>,
    calls: usize,
}
impl ScriptedChannel {
    pub fn new(steps: Vec<Step>) -> Self {
        Self {
            steps: steps.into(),
            config: FirehoseConfiguration {
                storage_sector_size: 4,
                send_buffer_size: 8,
                recv_buffer_size: 8,
                backend: QdlBackend::Serial,
                ..Default::default()
            },
            events: Vec::new(),
            calls: 0,
        }
    }
    fn tick(&mut self, event: &str) -> io::Result<()> {
        self.calls += 1;
        self.events.push(event.into());
        if self.calls > 64 {
            return Err(io::Error::other("script I/O call guard exhausted"));
        }
        Ok(())
    }
    pub fn assert_finished(&self) {
        assert!(self.steps.is_empty(), "unconsumed script: {:?}", self.steps);
    }
}
impl BufRead for ScriptedChannel {
    fn fill_buf(&mut self) -> io::Result<&[u8]> {
        self.tick("fill_buf")?;
        if matches!(self.steps.front(), Some(Step::EmptyPacket)) {
            self.steps.pop_front();
            return Ok(&[]);
        }
        if matches!(self.steps.front(), Some(Step::Error(_))) {
            let Some(Step::Error(kind)) = self.steps.pop_front() else {
                unreachable!()
            };
            return Err(io::Error::new(kind, "injected transport fault"));
        }
        match self.steps.front() {
            Some(Step::Bytes(data)) => Ok(data),
            Some(Step::Eof) => Ok(&[]),
            other => panic!("unexpected read: {other:?}"),
        }
    }
    fn consume(&mut self, amount: usize) {
        if amount == 0 {
            return;
        }
        let Some(Step::Bytes(data)) = self.steps.front_mut() else {
            panic!("consume without bytes")
        };
        assert!(amount <= data.len());
        data.drain(..amount);
        if data.is_empty() {
            self.steps.pop_front();
        }
    }
}
impl Read for ScriptedChannel {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        self.events.push(format!("read {}", buf.len()));
        if buf.is_empty() {
            self.tick("empty read")?;
            return Ok(0);
        }
        let data = self.fill_buf()?;
        let n = data.len().min(buf.len());
        buf[..n].copy_from_slice(&data[..n]);
        self.consume(n);
        Ok(n)
    }
}
impl Write for ScriptedChannel {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.tick("write")?;
        match self.steps.pop_front().expect("unexpected write") {
            Step::Command(name, result) => {
                let xml = std::str::from_utf8(buf).expect("command UTF-8");
                let doc = roxmltree::Document::parse(xml).expect("command XML");
                let root = doc.root_element();
                assert_eq!(root.tag_name().name(), "data");
                let nodes: Vec<_> = root.children().filter(|n| n.is_element()).collect();
                assert_eq!(nodes.len(), 1);
                let node = nodes[0];
                assert_eq!(node.tag_name().name(), name);
                let mut expected = vec![
                    ("SECTOR_SIZE_IN_BYTES", "4"),
                    ("num_partition_sectors", "2"),
                    ("slot", "0"),
                    ("physical_partition_number", "0"),
                    ("start_sector", "0"),
                ];
                if name == "program" {
                    expected.push(("read_back_verify", "0"));
                }
                assert_eq!(node.attributes().len(), expected.len());
                for (key, value) in expected {
                    assert_eq!(node.attribute(key), Some(value), "attribute {key}");
                }
                self.events.push(format!("command {name}"));
                result.map(|n| n.min(buf.len()))
            }
            Step::Payload(expected, result) => {
                assert_eq!(buf, expected);
                self.events.push(format!("payload {}", buf.len()));
                result
            }
            other => panic!("unexpected write during {other:?}"),
        }
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl QdlChan for ScriptedChannel {
    fn fh_config(&self) -> &FirehoseConfiguration {
        &self.config
    }
    fn mut_fh_config(&mut self) -> &mut FirehoseConfiguration {
        &mut self.config
    }
}
