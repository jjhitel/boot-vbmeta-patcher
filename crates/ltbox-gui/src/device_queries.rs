//! Session caches and request ownership for device polling and Lenovo lookups.
use std::collections::{HashMap, VecDeque};

use crate::{Message, QfilPopupState};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) enum LookupKind {
    Info,
    Ota,
    Qfil,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{App, ConnectionStatus, DeviceInfoState, DevicePollResult};

    fn polled(app: &mut App, serial: &str, status: ConnectionStatus) {
        let _ = app.update(Message::DevicePolled(DevicePollResult {
            status,
            serial: serial.into(),
            ..Default::default()
        }));
    }

    #[test]
    fn older_retry_and_old_device_failures_cannot_replace_current_popup() {
        let mut app = App::default();
        polled(&mut app, "A", ConnectionStatus::Fastboot);
        app.device_info_popup = Some(("A".into(), DeviceInfoState::Loading));
        let old = app.queries.start_lookup(LookupKind::Info);
        let retry = app.queries.start_lookup(LookupKind::Info);
        let error = |token, serial: &str, detail: &str| {
            Message::DeviceLookupEvent(
                token,
                Box::new(Message::DeviceInfoFetched(
                    serial.into(),
                    Err(detail.into()),
                )),
            )
        };
        let _ = app.update(error(old, "A", "old response"));
        assert!(matches!(
            app.device_info_popup,
            Some((_, DeviceInfoState::Loading))
        ));
        let _ = app.update(error(retry, "A", "current response"));
        assert!(
            matches!(&app.device_info_popup, Some((_, DeviceInfoState::Error(e))) if e == "current response")
        );

        let old = app.queries.start_lookup(LookupKind::Info);
        polled(&mut app, "B", ConnectionStatus::Fastboot);
        polled(&mut app, "A", ConnectionStatus::Fastboot);
        app.device_info_popup = Some(("A".into(), DeviceInfoState::Loading));
        let _current = app.queries.start_lookup(LookupKind::Info);
        // Panic fallbacks used to target whichever popup happened to be open.
        let _ = app.update(error(old, "", "old panic"));
        assert!(matches!(
            app.device_info_popup,
            Some((_, DeviceInfoState::Loading))
        ));
    }

    #[test]
    fn context_invalidation_preserves_poll_lease_and_completed_caches() {
        let mut queries = DeviceQueries::default();
        queries
            .qfil_cache
            .insert("A".into(), QfilPopupState::NoPackage);
        let poll = queries.start_poll();
        let info = queries.start_lookup(LookupKind::Info);
        let ota = queries.start_lookup(LookupKind::Ota);
        let qfil = queries.start_lookup(LookupKind::Qfil);
        queries.start_region();
        queries.invalidate_context();
        assert_eq!(queries.poll_in_flight, Some(poll));
        assert!(!queries.finish_poll(poll + 1));
        for token in [info, ota, qfil] {
            assert!(!queries.finish_lookup(token));
        }
        assert!(queries.region_pending.is_none());
        assert!(queries.qfil_cache.contains_key("A"));
        assert!(queries.finish_poll(poll));
        assert!(!queries.finish_poll(poll));
    }

    #[test]
    fn closing_one_lookup_preserves_other_kinds() {
        let mut queries = DeviceQueries::default();
        let info = queries.start_lookup(LookupKind::Info);
        let ota = queries.start_lookup(LookupKind::Ota);
        queries.cancel_lookup(LookupKind::Info);
        assert!(!queries.finish_lookup(info));
        assert!(queries.finish_lookup(ota));
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct LookupToken {
    kind: LookupKind,
    sequence: u64,
}

#[derive(Default)]
pub(crate) struct DeviceQueries {
    sequence: u64,
    pending: HashMap<LookupKind, LookupToken>,
    pub(crate) poll_in_flight: Option<u64>,
    pub(crate) poll_deferred: VecDeque<Message>,
    pub(crate) region_pending: Option<u64>,
    pub(crate) info_cache: HashMap<String, ltbox_core::lenovo_info::MachineInfo>,
    pub(crate) ota_cache: HashMap<(String, String), Option<ltbox_core::lenovo_ota::OtaUpdate>>,
    pub(crate) qfil_cache: HashMap<String, QfilPopupState>,
}

impl DeviceQueries {
    pub(crate) fn track_lookup(
        &mut self,
        kind: LookupKind,
        task: iced::Task<Message>,
    ) -> iced::Task<Message> {
        let token = self.start_lookup(kind);
        task.map(move |message| Message::DeviceLookupEvent(token, Box::new(message)))
    }
    fn next_sequence(&mut self) -> u64 {
        self.sequence = self
            .sequence
            .checked_add(1)
            .expect("device query ID exhausted");
        self.sequence
    }

    pub(crate) fn start_poll(&mut self) -> u64 {
        assert!(self.poll_in_flight.is_none(), "device poll already running");
        let id = self.next_sequence();
        self.poll_in_flight = Some(id);
        id
    }

    pub(crate) fn finish_poll(&mut self, id: u64) -> bool {
        if self.poll_in_flight != Some(id) {
            return false;
        }
        self.poll_in_flight = None;
        true
    }

    pub(crate) fn start_region(&mut self) -> u64 {
        let id = self.next_sequence();
        self.region_pending = Some(id);
        id
    }

    pub(crate) fn start_lookup(&mut self, kind: LookupKind) -> LookupToken {
        let token = LookupToken {
            kind,
            sequence: self.next_sequence(),
        };
        self.pending.insert(kind, token);
        token
    }

    pub(crate) fn finish_lookup(&mut self, token: LookupToken) -> bool {
        if self.pending.get(&token.kind) != Some(&token) {
            return false;
        }
        self.pending.remove(&token.kind);
        true
    }

    pub(crate) fn cancel_lookup(&mut self, kind: LookupKind) {
        self.pending.remove(&kind);
    }

    /// A device/transport change invalidates replies, including A -> B -> A.
    /// Keep serial-keyed completed caches and the USB poll lease: changing UI
    /// context must never release a worker that still owns a USB handle.
    pub(crate) fn invalidate_context(&mut self) {
        self.pending.clear();
        self.region_pending = None;
    }

    #[cfg(test)]
    pub(crate) fn sequence(&self) -> u64 {
        self.sequence
    }
}
