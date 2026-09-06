//! Serialize background USB polling with workflow input.
use crate::*;
use iced::Task;

pub(super) fn defers_message(message: &Message) -> bool {
    !matches!(message, Message::PollDevice)
        && (super::self_update_gate::blocks_message(message)
            || matches!(
                message,
                Message::InstallSelfUpdate | Message::FileSelected(_) | Message::FolderSelected(_)
            ))
}

impl App {
    pub(super) fn can_poll_device(&self) -> bool {
        self.device_poll_in_flight.is_none()
            && self.device_poll_deferred.is_empty()
            && !self.busy
            && !self.installing_drivers
            && !self.adb_server_kill_in_flight
            && !self.direct_update_state.is_active()
            && self.konabess.prepared.is_none()
    }

    pub(super) fn finish_device_poll(
        &mut self,
        id: u64,
        result: Option<DevicePollResult>,
    ) -> Task<Message> {
        // A duplicate or older completion must not release the current lease.
        if self.device_poll_in_flight != Some(id) {
            return Task::none();
        }
        self.device_poll_in_flight = None;
        let apply = self.can_poll_device();
        let task = if apply && let Some(result) = result {
            self.update(Message::DevicePolled(result))
        } else {
            Task::none()
        };
        // The blocking worker has returned and dropped its USB handles before
        // workflow input is replayed. Discard the snapshot if input was queued.
        task.chain(self.resume_after_device_poll())
    }

    pub(super) fn resume_after_device_poll(&mut self) -> Task<Message> {
        if self.device_poll_in_flight.is_some() || self.adb_server_kill_in_flight {
            return Task::none();
        }
        let mut tasks = Vec::new();
        while self.device_poll_in_flight.is_none() && !self.adb_server_kill_in_flight {
            let Some(message) = self.device_poll_deferred.pop_front() else {
                break;
            };
            // Dispatch synchronously in input order so busy reservations and
            // wizard edits are applied before the next deferred action.
            tasks.push(self.update(message));
        }
        Task::batch(tasks)
    }
}
