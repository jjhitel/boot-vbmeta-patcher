use super::*;

use std::fs;
use std::io::Write;
use std::path::Path;

fn assert_only_settings_file(dir: &Path, settings_path: &Path) {
    let entries = fs::read_dir(dir)
        .expect("settings test directory should be readable")
        .map(|entry| {
            entry
                .expect("settings directory entry should be readable")
                .path()
        })
        .collect::<Vec<_>>();

    assert_eq!(
        entries.len(),
        1,
        "temporary files were left behind: {entries:?}"
    );
    assert_eq!(entries[0], settings_path);
}

#[test]
fn save_to_path_creates_and_overwrites_valid_json_without_siblings() {
    let root = tempfile::tempdir().expect("temporary directory");
    let path = root.path().join("settings.json");

    let first = PersistedSettings {
        language: "ko".to_string(),
        theme: "light".to_string(),
        ..PersistedSettings::default()
    };
    save_to_path(&path, &first).expect("initial settings save");

    let stored: PersistedSettings =
        serde_json::from_slice(&fs::read(&path).expect("initial settings bytes")).unwrap();
    assert_eq!(stored.language, "ko");
    assert_eq!(stored.theme, "light");
    assert_only_settings_file(root.path(), &path);

    let mut second = first;
    second.language = "ja".to_string();
    second.theme = "dark".to_string();
    save_to_path(&path, &second).expect("overwriting settings save");

    let stored: PersistedSettings =
        serde_json::from_slice(&fs::read(&path).expect("overwritten settings bytes")).unwrap();
    assert_eq!(stored.language, "ja");
    assert_eq!(stored.theme, "dark");
    assert_only_settings_file(root.path(), &path);
}

#[test]
fn partial_write_error_preserves_old_bytes_and_cleans_temporary_file() {
    let root = tempfile::tempdir().expect("temporary directory");
    let path = root.path().join("settings.json");
    let old_bytes = br#"{"language":"old"}"#;
    fs::write(&path, old_bytes).expect("existing settings bytes");

    let result = atomic_write_with(&path, |file| {
        file.write_all(br#"{"language":"partial"}"#)?;
        Err(io::Error::other("injected write failure"))
    });

    assert!(result.is_err());
    assert_eq!(
        fs::read(&path).expect("preserved settings bytes"),
        old_bytes
    );
    assert_only_settings_file(root.path(), &path);
}

#[test]
fn regular_file_parent_error_preserves_ancestor_and_cleans_temporary_file() {
    let root = tempfile::tempdir().expect("temporary directory");
    let blocked_parent = root.path().join("blocked");
    let path = blocked_parent.join("settings.json");
    let old_bytes = b"the blocking ancestor remains a regular file";
    fs::write(&blocked_parent, old_bytes).expect("regular file ancestor");

    let result = save_to_path(&path, &PersistedSettings::default());

    assert!(result.is_err());
    assert_eq!(
        fs::read(&blocked_parent).expect("preserved ancestor bytes"),
        old_bytes
    );
    let entries = fs::read_dir(root.path())
        .expect("settings test directory should be readable")
        .map(|entry| {
            entry
                .expect("settings directory entry should be readable")
                .path()
        })
        .collect::<Vec<_>>();
    assert_eq!(entries, vec![blocked_parent]);
}

#[cfg(windows)]
#[test]
fn locked_destination_preserves_old_bytes_and_cleans_temporary_file() {
    use std::fs::OpenOptions;
    use std::io::{Read, Seek, SeekFrom};
    use std::os::windows::fs::OpenOptionsExt;

    let root = tempfile::tempdir().expect("temporary directory");
    let path = root.path().join("settings.json");
    let old_bytes = b"old settings";
    fs::write(&path, old_bytes).expect("existing settings bytes");
    let mut lock = OpenOptions::new()
        .read(true)
        .write(true)
        .share_mode(0)
        .open(&path)
        .expect("exclusive destination lock");

    let result = atomic_write_with(&path, |file| file.write_all(b"new settings"));

    assert!(result.is_err());
    lock.seek(SeekFrom::Start(0))
        .expect("rewind locked destination");
    let mut preserved = Vec::new();
    lock.read_to_end(&mut preserved)
        .expect("read preserved settings bytes through lock");
    drop(lock);
    assert_eq!(preserved, old_bytes);
    assert_only_settings_file(root.path(), &path);
}
