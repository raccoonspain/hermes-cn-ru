"""OCR one page image with rapidocr_onnxruntime — the default entry point
for this skill as of 2026-08-05 (D-023). Replaces ad-hoc inline OCR snippets.

Why this exists instead of calling `RapidOCR()` inline:
  1. **Thread count.** The bundled configs this script uses force
     `intra_op_num_threads`/`inter_op_num_threads` to `1`. The sandbox
     container is capped at 1.0 vCPU (`docker inspect`: NanoCpus=1e9), but
     the package default (`-1`/"auto") makes onnxruntime spawn one thread
     per HOST-visible core (`nproc` reports 8) — 8 threads fighting over a
     1-core cgroup quota. Forcing 1 thread cut a full-page call from 71s to
     17.5s on the same image, byte-identical output (verified, not assumed).
     **Do not try to go faster by running several OCR calls concurrently
     instead** — the 1-vCPU cap is process-wide, so concurrent calls just
     divide that one core more ways (tested: 4 concurrent calls, ~114s
     each, ~117s total wall time — worse than 4 sequential calls at
     17.5s = 70s total). Sequential, one page at a time, is the fast path.
  2. **Cyrillic.** `--lang cyrillic` swaps in the bundled
     `models/rapidocr-cyrillic` recognition model. The package's own
     default model is Chinese+English — on Cyrillic text it has no
     matching vocabulary and silently emits Latin lookalikes instead
     (С→C, Н→H, О→O...) rather than failing loudly. See D-022. Passing a
     `config_path` here is NOT sensitive to your current working
     directory — `RapidOCR`'s `update_model_path()` always resolves
     relative Det/Cls model paths against the *package's own* directory,
     never against CWD or where config.yaml lives (verified live,
     2026-08-05 — don't rediscover this the hard way, it cost a real
     session real time chasing a CWD theory that wasn't true).
  3. **Token cost.** Full recognized text goes to `out_txt` on disk. Stdout
     is one terse summary line. Do not read this script's stdout expecting
     the transcription — read the output file, and only the parts you
     need (grep for a line number, tail -c on a region), not the whole
     thing pasted into your own reasoning. A single growing chat session
     that echoes full OCR dumps repeatedly is the single biggest cost
     driver we found in practice (D-023) — much bigger than the OCR
     compute itself.

Usage:
  python3 ocr_page.py <input.jpg|png> <output.txt> [--lang cyrillic|latin] [--conf]

  --lang cyrillic   Use models/rapidocr-cyrillic (Russian/Cyrillic docs).
  --lang latin      Use models/rapidocr-latin (default — everything else:
                     English, mixed, numbers-only, tables).
  --conf            Prefix each output line with its confidence score
                     (0.00-1.00) — useful when you expect to need a
                     ⚠-table of uncertain spots afterward.

Runs as its own process on purpose (not imported and called in-loop) —
isolates the ONNX runtime session so a crash/OOM on one page can't take
down a longer-running orchestrator, and keeps this fast path a single,
reviewed call site instead of every session hand-rolling its own.
"""
import os
import sys
import time
import argparse

os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIGS = {
    'cyrillic': os.path.join(SKILL_DIR, 'models', 'rapidocr-cyrillic', 'config.yaml'),
    'latin': os.path.join(SKILL_DIR, 'models', 'rapidocr-latin', 'config.yaml'),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('out_txt')
    ap.add_argument('--lang', choices=['cyrillic', 'latin'], default='latin')
    ap.add_argument('--conf', action='store_true',
                     help='prefix each line with its confidence score')
    args = ap.parse_args()

    config_path = CONFIGS[args.lang]
    if not os.path.exists(config_path):
        print(f'FAIL: bundled config missing at {config_path} — sandbox '
              f'not synced with skill assets, see D-022/D-023', file=sys.stderr)
        sys.exit(1)

    from rapidocr_onnxruntime import RapidOCR  # import after env vars are set

    t0 = time.time()
    engine = RapidOCR(config_path=config_path)
    result, _ = engine(args.image)
    elapsed = time.time() - t0

    lines = result or []
    with open(args.out_txt, 'w') as f:
        for bbox, text, score in lines:
            if args.conf:
                f.write(f'{score:.2f}\t{text}\n')
            else:
                f.write(f'{text}\n')

    avg_conf = sum(s for _, _, s in lines) / len(lines) if lines else 0.0
    low_conf = sum(1 for _, _, s in lines if s < 0.75)
    print(f'{args.image} [{args.lang}]: {len(lines)} lines, '
          f'avg_conf={avg_conf:.2f}, {low_conf} below 0.75, '
          f'{elapsed:.1f}s -> {args.out_txt}')
    if low_conf:
        print(f'  {low_conf} low-confidence line(s) — read {args.out_txt} '
              f'with --conf next time, or zoom-crop and re-run on just '
              f'those regions rather than the whole page again.')


if __name__ == '__main__':
    main()
