//! Native performance helpers for DB Storage Manager.
//!
//! Hot paths: streaming gzip/zstd compress/decompress, AES-256-GCM file
//! encryption (PBKDF2 key derivation), SHA-256 checksums, and parallel batch
//! hashing for backup verification and storage scans.

use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use flate2::Compression;
use pbkdf2::pbkdf2_hmac;
use pyo3::exceptions::{PyIOError, PyValueError};
use pyo3::prelude::*;
use rand::RngCore;
use rayon::prelude::*;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::Path;

const BUF_SIZE: usize = 1024 * 1024; // 1 MiB streaming buffer
const ENC_MAGIC: &[u8; 8] = b"DSMENC1\0";
const ENC_SALT_LEN: usize = 16;
const ENC_NONCE_LEN: usize = 12;
const ENC_TAG_LEN: usize = 16;
const ENC_PBKDF2_ITERS: u32 = 200_000;
const ENC_CHUNK: usize = 1024 * 1024;

fn io_err(err: impl ToString) -> PyErr {
    PyIOError::new_err(err.to_string())
}

fn value_err(err: impl ToString) -> PyErr {
    PyValueError::new_err(err.to_string())
}

/// Compress `src` to gzip `dst`. Returns bytes written to `dst`.
#[pyfunction]
#[pyo3(signature = (src, dst, level=None))]
fn gzip_compress_file(src: &str, dst: &str, level: Option<u32>) -> PyResult<u64> {
    let level = level.unwrap_or(6).min(9);
    let in_file = File::open(src).map_err(io_err)?;
    let out_file = File::create(dst).map_err(io_err)?;
    let mut reader = BufReader::with_capacity(BUF_SIZE, in_file);
    let writer = BufWriter::with_capacity(BUF_SIZE, out_file);
    let mut encoder = GzEncoder::new(writer, Compression::new(level));

    let mut buf = vec![0u8; BUF_SIZE];
    loop {
        let n = reader.read(&mut buf).map_err(io_err)?;
        if n == 0 {
            break;
        }
        encoder.write_all(&buf[..n]).map_err(io_err)?;
    }

    let writer = encoder.finish().map_err(io_err)?;
    writer.into_inner().map_err(|e| io_err(e.error()))?;

    let size = std::fs::metadata(dst).map_err(io_err)?.len();
    Ok(size)
}

/// Decompress gzip `src` to `dst`. Returns bytes written.
#[pyfunction]
fn gzip_decompress_file(src: &str, dst: &str) -> PyResult<u64> {
    let in_file = File::open(src).map_err(io_err)?;
    let out_file = File::create(dst).map_err(io_err)?;
    let mut decoder = GzDecoder::new(BufReader::with_capacity(BUF_SIZE, in_file));
    let mut writer = BufWriter::with_capacity(BUF_SIZE, out_file);

    let mut buf = vec![0u8; BUF_SIZE];
    let mut written: u64 = 0;
    loop {
        let n = decoder.read(&mut buf).map_err(io_err)?;
        if n == 0 {
            break;
        }
        writer.write_all(&buf[..n]).map_err(io_err)?;
        written += n as u64;
    }
    writer.flush().map_err(io_err)?;
    Ok(written)
}

/// Compress `src` to zstd `dst`. Returns destination size in bytes.
#[pyfunction]
#[pyo3(signature = (src, dst, level=None))]
fn zstd_compress_file(src: &str, dst: &str, level: Option<i32>) -> PyResult<u64> {
    let level = level.unwrap_or(3).clamp(1, 22);
    let in_file = File::open(src).map_err(io_err)?;
    let out_file = File::create(dst).map_err(io_err)?;
    let mut reader = BufReader::with_capacity(BUF_SIZE, in_file);
    let writer = BufWriter::with_capacity(BUF_SIZE, out_file);
    let mut encoder = zstd::stream::write::Encoder::new(writer, level).map_err(io_err)?;

    let mut buf = vec![0u8; BUF_SIZE];
    loop {
        let n = reader.read(&mut buf).map_err(io_err)?;
        if n == 0 {
            break;
        }
        encoder.write_all(&buf[..n]).map_err(io_err)?;
    }

    let writer = encoder.finish().map_err(io_err)?;
    writer.into_inner().map_err(|e| io_err(e.error()))?;

    let size = std::fs::metadata(dst).map_err(io_err)?.len();
    Ok(size)
}

/// Decompress zstd `src` to `dst`. Returns bytes written.
#[pyfunction]
fn zstd_decompress_file(src: &str, dst: &str) -> PyResult<u64> {
    let in_file = File::open(src).map_err(io_err)?;
    let out_file = File::create(dst).map_err(io_err)?;
    let mut decoder =
        zstd::stream::read::Decoder::new(BufReader::with_capacity(BUF_SIZE, in_file))
            .map_err(io_err)?;
    let mut writer = BufWriter::with_capacity(BUF_SIZE, out_file);

    let mut buf = vec![0u8; BUF_SIZE];
    let mut written: u64 = 0;
    loop {
        let n = decoder.read(&mut buf).map_err(io_err)?;
        if n == 0 {
            break;
        }
        writer.write_all(&buf[..n]).map_err(io_err)?;
        written += n as u64;
    }
    writer.flush().map_err(io_err)?;
    Ok(written)
}

