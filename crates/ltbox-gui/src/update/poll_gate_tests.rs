use crate::{
    App, ConnectionStatus, DevicePollResult, KonaBessPrepared, Message, OperationExecution, View,
};

fn poll(serial: &str, model: &str) -> DevicePollResult {
    DevicePollResult {
        status: ConnectionStatus::Adb,
        model: model.to_string(),
        serial: serial.to_string(),
        ..DevicePollResult::default()
    }
}

fn prepared() -> KonaBessPrepared {
    KonaBessPrepared {
        work_dir: Default::default(),
        vendor_boot: Default::default(),
        vbmeta: Default::default(),
        backup_dir: Default::default(),
        slot_suffix: "_a".to_string(),
        probable_dtb_index: None,
    }
}

#[test]
fn poll_gate_allocates_one_id_and_drops_duplicate_poll_requests() {
    let mut app = App::default();

    let first = app.update(Message::PollDevice);
    assert_eq!(first.units(), 1);
    assert_eq!(app.device_poll_sequence, 1);
    assert_eq!(app.device_poll_in_flight, Some(1));

    let second = app.update(Message::PollDevice);
    assert_eq!(second.units(), 0);
    assert_eq!(app.device_poll_sequence, 1);
    assert_eq!(app.device_poll_in_flight, Some(1));
}

#[test]
fn stale_poll_completion_keeps_lease_and_snapshot_unchanged() {
    let mut app = App::default();
    let _ = app.update(Message::DevicePolled(poll("old", "old-model")));
    let _ = app.update(Message::PollDevice);

    let task = app.update(Message::DevicePollFinished(
        2,
        Some(poll("new", "new-model")),
    ));
    assert_eq!(task.units(), 0);
    assert_eq!(app.device_poll_in_flight, Some(1));
    assert_eq!(app.device_serial, "old");
    assert_eq!(app.device_model, "old-model");
}

#[test]
fn empty_matching_completion_releases_gate_and_preserves_snapshot() {
    let mut app = App::default();
    let _ = app.update(Message::DevicePolled(poll("old", "old-model")));
    let _ = app.update(Message::PollDevice);

    let task = app.update(Message::DevicePollFinished(1, None));
    assert_eq!(task.units(), 0);
    assert_eq!(app.device_poll_in_flight, None);
    assert_eq!(app.device_serial, "old");
    assert_eq!(app.device_model, "old-model");
    assert!(app.can_poll_device());

    let task = app.update(Message::PollDevice);
    assert_eq!(task.units(), 1);
    assert_eq!(app.device_poll_in_flight, Some(2));
}

#[test]
fn workflow_blockers_prevent_a_new_poll() {
    let mut app = App {
        operation: OperationExecution::fixture(true, None, Vec::new(), 0, None),
        ..App::default()
    };
    assert_eq!(app.update(Message::PollDevice).units(), 0);
    assert_eq!(app.device_poll_sequence, 0);

    app.end_silent_op();
    app.installing_drivers = true;
    assert_eq!(app.update(Message::PollDevice).units(), 0);
    assert_eq!(app.device_poll_sequence, 0);

    app.installing_drivers = false;
    app.konabess.prepared = Some(prepared());
    assert_eq!(app.update(Message::PollDevice).units(), 0);
    assert_eq!(app.device_poll_sequence, 0);
}

#[test]
fn queued_navigation_and_start_over_wait_for_finish_and_discard_stale_result() {
    let mut app = App {
        current_view: View::Dashboard,
        root: crate::RootWizard {
            step: 3,
            family: Some(crate::Family::Magisk),
            ..crate::RootWizard::default()
        },
        ..App::default()
    };
    let _ = app.update(Message::PollDevice);
    let _ = app.update(Message::Navigate(View::Root));
    let _ = app.update(Message::StartOver);

    assert_eq!(app.current_view, View::Dashboard);
    assert_eq!(app.device_poll_deferred.len(), 2);
    assert_eq!(app.device_serial, "");

    let task = app.update(Message::DevicePollFinished(
        1,
        Some(poll("stale", "stale-model")),
    ));
    assert_eq!(task.units(), 0);
    assert_eq!(app.current_view, View::Root);
    assert_eq!(app.device_serial, "");
    assert_eq!(app.device_model, "");
    assert_eq!(app.device_poll_deferred.len(), 0);
    assert_eq!(app.root.step, 0);
    assert!(app.root.family.is_none());
}

