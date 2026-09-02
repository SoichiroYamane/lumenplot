//! Static shader source and provenance verification for the portable renderer.

pub(crate) const LINE_SHADER_SOURCE: &str = include_str!("../shaders/line.wgsl");
const LINE_SHADER_SOURCE_REVISION: &str = "lumenplot-line-wgsl-v1";
const LINE_SHADER_VALIDATION: &str =
    "naga WGSL parser plus wgpu 29.0.4 checked shader at renderer initialization";
const LINE_SHADER_RESOURCE_LAYOUT: &str =
    "group0/binding0 uniform(viewport_px, half_width_px, color_linear)";
const LINE_SHADER_SHA256: &str = "e0c3b4d3247963a1b8a96fe91dacb2f1c6f14ee5c31ed1c91fd6bbcc5ec9cbf3";

/// Provenance attached to the trusted static line shader artifact.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ShaderProvenance {
    source_revision: &'static str,
    validation: &'static str,
    resource_layout: &'static str,
    artifact_sha256: &'static str,
}

impl ShaderProvenance {
    /// Source revision identifier for the checked-in WGSL artifact.
    pub const fn source_revision(self) -> &'static str {
        self.source_revision
    }

    /// Validation mode used before the shader is installed.
    pub const fn validation(self) -> &'static str {
        self.validation
    }

    /// Resource layout expected by the shader and pipeline.
    pub const fn resource_layout(self) -> &'static str {
        self.resource_layout
    }

    /// SHA-256 digest of the exact checked-in WGSL source bytes.
    pub const fn artifact_sha256(self) -> &'static str {
        self.artifact_sha256
    }
}

pub(crate) const fn provenance() -> ShaderProvenance {
    ShaderProvenance {
        source_revision: LINE_SHADER_SOURCE_REVISION,
        validation: LINE_SHADER_VALIDATION,
        resource_layout: LINE_SHADER_RESOURCE_LAYOUT,
        artifact_sha256: LINE_SHADER_SHA256,
    }
}

pub(crate) fn verify_artifact() -> bool {
    digest_matches(LINE_SHADER_SOURCE.as_bytes(), LINE_SHADER_SHA256)
}

#[cfg(test)]
pub(crate) fn verify_bytes(source: &[u8], expected_sha256: &str) -> bool {
    digest_matches(source, expected_sha256)
}

fn digest_matches(source: &[u8], expected_sha256: &str) -> bool {
    let Some(digest) = sha256(source) else {
        return false;
    };
    if expected_sha256.len() != 64 {
        return false;
    }
    let mut encoded = [0u8; 64];
    for (index, byte) in digest.into_iter().enumerate() {
        encoded[index * 2] = hex_digit(byte >> 4);
        encoded[index * 2 + 1] = hex_digit(byte & 0x0f);
    }
    encoded == expected_sha256.as_bytes()
}

fn hex_digit(value: u8) -> u8 {
    match value {
        0..=9 => b'0' + value,
        10..=15 => b'a' + (value - 10),
        _ => unreachable!("a nibble is always below sixteen"),
    }
}

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
    let bit_length = (source.len() as u64).checked_mul(8)?;

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checked_static_artifact_matches_its_provenance() {
        assert!(verify_artifact());
        let metadata = provenance();
        assert_eq!(metadata.source_revision(), "lumenplot-line-wgsl-v1");
        assert_eq!(metadata.validation(), LINE_SHADER_VALIDATION);
        assert_eq!(metadata.resource_layout(), LINE_SHADER_RESOURCE_LAYOUT);
        assert_eq!(metadata.artifact_sha256(), LINE_SHADER_SHA256);
    }

    #[test]
    fn altered_shader_bytes_fail_closed() {
        let mut altered = LINE_SHADER_SOURCE.as_bytes().to_vec();
        altered.push(b' ');
        assert!(!verify_bytes(&altered, LINE_SHADER_SHA256));
        assert!(!verify_bytes(LINE_SHADER_SOURCE.as_bytes(), "not-a-sha256"));
    }

    #[test]
    fn sha256_known_empty_vector_is_correct() {
        assert!(verify_bytes(
            b"",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        ));
    }
}
