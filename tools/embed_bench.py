"""Measure what the matcher would cost on this runner. Prints timings only (public logs).

1. Job vectors: embed a random sample of open US jobs with Recrutas's model (bge-small-en-v1.5,
   full-precision ONNX, mean pooling, normalized; matches production at cosine 1.0), using the
   text Recrutas embeds: title, company, first 1,000 characters of the description.
2. Matching: score synthetic user vectors against synthetic job vectors at full catalog size
   and keep each user's top 300. Synthetic, so no user data comes near this public repo.
"""
from __future__ import annotations

import argparse
import os
import time

import duckdb
import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

MODEL = "Xenova/bge-small-en-v1.5"


def load_model():
    tok = Tokenizer.from_file(hf_hub_download(MODEL, "tokenizer.json"))
    tok.enable_truncation(512)
    tok.enable_padding()
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = os.cpu_count() or 2
    sess = ort.InferenceSession(hf_hub_download(MODEL, "onnx/model.onnx"), opts, providers=["CPUExecutionProvider"])
    return tok, sess, {i.name for i in sess.get_inputs()}


def embed(tok, sess, names, texts: list[str]) -> np.ndarray:
    enc = tok.encode_batch(texts)
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    feeds = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in names:
        feeds["token_type_ids"] = np.zeros_like(ids)
    h = sess.run(None, feeds)[0]
    v = (h * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
    return (v / np.linalg.norm(v, axis=1, keepdims=True)).astype(np.float32)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sample", type=int, default=20000)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--jobs", type=int, default=875000, help="catalog size for the matching test")
    p.add_argument("--users", type=int, nargs="+", default=[21, 1000, 10000])
    args = p.parse_args()
    print(f"cpus: {os.cpu_count()}")

    state = hf_hub_download(os.environ.get("HF_DATASET", "recrutas/us-jobs"), "state/jobs.parquet", repo_type="dataset")
    texts = [r[0] for r in duckdb.sql(f"""
        SELECT concat_ws(' ', title, company_name, left(coalesce(description, ''), 1000))
        FROM read_parquet('{state}') WHERE closed_at IS NULL AND is_us
        USING SAMPLE {args.sample} ROWS (reservoir, 7)""").fetchall()]
    texts.sort(key=len)  # similar lengths per batch: far less padding
    tok, sess, names = load_model()
    embed(tok, sess, names, texts[: args.batch])  # warm up
    t = time.perf_counter()
    for i in range(0, len(texts), args.batch):
        embed(tok, sess, names, texts[i: i + args.batch])
    rate = len(texts) / (time.perf_counter() - t)
    print(f"job vectors: {rate:.1f} jobs/s on {len(texts)} jobs "
          f"→ {875000 / rate / 60:.0f} runner-min for 875K, {5000 / rate / 60:.1f} min per 5K new jobs")

    rng = np.random.default_rng(7)
    jobs = rng.standard_normal((args.jobs, 384), dtype=np.float32)
    jobs /= np.linalg.norm(jobs, axis=1, keepdims=True)
    for n in args.users:
        users = rng.standard_normal((n, 384), dtype=np.float32)
        t = time.perf_counter()
        for i in range(0, n, 256):
            s = users[i: i + 256] @ jobs.T
            np.argpartition(-s, 300, axis=1)[:, :300]
        print(f"matching: {n} users × {args.jobs} jobs → top 300 each in {time.perf_counter() - t:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
