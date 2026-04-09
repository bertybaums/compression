"""
Evaluation metrics for round-trip fidelity testing.

All metrics compare an original English text to a reconstructed English text
that has passed through the UGF vocabulary bottleneck.

Metrics:
  1. BERTScore — token-level semantic similarity via contextual embeddings
  2. Sentence cosine similarity — embedding-level meaning preservation
  3. NLI bidirectional entailment — logical equivalence check
  4. BLEU / ROUGE — surface-level baselines
  5. LLM judge — gpt-oss-120b rates reasoning quality on 0-4 rubric
"""

from dataclasses import dataclass, field
from typing import Optional

import torch


@dataclass
class MetricResult:
    """Container for a single metric's results across a batch."""
    name: str
    scores: list[float]
    metadata: dict = field(default_factory=dict)

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def median(self) -> float:
        if not self.scores:
            return 0.0
        s = sorted(self.scores)
        n = len(s)
        if n % 2 == 0:
            return (s[n // 2 - 1] + s[n // 2]) / 2
        return s[n // 2]

    @property
    def std(self) -> float:
        if len(self.scores) < 2:
            return 0.0
        m = self.mean
        return (sum((x - m) ** 2 for x in self.scores) / (len(self.scores) - 1)) ** 0.5

    def summary(self) -> dict:
        return {
            "name": self.name,
            "n": len(self.scores),
            "mean": round(self.mean, 4),
            "median": round(self.median, 4),
            "std": round(self.std, 4),
            "min": round(min(self.scores), 4) if self.scores else 0.0,
            "max": round(max(self.scores), 4) if self.scores else 0.0,
        }


# --- BERTScore ---

class BERTScoreMetric:
    """Token-level semantic similarity using contextual embeddings.

    Uses the bert-score library with DeBERTa-xlarge-MNLI for high-quality
    token alignment scores.
    """

    def __init__(self, model_type: str = "microsoft/deberta-xlarge-mnli", device: Optional[str] = None):
        self.model_type = model_type
        self.device = device

    def compute(self, originals: list[str], reconstructed: list[str]) -> MetricResult:
        from bert_score import score as bert_score

        P, R, F1 = bert_score(
            reconstructed, originals,
            model_type=self.model_type,
            device=self.device,
            verbose=False,
        )
        return MetricResult(
            name="bertscore_f1",
            scores=F1.tolist(),
            metadata={"precision_mean": P.mean().item(), "recall_mean": R.mean().item()},
        )


# --- Sentence Cosine Similarity ---

class CosineSimilarityMetric:
    """Embedding-level meaning preservation using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: Optional[str] = None):
        self.model_name = model_name
        self._model = None
        self.device = device

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device=self.device)

    def compute(self, originals: list[str], reconstructed: list[str]) -> MetricResult:
        self._load_model()

        emb_orig = self._model.encode(originals, convert_to_tensor=True, show_progress_bar=False)
        emb_recon = self._model.encode(reconstructed, convert_to_tensor=True, show_progress_bar=False)

        # Cosine similarity per pair
        cos_sim = torch.nn.functional.cosine_similarity(emb_orig, emb_recon, dim=1)

        return MetricResult(
            name="cosine_similarity",
            scores=cos_sim.tolist(),
        )


# --- NLI Bidirectional Entailment ---

class NLIEntailmentMetric:
    """Logical equivalence check via Natural Language Inference.

    For each (original, reconstructed) pair, checks bidirectional entailment:
    - Does original entail reconstructed?
    - Does reconstructed entail original?

    If both directions entail, the meaning is preserved. The score is the
    minimum of the two entailment probabilities (conservative estimate).
    """

    def __init__(self, model_name: str = "facebook/bart-large-mnli", device: Optional[str] = None):
        self.model_name = model_name
        self._pipeline = None
        self.device = device

    def _load_pipeline(self):
        if self._pipeline is None:
            from transformers import pipeline
            self._pipeline = pipeline(
                "zero-shot-classification",
                model=self.model_name,
                device=0 if self.device == "cuda" or (self.device is None and torch.cuda.is_available()) else -1,
            )

    def _entailment_score(self, premise: str, hypothesis: str) -> float:
        """Get P(entailment) for premise -> hypothesis."""
        result = self._pipeline(
            premise,
            candidate_labels=["entailment"],
            hypothesis_template=hypothesis + " {}",
            multi_label=True,
        )
        return result["scores"][0]

    def compute(self, originals: list[str], reconstructed: list[str]) -> MetricResult:
        self._load_pipeline()

        scores = []
        forward_scores = []
        backward_scores = []

        for orig, recon in zip(originals, reconstructed):
            # Truncate long texts to avoid OOM (NLI models have limited context)
            orig_trunc = orig[:1000]
            recon_trunc = recon[:1000]

            fwd = self._entailment_score(orig_trunc, recon_trunc)
            bwd = self._entailment_score(recon_trunc, orig_trunc)

            forward_scores.append(fwd)
            backward_scores.append(bwd)
            scores.append(min(fwd, bwd))  # conservative: both must entail

        return MetricResult(
            name="nli_bidirectional_entailment",
            scores=scores,
            metadata={
                "forward_mean": sum(forward_scores) / len(forward_scores),
                "backward_mean": sum(backward_scores) / len(backward_scores),
            },
        )


# --- BLEU / ROUGE ---

class BLEUMetric:
    """Surface-level n-gram overlap (sanity check baseline)."""

    def compute(self, originals: list[str], reconstructed: list[str]) -> MetricResult:
        from collections import Counter

        scores = []
        for orig, recon in zip(originals, reconstructed):
            # Simple unigram BLEU (precision of reconstructed n-grams in original)
            orig_tokens = orig.lower().split()
            recon_tokens = recon.lower().split()

            if not recon_tokens:
                scores.append(0.0)
                continue

            orig_counts = Counter(orig_tokens)
            recon_counts = Counter(recon_tokens)

            # Clipped counts
            clipped = sum(min(recon_counts[w], orig_counts[w]) for w in recon_counts)
            precision = clipped / len(recon_tokens)

            # Brevity penalty
            bp = min(1.0, len(recon_tokens) / max(len(orig_tokens), 1))

            scores.append(bp * precision)

        return MetricResult(name="bleu_unigram", scores=scores)


class ROUGEMetric:
    """ROUGE-L (longest common subsequence) for recall-oriented comparison."""

    def compute(self, originals: list[str], reconstructed: list[str]) -> MetricResult:
        scores = []
        for orig, recon in zip(originals, reconstructed):
            orig_tokens = orig.lower().split()
            recon_tokens = recon.lower().split()

            if not orig_tokens or not recon_tokens:
                scores.append(0.0)
                continue

            # LCS length
            lcs_len = self._lcs_length(orig_tokens, recon_tokens)
            precision = lcs_len / len(recon_tokens)
            recall = lcs_len / len(orig_tokens)

            if precision + recall == 0:
                scores.append(0.0)
            else:
                f1 = 2 * precision * recall / (precision + recall)
                scores.append(f1)

        return MetricResult(name="rouge_l", scores=scores)

    @staticmethod
    def _lcs_length(a: list[str], b: list[str]) -> int:
        """Compute length of longest common subsequence."""
        m, n = len(a), len(b)
        # Space-optimized LCS
        prev = [0] * (n + 1)
        curr = [0] * (n + 1)
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    curr[j] = prev[j - 1] + 1
                else:
                    curr[j] = max(prev[j], curr[j - 1])
            prev, curr = curr, [0] * (n + 1)
        return prev[n]


# --- LLM Judge ---

class LLMJudgeMetric:
    """Use gpt-oss-120b to rate reasoning quality on the good-thinking-bot rubric.

    Scores 0-4:
      0: Completely wrong or irrelevant
      1: Mentions the topic but reasoning is incorrect
      2: Partially correct reasoning with significant gaps
      3: Mostly correct with minor gaps
      4: Fully correct and well-articulated

    This metric requires MindRouter API access.
    """

    def __init__(self, api_base: str = "https://mindrouter.uidaho.edu/v1", api_key: str = "", model: str = "openai/gpt-oss-120b"):
        self.api_base = api_base
        self.api_key = api_key
        self.model = model

    def compute(self, originals: list[str], reconstructed: list[str]) -> MetricResult:
        import asyncio
        scores = asyncio.run(self._compute_async(originals, reconstructed))
        return MetricResult(name="llm_judge", scores=scores)

    async def _compute_async(self, originals: list[str], reconstructed: list[str]) -> list[float]:
        import aiohttp
        import json
        import re

        scores = []
        connector = aiohttp.TCPConnector(ssl=False)

        async with aiohttp.ClientSession(connector=connector) as session:
            for orig, recon in zip(originals, reconstructed):
                prompt = (
                    "You are evaluating whether a simplified explanation preserves "
                    "the meaning and reasoning of the original text.\n\n"
                    f"ORIGINAL:\n{orig}\n\n"
                    f"RECONSTRUCTED (after passing through a vocabulary bottleneck):\n{recon}\n\n"
                    "Rate the reconstructed text on this scale:\n"
                    "0: Completely wrong or irrelevant\n"
                    "1: Mentions the topic but reasoning is incorrect\n"
                    "2: Partially correct reasoning with significant gaps\n"
                    "3: Mostly correct with minor gaps\n"
                    "4: Fully correct and well-articulated\n\n"
                    "Respond with ONLY a single digit (0-4)."
                )

                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.0,
                }
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }

                try:
                    async with session.post(
                        f"{self.api_base}/chat/completions",
                        json=payload, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            content = data["choices"][0]["message"].get("content", "")
                            if content:
                                # Extract digit from response
                                match = re.search(r"[0-4]", content)
                                if match:
                                    scores.append(float(match.group()))
                                    continue
                except Exception:
                    pass

                scores.append(-1.0)  # failed

        return scores


# --- Convenience ---

def compute_all_metrics(
    originals: list[str],
    reconstructed: list[str],
    device: Optional[str] = None,
    include_llm_judge: bool = False,
    llm_api_key: str = "",
) -> dict[str, MetricResult]:
    """Compute all metrics on a batch of (original, reconstructed) pairs.

    Args:
        originals: List of original English texts.
        reconstructed: List of reconstructed English texts (after round-trip).
        device: Device for model-based metrics ("cuda" or "cpu").
        include_llm_judge: Whether to include the LLM judge metric (requires API).
        llm_api_key: MindRouter API key for the LLM judge.

    Returns:
        Dict mapping metric name to MetricResult.
    """
    results = {}

    print("Computing BLEU...")
    results["bleu"] = BLEUMetric().compute(originals, reconstructed)

    print("Computing ROUGE-L...")
    results["rouge_l"] = ROUGEMetric().compute(originals, reconstructed)

    print("Computing cosine similarity...")
    results["cosine"] = CosineSimilarityMetric(device=device).compute(originals, reconstructed)

    print("Computing BERTScore...")
    results["bertscore"] = BERTScoreMetric(device=device).compute(originals, reconstructed)

    print("Computing NLI entailment...")
    results["nli"] = NLIEntailmentMetric(device=device).compute(originals, reconstructed)

    if include_llm_judge and llm_api_key:
        print("Computing LLM judge scores...")
        results["llm_judge"] = LLMJudgeMetric(api_key=llm_api_key).compute(originals, reconstructed)

    return results
