//! M5-P3i deterministic fixture-font evidence (`AT-SEC-FONTS`).
//!
//! Scope: one vendored OFL fixture font plus its manifest entry
//! (SHA-256, face, variation, `fsType`, license, fallback route), a
//! dependency-free OpenType `OS/2.fsType` reader, and deterministic
//! fixture tests. There is intentionally no shaping dependency, no PDF
//! writer change, and no dependency pin in this slice.
//!
//! Placement note: the reader lives in this integration test rather than
//! in `src/` because the `lumenplot-export` source/module inventory is
//! architecture-pinned and writer changes are deferred by the slice
//! order. The follow-up writer slice promotes this proven reader into
//! the writer together with that slice's inventory amendment; until
//! then this test is the authoritative `fsType` reader evidence.

use std::path::PathBuf;

const FONT_FILE: &str = "FiraSans-Regular.ttf";
const MANIFEST_FILE: &str = "at-sec-fonts-manifest.toml";
const LICENSE_FILE: &str = "OFL.txt";

const EXPECTED_BYTES: usize = 456_996;
const EXPECTED_FSTYPE: u16 = 0;
const EXPECTED_SHA256_HEX: &str =
    "c29556a2719bf613ef3d5e070e40d903a8965d9c081beca1375dc1e6e0f93c23";
const EXPECTED_SHA256: [u8; 32] = [
    0xc2, 0x95, 0x56, 0xa2, 0x71, 0x9b, 0xf6, 0x13, 0xef, 0x3d, 0x5e, 0x07, 0x0e, 0x40, 0xd9, 0x03,
    0xa8, 0x96, 0x5d, 0x9c, 0x08, 0x1b, 0xec, 0xa1, 0x37, 0x5d, 0xc1, 0xe6, 0xe0, 0xf9, 0x3c, 0x23,
];

/// Failure modes of the fixture `fsType` reader.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FontReadError {
    /// Fewer bytes than the claimed sfnt header or table directory.
    Truncated,
    /// Unknown sfnt version (including `ttcf` collections), or zero tables.
    UnsupportedSfnt,
    /// No `OS/2` table directory entry.
    MissingOs2,
    /// `OS/2` entry runs out of bounds or is shorter than the `fsType`
    /// field offset.
    Os2TooShort,
}

/// Read the `OS/2.fsType` embedding-permission word from sfnt font bytes.
///
/// Accepts single-font TrueType/OpenType sfnt versions (`0x00010000`,
/// `OTTO`, `true`, `typ1`) and rejects collections and malformed input
/// with checked bounds before any read. Uses only `std`.
fn read_fstype(font_bytes: &[u8]) -> Result<u16, FontReadError> {
    const HEADER_LEN: usize = 12;
    const ENTRY_LEN: usize = 16;
    const OS2_FSTYPE_OFFSET: usize = 8;
    const OS2_MIN_LEN: u32 = 10;

    if font_bytes.len() < HEADER_LEN {
        return Err(FontReadError::Truncated);
    }
    let magic = u32::from_be_bytes([font_bytes[0], font_bytes[1], font_bytes[2], font_bytes[3]]);
    const TRUETYPE: u32 = 0x0001_0000;
    const OTTO: u32 = 0x4f54_544f;
    const TRUE: u32 = 0x7472_7565;
    const TYP1: u32 = 0x7479_7031;
    if magic != TRUETYPE && magic != OTTO && magic != TRUE && magic != TYP1 {
        return Err(FontReadError::UnsupportedSfnt);
    }
    let num_tables = u16::from_be_bytes([font_bytes[4], font_bytes[5]]);
    if num_tables == 0 {
        return Err(FontReadError::UnsupportedSfnt);
    }
    let directory_len = (num_tables as usize)
        .checked_mul(ENTRY_LEN)
        .and_then(|entries| entries.checked_add(HEADER_LEN))
        .ok_or(FontReadError::Truncated)?;
    if font_bytes.len() < directory_len {
        return Err(FontReadError::Truncated);
    }
    for index in 0..num_tables as usize {
        let entry = HEADER_LEN + index * ENTRY_LEN;
        let offset = u32::from_be_bytes([
            font_bytes[entry + 8],
            font_bytes[entry + 9],
            font_bytes[entry + 10],
            font_bytes[entry + 11],
        ]);
        let length = u32::from_be_bytes([
            font_bytes[entry + 12],
            font_bytes[entry + 13],
            font_bytes[entry + 14],
            font_bytes[entry + 15],
        ]);
        if &font_bytes[entry..entry + 4] != b"OS/2" {
            continue;
        }
        if length < OS2_MIN_LEN {
            return Err(FontReadError::Os2TooShort);
        }
        let fstype_at = (offset as usize)
            .checked_add(OS2_FSTYPE_OFFSET)
            .and_then(|at| at.checked_add(2))
            .ok_or(FontReadError::Os2TooShort)?;
        if fstype_at > font_bytes.len() || (offset as usize) > font_bytes.len() {
            return Err(FontReadError::Os2TooShort);
        }
        let at = offset as usize + OS2_FSTYPE_OFFSET;
        return Ok(u16::from_be_bytes([font_bytes[at], font_bytes[at + 1]]));
    }
    Err(FontReadError::MissingOs2)
}

