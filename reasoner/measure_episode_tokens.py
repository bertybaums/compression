"""
Per-episode token-count + truncation measurement for the English-vocab baseline
(docs/english-baseline-design-2026-05-24.md -- "report per-episode token counts").

Tokenizes each SFT record the way the trainer does -- [BOS] + prompt + response +
[EOS] under the arm's own vocabulary (cf. UGFSFTDataset.__getitem__) -- and
reports the length distribution plus the fraction exceeding max_seq_len (those get
their response tail truncated during training).

Run once per arm to (a) quantify the Sheffer-stroke "longer derivations" cost
(UGF tokens-per-episode vs English over the same content), and (b) check the
truncation asymmetry at 512 (English responses run ~1.2-1.4x longer in words).

Usage (fortyfive):
  python3 -m reasoner.measure_episode_tokens \
      --corpus corpus/processed/ugf_n_sft_400k.jsonl \
      --vocab wordlist/vocab_final.json --label UGF-N
  python3 -m reasoner.measure_episode_tokens \
      --corpus corpus/processed/english_n_sft.jsonl \
      --vocab wordlist/vocab_english_40k.json --label English-N
"""
import argparse
import json

from tokenizer.ugf_tokenizer import UGFTokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--vocab", default=None, help="vocab_path; None -> UGF default")
    ap.add_argument("--max-seq-len", type=int, default=512)
    ap.add_argument("--label", default="")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    tok = UGFTokenizer(vocab_path=args.vocab)
    unk_id = tok._convert_token_to_id("<UNK>")

    full_lens, resp_lens = [], []
    n_unk = n_resp_tok = 0
    with open(args.corpus) as f:
        for i, line in enumerate(f):
            if args.limit and i >= args.limit:
                break
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            prompt = (r.get("prompt") or "").strip()
            resp = (r.get("response") or "").strip()
            if not prompt or not resp:
                continue
            pids = tok.encode(prompt, add_special_tokens=False)
            rids = tok.encode(resp, add_special_tokens=False)
            full_lens.append(1 + len(pids) + len(rids) + 1)  # BOS + prompt + resp + EOS
            resp_lens.append(len(rids))
            n_unk += sum(1 for t in rids if t == unk_id)
            n_resp_tok += len(rids)

    full_lens.sort()
    resp_lens.sort()
    n = len(full_lens)

    def pct(arr, p):
        return arr[min(len(arr) - 1, int(p * len(arr)))] if arr else 0

    over = sum(1 for L in full_lens if L > args.max_seq_len)
    print(f"=== {args.label or args.corpus} (vocab={args.vocab or 'UGF default'}) ===")
    print(f"records: {n}")
    if n:
        print(f"full episode tokens  mean={sum(full_lens)/n:.1f} p50={pct(full_lens, .5)} "
              f"p90={pct(full_lens, .9)} p99={pct(full_lens, .99)} max={full_lens[-1]}")
        print(f"response tokens      mean={sum(resp_lens)/n:.1f} p50={pct(resp_lens, .5)} "
              f"p90={pct(resp_lens, .9)} p99={pct(resp_lens, .99)} max={resp_lens[-1]}")
        print(f"truncated (>{args.max_seq_len}): {over} ({over/n*100:.2f}%)")
        rate = (n_unk / n_resp_tok * 100) if n_resp_tok else 0.0
        print(f"response UNK rate: {n_unk}/{n_resp_tok} ({rate:.3f}%)")


if __name__ == "__main__":
    main()
