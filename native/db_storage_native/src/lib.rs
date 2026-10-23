//! Native performance helpers for DB Storage Manager.
//!
//! Hot paths: streaming gzip compress/decompress, SHA-256 file checksums,
//! and parallel batch hashing for backup verification and storage scans.

use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use flate2::Compression;
use pyo3::exceptions::PyIOError;
use pyo3::prelude::*;
use rayon::prelude::*;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::Path;

const BUF_SIZE: usize = 1024 * 1024; // 1 MiB streaming buffer

fn io_err(err: impl ToString) -> PyErr {
    PyIOError::new_err(err.to_string())
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

/// Decompress gzip `src` to `dst`. Returns bytes written to `dst`.
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
    m.add_function(wrap_pyfunction!(sha256_file, m)?)?;
    m.add_function(wrap_pyfunction!(sha256_files_parallel, m)?)?;
    m.add_function(wrap_pyfunction!(aggregate_f64, m)?)?;
    m.add_function(wrap_pyfunction!(hash_rows_parallel, m)?)?;
    m.add_function(wrap_pyfunction!(backend_info, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