/// SHA-256 over `std` only, mirroring the engine retained-identity helper.
fn sha256(source: &[u8]) -> Option<[u8; 32]> {
    const INITIAL: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    const ROUND_CONSTANTS: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];

    let with_marker = source.len().checked_add(1)?;
    let with_length = with_marker.checked_add(8)?;
    let padding = (64 - (with_length % 64)) % 64;
    let padded_len = with_length.checked_add(padding)?;
    let bit_length = u64::try_from(source.len()).ok()?.checked_mul(8)?;

    let mut padded = Vec::new();
    padded.try_reserve_exact(padded_len).ok()?;
    padded.extend_from_slice(source);
    padded.push(0x80);
    padded.resize(padded_len - 8, 0);
    padded.extend_from_slice(&bit_length.to_be_bytes());

    let mut state = INITIAL;
    for chunk in padded.chunks_exact(64) {
        let mut words = [0u32; 64];
        for (index, word) in words[..16].iter_mut().enumerate() {
            let start = index * 4;
            *word = u32::from_be_bytes([
                chunk[start],
                chunk[start + 1],
                chunk[start + 2],
                chunk[start + 3],
            ]);
        }
        for index in 16..64 {
            let s0 = words[index - 15].rotate_right(7)
                ^ words[index - 15].rotate_right(18)
                ^ (words[index - 15] >> 3);
            let s1 = words[index - 2].rotate_right(17)
                ^ words[index - 2].rotate_right(19)
                ^ (words[index - 2] >> 10);
            words[index] = words[index - 16]
                .wrapping_add(s0)
                .wrapping_add(words[index - 7])
                .wrapping_add(s1);
        }

        let mut working = state;
        for index in 0..64 {
            let s1 = working[4].rotate_right(6)
                ^ working[4].rotate_right(11)
                ^ working[4].rotate_right(25);
            let choose = (working[4] & working[5]) ^ ((!working[4]) & working[6]);
            let temporary1 = working[7]
                .wrapping_add(s1)
                .wrapping_add(choose)
                .wrapping_add(ROUND_CONSTANTS[index])
                .wrapping_add(words[index]);
            let s0 = working[0].rotate_right(2)
                ^ working[0].rotate_right(13)
                ^ working[0].rotate_right(22);
            let majority =
                (working[0] & working[1]) ^ (working[0] & working[2]) ^ (working[1] & working[2]);
            let temporary2 = s0.wrapping_add(majority);

            working[7] = working[6];
            working[6] = working[5];
            working[5] = working[4];
            working[4] = working[3].wrapping_add(temporary1);
            working[3] = working[2];
            working[2] = working[1];
            working[1] = working[0];
            working[0] = temporary1.wrapping_add(temporary2);
        }
        for index in 0..8 {
            state[index] = state[index].wrapping_add(working[index]);
        }
    }

    let mut digest = [0u8; 32];
    for (index, word) in state.into_iter().enumerate() {
        digest[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    Some(digest)
}

fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fonts")
}

fn read_font_bytes() -> Vec<u8> {
    std::fs::read(fixture_dir().join(FONT_FILE)).expect("vendored fixture font is readable")
}

fn read_manifest_text() -> String {
    std::fs::read_to_string(fixture_dir().join(MANIFEST_FILE))
        .expect("AT-SEC-FONTS manifest is readable")
}

fn read_license_text() -> String {
    std::fs::read_to_string(fixture_dir().join(LICENSE_FILE)).expect("OFL text is readable")
}

/// Extract the `sha256 = "<64 hex>"` value from the manifest without a
/// parser dependency; the fixed schema keeps this exact.
fn manifest_sha256(manifest: &str) -> Option<[u8; 32]> {
    const PREFIX: &str = "sha256 = \"";
    let line = manifest
        .lines()
        .find(|line| line.starts_with(PREFIX) && line.ends_with('"'))?;
    let hex = line.strip_prefix(PREFIX)?.strip_suffix('"')?;
    if hex.len() != 64 || !hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return None;
    }
    let mut digest = [0u8; 32];
    for (index, slot) in digest.iter_mut().enumerate() {
        let pair = hex.get(index * 2..index * 2 + 2)?;
        *slot = u8::from_str_radix(pair, 16).ok()?;
    }
    Some(digest)
}

fn sfnt_header(magic: u32, num_tables: u16) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(12);
    bytes.extend_from_slice(&magic.to_be_bytes());
    bytes.extend_from_slice(&num_tables.to_be_bytes());
    bytes.extend_from_slice(&[0u8; 6]);
    bytes
}