#[test]
fn old_completion_cannot_release_or_apply_after_a_new_poll_starts() {
    let mut app = App::default();
    let _ = app.update(Message::DevicePollFinished(
        0,
        Some(poll("ignored", "ignored-model")),
    ));
    let _ = app.update(Message::DevicePolled(poll("stable", "stable-model")));
    let _ = app.update(Message::PollDevice);
    let _ = app.update(Message::DevicePollFinished(1, None));
    let _ = app.update(Message::PollDevice);

    assert_eq!(app.device_poll_in_flight, Some(2));
    let task = app.update(Message::DevicePollFinished(
        1,
        Some(poll("old", "old-model")),
    ));
    assert_eq!(task.units(), 0);
    assert_eq!(app.device_poll_in_flight, Some(2));
    assert_eq!(app.device_serial, "stable");
    assert_eq!(app.device_model, "stable-model");
}

#[test]
fn queued_kill_server_resumes_before_navigation_after_poll_finish() {
    let mut app = App::default();
    let _ = app.update(Message::PollDevice);
    let _ = app.update(Message::KillAdbServer);
    let _ = app.update(Message::Navigate(View::Settings));

    assert_eq!(app.device_poll_deferred.len(), 2);
    assert!(!app.adb_server_kill_in_flight);
    assert_eq!(app.current_view, View::Dashboard);

    let task = app.update(Message::DevicePollFinished(
        1,
        Some(poll("stale", "stale-model")),
    ));
    assert!(task.units() > 0);
    assert!(app.adb_server_kill_in_flight);
    assert_eq!(app.device_poll_deferred.len(), 1);
    assert_eq!(app.current_view, View::Dashboard);
    assert_eq!(app.device_serial, "");

    let task = app.update(Message::AdbServerKillFinished(Ok(())));
    assert!(task.units() > 0);
    assert!(!app.adb_server_kill_in_flight);
    assert_eq!(app.device_poll_deferred.len(), 0);
    assert_eq!(app.current_view, View::Settings);
}

#[test]
fn matching_poll_applies_once_then_rejects_duplicate_completion() {
    let mut app = App::default();
    let _ = app.update(Message::PollDevice);
    let _ = app.update(Message::DevicePollFinished(
        1,
        Some(poll("new", "new-model")),
    ));
    assert_eq!(app.device_serial, "new");
    assert_eq!(app.device_model, "new-model");
    assert!(app.device_poll_in_flight.is_none());
    let _ = app.update(Message::DevicePollFinished(
        1,
        Some(poll("old", "old-model")),
    ));
    assert_eq!(app.device_serial, "new");
}

#[test]
fn poll_cannot_run_across_an_operation_boundary() {
    let mut app = App::default();
    let _ = app.update(Message::PollDevice);
    let _ = app.update(Message::DevicePollFinished(
        1,
        Some(poll("before", "before")),
    ));
    app.begin_op(View::Root);
    assert_eq!(app.update(Message::PollDevice).units(), 0);
    app.end_op();
    let _ = app.update(Message::PollDevice);
    assert_eq!(app.device_poll_in_flight, Some(2));
    let _ = app.update(Message::DevicePollFinished(1, Some(poll("stale", "stale"))));
    assert_eq!(app.device_serial, "before");
    assert_eq!(app.device_poll_in_flight, Some(2));
    let _ = app.update(Message::DevicePollFinished(2, Some(poll("after", "after"))));
    assert_eq!(app.device_serial, "after");
}