fn derive_key(passphrase: &str, salt: &[u8]) -> [u8; 32] {
    let mut key = [0u8; 32];
    pbkdf2_hmac::<Sha256>(passphrase.as_bytes(), salt, ENC_PBKDF2_ITERS, &mut key);
    key
}

fn write_u32_be(out: &mut impl Write, value: u32) -> Result<(), std::io::Error> {
    out.write_all(&value.to_be_bytes())
}

fn read_u32_be(input: &mut impl Read) -> Result<u32, std::io::Error> {
    let mut buf = [0u8; 4];
    input.read_exact(&mut buf)?;
    Ok(u32::from_be_bytes(buf))
}

/// Encrypt file with AES-256-GCM (chunked). Key = PBKDF2-HMAC-SHA256(passphrase).
///
/// On-disk format (`DSMENC1`):
/// `magic(8) | salt(16) | repeated (u32_be plain_len | nonce(12) | ciphertext+tag) | u32_be(0)`
#[pyfunction]
fn encrypt_file(src: &str, dst: &str, passphrase: &str) -> PyResult<u64> {
    if passphrase.is_empty() {
        return Err(value_err("encryption passphrase must not be empty"));
    }

    let mut salt = [0u8; ENC_SALT_LEN];
    rand::thread_rng().fill_bytes(&mut salt);
    let key = derive_key(passphrase, &salt);
    let cipher = Aes256Gcm::new_from_slice(&key).map_err(|e| value_err(e.to_string()))?;

    let in_file = File::open(src).map_err(io_err)?;
    let out_file = File::create(dst).map_err(io_err)?;
    let mut reader = BufReader::with_capacity(BUF_SIZE, in_file);
    let mut writer = BufWriter::with_capacity(BUF_SIZE, out_file);

    writer.write_all(ENC_MAGIC).map_err(io_err)?;
    writer.write_all(&salt).map_err(io_err)?;

    let mut plain = vec![0u8; ENC_CHUNK];
    loop {
        let mut filled = 0usize;
        while filled < ENC_CHUNK {
            let n = reader.read(&mut plain[filled..]).map_err(io_err)?;
            if n == 0 {
                break;
            }
            filled += n;
        }
        if filled == 0 {
            break;
        }

        let mut nonce_bytes = [0u8; ENC_NONCE_LEN];
        rand::thread_rng().fill_bytes(&mut nonce_bytes);
        let nonce = Nonce::from_slice(&nonce_bytes);
        let ciphertext = cipher
            .encrypt(nonce, &plain[..filled])
            .map_err(|e| value_err(format!("AES-GCM encrypt failed: {e}")))?;

        write_u32_be(&mut writer, filled as u32).map_err(io_err)?;
        writer.write_all(&nonce_bytes).map_err(io_err)?;
        writer.write_all(&ciphertext).map_err(io_err)?;
    }
    write_u32_be(&mut writer, 0).map_err(io_err)?;
    writer.flush().map_err(io_err)?;

    let size = std::fs::metadata(dst).map_err(io_err)?.len();
    Ok(size)
}

/// Decrypt a `DSMENC1` file produced by `encrypt_file`.
#[pyfunction]
fn decrypt_file(src: &str, dst: &str, passphrase: &str) -> PyResult<u64> {
    if passphrase.is_empty() {
        return Err(value_err("encryption passphrase must not be empty"));
    }

    let in_file = File::open(src).map_err(io_err)?;
    let out_file = File::create(dst).map_err(io_err)?;
    let mut reader = BufReader::with_capacity(BUF_SIZE, in_file);
    let mut writer = BufWriter::with_capacity(BUF_SIZE, out_file);

    let mut magic = [0u8; 8];
    reader.read_exact(&mut magic).map_err(io_err)?;
    if &magic != ENC_MAGIC {
        return Err(value_err(
            "not a DSMENC1 encrypted backup (bad magic header)",
        ));
    }

    let mut salt = [0u8; ENC_SALT_LEN];
    reader.read_exact(&mut salt).map_err(io_err)?;
    let key = derive_key(passphrase, &salt);
    let cipher = Aes256Gcm::new_from_slice(&key).map_err(|e| value_err(e.to_string()))?;

    let mut written: u64 = 0;
    loop {
        let plain_len = read_u32_be(&mut reader).map_err(io_err)? as usize;
        if plain_len == 0 {
            break;
        }
        if plain_len > ENC_CHUNK {
            return Err(value_err("encrypted chunk length exceeds frame limit"));
        }

        let mut nonce_bytes = [0u8; ENC_NONCE_LEN];
        reader.read_exact(&mut nonce_bytes).map_err(io_err)?;
        let ct_len = plain_len + ENC_TAG_LEN;
        let mut ciphertext = vec![0u8; ct_len];
        reader.read_exact(&mut ciphertext).map_err(io_err)?;

        let nonce = Nonce::from_slice(&nonce_bytes);
        let plain = cipher
            .decrypt(nonce, ciphertext.as_ref())
            .map_err(|_| value_err("AES-GCM decrypt failed (wrong key or corrupt file)"))?;
        if plain.len() != plain_len {
            return Err(value_err("decrypted chunk length mismatch"));
        }
        writer.write_all(&plain).map_err(io_err)?;
        written += plain.len() as u64;
    }
    writer.flush().map_err(io_err)?;
    Ok(written)
}