fn table_entry(tag: &[u8; 4], offset: u32, length: u32) -> [u8; 16] {
    let mut entry = [0u8; 16];
    entry[..4].copy_from_slice(tag);
    entry[8..12].copy_from_slice(&offset.to_be_bytes());
    entry[12..16].copy_from_slice(&length.to_be_bytes());
    entry
}

#[test]
fn sha256_matches_known_answer_vector() {
    assert_eq!(
        sha256(b"abc"),
        Some([
            0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40, 0xde, 0x5d, 0xae,
            0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61,
            0xf2, 0x00, 0x15, 0xad,
        ])
    );
}

#[test]
fn fixture_font_bytes_are_deterministic_and_pinned() {
    let first = read_font_bytes();
    let second = read_font_bytes();
    assert_eq!(first.len(), EXPECTED_BYTES);
    assert_eq!(first, second);
    assert_eq!(sha256(&first), Some(EXPECTED_SHA256));
    assert!(read_manifest_text().contains(EXPECTED_SHA256_HEX));
}

#[test]
fn fixture_fstype_is_installable_embedding() {
    assert_eq!(read_fstype(&read_font_bytes()), Ok(EXPECTED_FSTYPE));
    assert_eq!(EXPECTED_FSTYPE, 0);
}

#[test]
fn manifest_records_all_required_at_sec_fonts_fields() {
    let manifest = read_manifest_text();
    for field in [
        "font_file = \"FiraSans-Regular.ttf\"",
        EXPECTED_SHA256_HEX,
        "bytes = 456996",
        "face_index = 0",
        "Fira Sans Regular",
        "FiraSans-Regular",
        "variation = ",
        "fstype = 0",
        "installable embedding",
        "license = \"OFL-1.1\"",
        "license_file = \"OFL.txt\"",
        "Mozilla Foundation",
        "fallback_route = ",
        "no system fallback",
        "source_url = ",
    ] {
        assert!(
            manifest.contains(field),
            "manifest is missing field {field:?}"
        );
    }
    let license = read_license_text();
    for marker in [
        "SIL OPEN FONT LICENSE Version 1.1",
        "Permission is hereby granted, free of charge",
        "THE FONT SOFTWARE IS PROVIDED",
    ] {
        assert!(
            license.contains(marker),
            "OFL text is missing marker {marker:?}"
        );
    }
}

#[test]
fn manifest_sha256_binds_recorded_hash_to_vendored_bytes() {
    let manifest = read_manifest_text();
    let recorded = manifest_sha256(&manifest).expect("manifest carries a 64-hex sha256");
    assert_eq!(recorded, EXPECTED_SHA256);
    assert_eq!(sha256(&read_font_bytes()), Some(recorded));
}

#[test]
fn reader_rejects_truncated_input() {
    assert_eq!(read_fstype(&[]), Err(FontReadError::Truncated));
    assert_eq!(read_fstype(&[0u8; 5]), Err(FontReadError::Truncated));
    let mut claimed_two = sfnt_header(0x0001_0000, 2);
    claimed_two.extend_from_slice(&table_entry(b"OS/2", 28, 10));
    assert_eq!(read_fstype(&claimed_two), Err(FontReadError::Truncated));
    assert_eq!(
        read_fstype(&sfnt_header(0x0001_0000, 0)),
        Err(FontReadError::UnsupportedSfnt)
    );
}

#[test]
fn reader_rejects_non_sfnt_and_collections() {
    assert_eq!(
        read_fstype(&sfnt_header(0x7474_6366, 1)),
        Err(FontReadError::UnsupportedSfnt)
    );
    assert_eq!(
        read_fstype(&sfnt_header(0xdead_beef, 1)),
        Err(FontReadError::UnsupportedSfnt)
    );
}

#[test]
fn reader_rejects_missing_or_short_os2() {
    let mut without_os2 = sfnt_header(0x0001_0000, 1);
    without_os2.extend_from_slice(&table_entry(b"head", 28, 54));
    without_os2.resize(82, 0);
    assert_eq!(read_fstype(&without_os2), Err(FontReadError::MissingOs2));

    let mut short_os2 = sfnt_header(0x0001_0000, 1);
    short_os2.extend_from_slice(&table_entry(b"OS/2", 28, 8));
    short_os2.resize(36, 0);
    assert_eq!(read_fstype(&short_os2), Err(FontReadError::Os2TooShort));

    let mut oob_os2 = sfnt_header(0x0001_0000, 1);
    oob_os2.extend_from_slice(&table_entry(b"OS/2", u32::MAX, 96));
    assert_eq!(read_fstype(&oob_os2), Err(FontReadError::Os2TooShort));
}

#[test]
fn reader_reads_fstype_from_synthetic_os2() {
    let mut font = sfnt_header(0x4f54_544f, 1);
    font.extend_from_slice(&table_entry(b"OS/2", 28, 96));
    font.resize(28, 0);
    font.extend_from_slice(&[0u8; 8]);
    font.extend_from_slice(&[0x01, 0x02]);
    assert_eq!(read_fstype(&font), Ok(0x0102));
}
