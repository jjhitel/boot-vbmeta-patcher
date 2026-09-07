//! Shared file hashing; callers own verification policy and error reporting.

use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::{self, Read};
use std::path::Path;

/// Stream a file into a lowercase SHA-256 digest, propagating open/read errors.
pub(crate) fn sha256_hex_file(path: &Path) -> io::Result<String> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let digest = hasher.finalize();
    let mut hex = String::with_capacity(digest.len() * 2);
    for byte in digest {
        use std::fmt::Write as _;
        write!(&mut hex, "{byte:02x}").expect("writing to String cannot fail");
    }
    Ok(hex)
}

#[cfg(test)]
mod tests {
    #[test]
    fn sha256_hex_file_matches_known_digest() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("abc.bin");
        std::fs::write(&path, b"abc").expect("write");
        // FIPS 180-2 SHA-256("abc")
        assert_eq!(
            super::sha256_hex_file(&path).expect("hash"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}