/// SHA-256 hex digest of a file (streaming, constant memory).
#[pyfunction]
fn sha256_file(path: &str) -> PyResult<String> {
    hash_file_sha256(Path::new(path)).map_err(io_err)
}

fn hash_file_sha256(path: &Path) -> Result<String, std::io::Error> {
    let file = File::open(path)?;
    let mut reader = BufReader::with_capacity(BUF_SIZE, file);
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; BUF_SIZE];
    loop {
        let n = reader.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hex::encode(hasher.finalize()))
}

/// Parallel SHA-256 for many paths. Returns list of `(path, hex_digest)` tuples.
/// Failed paths return an empty digest string and are still included.
#[pyfunction]
fn sha256_files_parallel(paths: Vec<String>) -> PyResult<Vec<(String, String)>> {
    let results: Vec<(String, String)> = paths
        .par_iter()
        .map(|p| match hash_file_sha256(Path::new(p)) {
            Ok(digest) => (p.clone(), digest),
            Err(_) => (p.clone(), String::new()),
        })
        .collect();
    Ok(results)
}

/// Aggregate numeric column values from a flat f64 list (query-result helper).
/// Returns `(count, sum, min, max, mean)`. Empty input returns zeros.
#[pyfunction]
fn aggregate_f64(values: Vec<f64>) -> PyResult<(usize, f64, f64, f64, f64)> {
    if values.is_empty() {
        return Ok((0, 0.0, 0.0, 0.0, 0.0));
    }
    let count = values.len();
    let (sum, min, max) = values
        .par_iter()
        .fold(
            || (0.0_f64, f64::INFINITY, f64::NEG_INFINITY),
            |(s, mn, mx), &v| (s + v, mn.min(v), mx.max(v)),
        )
        .reduce(
            || (0.0_f64, f64::INFINITY, f64::NEG_INFINITY),
            |(s1, mn1, mx1), (s2, mn2, mx2)| (s1 + s2, mn1.min(mn2), mx1.max(mx2)),
        );
    let mean = sum / count as f64;
    Ok((count, sum, min, max, mean))
}

/// Hash UTF-8 string rows in parallel (for data comparison fingerprints).
/// Each row is joined with `\0` then SHA-256'd; returns hex digests in order.
#[pyfunction]
fn hash_rows_parallel(rows: Vec<Vec<String>>) -> PyResult<Vec<String>> {
    let digests: Vec<String> = rows
        .par_iter()
        .map(|row| {
            let mut hasher = Sha256::new();
            for (i, cell) in row.iter().enumerate() {
                if i > 0 {
                    hasher.update([0u8]);
                }
                hasher.update(cell.as_bytes());
            }
            hex::encode(hasher.finalize())
        })
        .collect();
    Ok(digests)
}

/// Backend identity for feature detection from Python.
#[pyfunction]
fn backend_info() -> PyResult<(String, String)> {
    Ok((
        "rust".to_string(),
        env!("CARGO_PKG_VERSION").to_string(),
    ))
}

#[pymodule]
fn db_storage_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(gzip_compress_file, m)?)?;
    m.add_function(wrap_pyfunction!(gzip_decompress_file, m)?)?;
    m.add_function(wrap_pyfunction!(zstd_compress_file, m)?)?;
    m.add_function(wrap_pyfunction!(zstd_decompress_file, m)?)?;
    m.add_function(wrap_pyfunction!(encrypt_file, m)?)?;
    m.add_function(wrap_pyfunction!(decrypt_file, m)?)?;
    m.add_function(wrap_pyfunction!(sha256_file, m)?)?;
    m.add_function(wrap_pyfunction!(sha256_files_parallel, m)?)?;
    m.add_function(wrap_pyfunction!(aggregate_f64, m)?)?;
    m.add_function(wrap_pyfunction!(hash_rows_parallel, m)?)?;
    m.add_function(wrap_pyfunction!(backend_info, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("ENCRYPTION_FORMAT", "DSMENC1")?;
    m.add("ENCRYPTION_SCHEME", "aes-256-gcm-pbkdf2")?;
    Ok(())
}
