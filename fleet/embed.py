"""Job vectors for open US jobs, so matching runs outside the Recrutas server (ADR 0008).

Same model, pooling and text as Recrutas's own job vectors (bge-small-en-v1.5, full-precision
ONNX, mean pooling, normalised; title + company + the first 1,000 characters of the description),
so a Fleet vector and a resume vector are comparable. Checked against production: cosine 1.0.

Incremental: a job is embedded once and again only when its content changes. Shards split the
work for the first backfill; `combine` drops closed jobs and writes one file.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .ids import shard_of

MODEL = "Xenova/bge-small-en-v1.5"
DIM = 384
VECTORS_PATH = "vectors/jobs.parquet"
STATE_COLUMNS = ["job_id", "content_hash", "title", "company_name", "description", "closed_at", "is_us"]
SCHEMA = pa.schema([("job_id", pa.string()), ("content_hash", pa.string()), ("vector", pa.list_(pa.float16(), DIM))])

Embedder = Callable[[list[str]], np.ndarray]


def job_text(title: str | None, company: str | None, description: str | None) -> str:
    """The text Recrutas embeds for a job (its skills and requirements are empty for Fleet jobs)."""
    return " ".join([title or "", company or "", (description or "")[:1000]])


def load_embedder(batch: int = 32) -> Embedder:
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(hf_hub_download(MODEL, "tokenizer.json"))
    tok.enable_truncation(512)
    tok.enable_padding()
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = os.cpu_count() or 2
    sess = ort.InferenceSession(hf_hub_download(MODEL, "onnx/model.onnx"), opts, providers=["CPUExecutionProvider"])
    names = {i.name for i in sess.get_inputs()}

    def embed(texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch):
            enc = tok.encode_batch(texts[i: i + batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in names:
                feeds["token_type_ids"] = np.zeros_like(ids)
            h = sess.run(None, feeds)[0]
            v = (h * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            out.append(v / np.linalg.norm(v, axis=1, keepdims=True))
        return np.concatenate(out).astype(np.float32) if out else np.zeros((0, DIM), np.float32)

    return embed


def known_hashes(vectors: Path | None) -> dict[str, str]:
    """job_id -> content_hash of the vectors we already have."""
    if vectors is None or not vectors.exists():
        return {}
    t = pq.read_table(vectors, columns=["job_id", "content_hash"])
    return dict(zip(t.column("job_id").to_pylist(), t.column("content_hash").to_pylist()))


def _open_us(t: pa.Table) -> pa.Table:
    return t.filter(pc.and_(pc.is_null(t.column("closed_at")), pc.fill_null(pc.equal(t.column("is_us"), True), False)))


def todo(state: Path, known: dict[str, str], shard: int = 0, of: int = 1) -> Iterable[tuple[str, str, str]]:
    """(job_id, content_hash, text) for open US jobs in this shard that are new or changed."""
    for batch in pq.ParquetFile(state).iter_batches(batch_size=20_000, columns=STATE_COLUMNS):
        t = _open_us(pa.Table.from_batches([batch]))
        cols = (t.column(c).to_pylist() for c in ("job_id", "content_hash", "title", "company_name", "description"))
        for jid, h, title, company, desc in zip(*cols):
            if known.get(jid) == h:
                continue
            if of > 1 and shard_of(jid, of) != shard:
                continue
            yield jid, h, job_text(title, company, desc)


def _table(ids: list[str], hashes: list[str], vecs: np.ndarray) -> pa.Table:
    flat = pa.array(vecs.astype(np.float16).reshape(-1), type=pa.float16())
    return pa.table({"job_id": pa.array(ids, pa.string()), "content_hash": pa.array(hashes, pa.string()),
                     "vector": pa.FixedSizeListArray.from_arrays(flat, DIM).cast(SCHEMA.field("vector").type)}, schema=SCHEMA)


def embed_shard(state: Path, vectors: Path | None, out: Path, embed: Embedder, shard: int = 0, of: int = 1,
                chunk: int = 2048) -> int:
    """Embed this shard's new and changed jobs into `out`. Returns how many."""
    out.parent.mkdir(parents=True, exist_ok=True)
    w = pq.ParquetWriter(out, SCHEMA, compression="zstd")
    n = 0
    buf: list[tuple[str, str, str]] = []

    def flush() -> None:
        nonlocal n
        if buf:
            w.write_table(_table([b[0] for b in buf], [b[1] for b in buf], embed([b[2] for b in buf])))
            n += len(buf)
            buf.clear()

    for item in todo(state, known_hashes(vectors), shard, of):
        buf.append(item)
        if len(buf) >= chunk:
            flush()
    flush()
    w.close()
    return n


def combine(state: Path, vectors: Path | None, shard_files: list[Path], out: Path) -> dict:
    """Previous vectors + this run's shards, keeping only jobs that are open and US now, at their current content."""
    open_now: dict[str, str] = {}
    for batch in pq.ParquetFile(state).iter_batches(batch_size=100_000, columns=["job_id", "content_hash", "closed_at", "is_us"]):
        t = _open_us(pa.Table.from_batches([batch]))
        open_now.update(zip(t.column("job_id").to_pylist(), t.column("content_hash").to_pylist()))

    parts = [pq.read_table(f).cast(SCHEMA) for f in shard_files]
    fresh = {j for p in parts for j in p.column("job_id").to_pylist()}
    if vectors is not None and vectors.exists():
        prev = pq.read_table(vectors).cast(SCHEMA)
        parts.append(prev.filter(pa.array([j not in fresh for j in prev.column("job_id").to_pylist()])))
    merged = pa.concat_tables(parts) if parts else SCHEMA.empty_table()
    current = [open_now.get(j) == h for j, h in zip(merged.column("job_id").to_pylist(), merged.column("content_hash").to_pylist())]
    merged = merged.filter(pa.array(current, pa.bool_()))
    pq.write_table(merged, out, compression="zstd", row_group_size=50_000)
    return {"vectors": merged.num_rows, "embedded_this_run": len(fresh), "open_us_jobs": len(open_now),
            "not_embedded_yet": len(open_now) - merged.num_rows}
