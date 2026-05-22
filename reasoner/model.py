"""
Reasoner: a from-scratch Llama-style decoder-only transformer.

Architecture choices:
  - RMSNorm (simpler than LayerNorm, slight speedup)
  - Rotary Positional Embeddings (RoPE) for length generalization
  - SwiGLU activation in FFN (better than ReLU/GELU at same param count)
  - Grouped Query Attention (GQA) with fewer KV heads (saves KV cache memory)
  - No bias terms in linear layers
  - Tied input/output embeddings

The vocabulary is radically small (~3,643 tokens from the Up Goer Five word
list), so the embedding matrix is negligible (~7.5M params). Almost all 1.5B
parameters go into the transformer layers.

Default config: d_model=2048, n_layers=32, n_heads=32, d_ff=5504 (SwiGLU),
n_kv_heads=8 (GQA ratio 4:1). Total ~1.5B params.
"""

import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ReasonerConfig:
    vocab_size: int = 3643
    d_model: int = 2048
    n_layers: int = 32
    n_heads: int = 32
    n_kv_heads: int = 8          # GQA: 4 query heads per KV head
    d_ff: int = 5504             # SwiGLU intermediate size
    max_seq_len: int = 512       # word-level tokens, not BPE
    dropout: float = 0.0         # no dropout for pretraining (following Llama)
    rope_theta: float = 10000.0  # RoPE base frequency
    tie_embeddings: bool = True

    @property
    def head_dim(self) -> int:
        return self.d_model // self.n_heads


# --- Components ---

class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization."""

    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        norm = x.float().pow(2).mean(-1, keepdim=True).add(self.eps).rsqrt()
        return (x.float() * norm).type_as(x) * self.weight


def precompute_rope_frequencies(dim: int, max_seq_len: int, theta: float = 10000.0) -> torch.Tensor:
    """Precompute complex exponentials for RoPE."""
    freqs = 1.0 / (theta ** (torch.arange(0, dim, 2).float() / dim))
    t = torch.arange(max_seq_len, dtype=torch.float32)
    freqs = torch.outer(t, freqs)
    # Return as complex numbers for efficient rotation
    return torch.polar(torch.ones_like(freqs), freqs)  # e^(i * theta)


def apply_rope(x: torch.Tensor, freqs: torch.Tensor) -> torch.Tensor:
    """Apply rotary embeddings to query or key tensor.

    Args:
        x: (batch, seq_len, n_heads, head_dim)
        freqs: (seq_len, head_dim // 2) complex
    """
    # Reshape x to pairs: (batch, seq_len, n_heads, head_dim//2, 2)
    x_pairs = x.float().reshape(*x.shape[:-1], -1, 2)
    # Convert to complex
    x_complex = torch.view_as_complex(x_pairs)
    # Broadcast freqs to match: (1, seq_len, 1, head_dim//2)
    freqs = freqs.unsqueeze(0).unsqueeze(2)
    # Rotate
    x_rotated = x_complex * freqs
    # Back to real
    x_out = torch.view_as_real(x_rotated).flatten(-2)
    return x_out.type_as(x)


class GroupedQueryAttention(nn.Module):
    """Multi-head attention with grouped query attention (GQA).

    Uses fewer KV heads than query heads to save memory in the KV cache
    without significant quality loss.
    """

    def __init__(self, config: ReasonerConfig):
        super().__init__()
        self.n_heads = config.n_heads
        self.n_kv_heads = config.n_kv_heads
        self.head_dim = config.head_dim
        self.n_rep = self.n_heads // self.n_kv_heads  # query heads per KV head

        self.wq = nn.Linear(config.d_model, config.n_heads * self.head_dim, bias=False)
        self.wk = nn.Linear(config.d_model, config.n_kv_heads * self.head_dim, bias=False)
        self.wv = nn.Linear(config.d_model, config.n_kv_heads * self.head_dim, bias=False)
        self.wo = nn.Linear(config.n_heads * self.head_dim, config.d_model, bias=False)

    def forward(
        self,
        x: torch.Tensor,
        freqs: torch.Tensor,
        mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        batch, seq_len, _ = x.shape

        # Project to Q, K, V
        q = self.wq(x).view(batch, seq_len, self.n_heads, self.head_dim)
        k = self.wk(x).view(batch, seq_len, self.n_kv_heads, self.head_dim)
        v = self.wv(x).view(batch, seq_len, self.n_kv_heads, self.head_dim)

        # Apply RoPE to Q and K
        q = apply_rope(q, freqs)
        k = apply_rope(k, freqs)

        # Expand KV heads to match query heads (GQA)
        if self.n_rep > 1:
            k = k.unsqueeze(3).expand(-1, -1, -1, self.n_rep, -1).reshape(
                batch, seq_len, self.n_heads, self.head_dim
            )
            v = v.unsqueeze(3).expand(-1, -1, -1, self.n_rep, -1).reshape(
                batch, seq_len, self.n_heads, self.head_dim
            )

        # Transpose to (batch, n_heads, seq_len, head_dim)
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)

        # Scaled dot-product attention (uses Flash Attention when available)
        attn_out = F.scaled_dot_product_attention(
            q, k, v,
            attn_mask=mask,
            is_causal=(mask is None),  # use causal mask if no explicit mask
        )

        # Reshape and project output
        attn_out = attn_out.transpose(1, 2).contiguous().view(batch, seq_len, -1)
        return self.wo(attn_out)


class SwiGLUFFN(nn.Module):
    """Feed-forward network with SwiGLU activation.

    SwiGLU uses three weight matrices instead of two, with a gated activation:
        FFN(x) = (Swish(xW1) * xW3) W2

    For the same parameter count as a standard FFN with d_ff=8192,
    SwiGLU uses d_ff=5504 (since it has 3 matrices instead of 2).
    """

    def __init__(self, config: ReasonerConfig):
        super().__init__()
        self.w1 = nn.Linear(config.d_model, config.d_ff, bias=False)  # gate
        self.w2 = nn.Linear(config.d_ff, config.d_model, bias=False)  # down
        self.w3 = nn.Linear(config.d_model, config.d_ff, bias=False)  # up

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class TransformerBlock(nn.Module):
    """Pre-norm transformer block: RMSNorm -> Attention -> Residual -> RMSNorm -> FFN -> Residual."""

    def __init__(self, config: ReasonerConfig):
        super().__init__()
        self.attn_norm = RMSNorm(config.d_model)
        self.attn = GroupedQueryAttention(config)
        self.ffn_norm = RMSNorm(config.d_model)
        self.ffn = SwiGLUFFN(config)

    def forward(self, x: torch.Tensor, freqs: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        x = x + self.attn(self.attn_norm(x), freqs, mask)
        x = x + self.ffn(self.ffn_norm(x))
        return x


# --- Full Model ---

class Reasoner(nn.Module):
    """The Up Goer Five Reasoner: a 1.5B parameter decoder-only transformer
    that can only think in ~1,000 common English words.

    This model receives Up Goer Five text as input and generates Up Goer Five
    text as output. Both its input and output vocabulary are constrained to
    the UGF tokenizer's ~3,643 tokens.
    """

    def __init__(self, config: ReasonerConfig):
        super().__init__()
        self.config = config

        self.tok_emb = nn.Embedding(config.vocab_size, config.d_model)
        self.layers = nn.ModuleList([TransformerBlock(config) for _ in range(config.n_layers)])
        self.norm = RMSNorm(config.d_model)

        # Output projection — tied with input embeddings if configured
        if config.tie_embeddings:
            self.output = None  # will use tok_emb.weight
        else:
            self.output = nn.Linear(config.d_model, config.vocab_size, bias=False)

        # Precompute RoPE frequencies (not a parameter, but needs to be on device)
        self.register_buffer(
            "rope_freqs",
            precompute_rope_frequencies(config.head_dim, config.max_seq_len, config.rope_theta),
            persistent=False,
        )

        # Initialize weights
        self._init_weights()

    def _init_weights(self):
        """Initialize weights following GPT-2 / Llama conventions."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
            elif isinstance(module, nn.Embedding):
                torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)

        # Scale residual projections by 1/sqrt(2*n_layers) following GPT-2
        for layer in self.layers:
            torch.nn.init.normal_(
                layer.attn.wo.weight,
                mean=0.0,
                std=0.02 / math.sqrt(2 * self.config.n_layers),
            )
            torch.nn.init.normal_(
                layer.ffn.w2.weight,
                mean=0.0,
                std=0.02 / math.sqrt(2 * self.config.n_layers),
            )

    def forward(
        self,
        input_ids: torch.Tensor,
        labels: torch.Tensor | None = None,
        attention_mask: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """
        Args:
            input_ids: (batch, seq_len) token indices
            labels: (batch, seq_len) target token indices for loss computation.
                    Shifted internally (predicts next token).
            attention_mask: (batch, seq_len) 1 for real tokens, 0 for padding.

        Returns:
            dict with 'logits' and optionally 'loss'.
        """
        batch, seq_len = input_ids.shape
        assert seq_len <= self.config.max_seq_len, (
            f"Sequence length {seq_len} exceeds max {self.config.max_seq_len}"
        )

        # Token embeddings
        h = self.tok_emb(input_ids)

        # RoPE frequencies for this sequence length
        freqs = self.rope_freqs[:seq_len]

        # Build causal mask incorporating padding if needed
        mask = None
        if attention_mask is not None:
            # Convert padding mask to attention mask compatible with SDPA
            # Shape: (batch, 1, seq_len, seq_len)
            mask = attention_mask[:, None, None, :].expand(-1, -1, seq_len, -1)
            mask = mask.float().masked_fill(mask == 0, float("-inf")).masked_fill(mask == 1, 0.0)
            # Add causal mask
            causal = torch.triu(torch.ones(seq_len, seq_len, device=h.device), diagonal=1)
            causal = causal.masked_fill(causal == 1, float("-inf"))
            mask = mask + causal[None, None, :, :]

        # Transformer layers
        for layer in self.layers:
            h = layer(h, freqs, mask)

        h = self.norm(h)

        # Output logits
        if self.config.tie_embeddings:
            logits = F.linear(h, self.tok_emb.weight)
        else:
            logits = self.output(h)

        result = {"logits": logits}

        # Compute loss if labels provided
        if labels is not None:
            # Shift: predict token t+1 from position t
            shift_logits = logits[:, :-1, :].contiguous()
            shift_labels = labels[:, 1:].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, self.config.vocab_size),
                shift_labels.view(-1),
                ignore_index=-100,  # ignore padding in labels
            )
            result["loss"] = loss

        return result

    @torch.no_grad()
    def generate(
        self,
        input_ids: torch.Tensor,
        max_new_tokens: int = 256,
        temperature: float = 0.8,
        top_k: int = 50,
        top_p: float = 0.9,
        eos_token_id: int | None = None,
        repetition_penalty: float = 1.0,
        no_repeat_ngram_size: int = 0,
    ) -> torch.Tensor:
        """Autoregressive generation with top-k/top-p sampling.

        Optional anti-repetition controls (HuggingFace-compatible semantics):
          - repetition_penalty: divide positive logits / multiply negative logits
            for tokens that already appeared in the context. 1.0 = no effect;
            1.2-1.5 is typical. Catches token-level repetition.
          - no_repeat_ngram_size: forbid producing tokens that would create an
            n-gram already in the sequence. 0 = disabled; 3-5 typical. Catches
            phrase-level repetition (doom loops).
        Both currently assume batch_size=1 (the bench-generation case).
        """
        self.eval()

        for _ in range(max_new_tokens):
            # Crop to max_seq_len if needed
            idx_cond = input_ids if input_ids.shape[1] <= self.config.max_seq_len else input_ids[:, -self.config.max_seq_len:]

            result = self(idx_cond)
            logits = result["logits"][:, -1, :]  # last position

            # Anti-repetition: token-level penalty (HF-compatible).
            if repetition_penalty != 1.0 and input_ids.shape[1] > 0:
                seen = set(input_ids[0].tolist())
                for tok in seen:
                    if logits[0, tok] > 0:
                        logits[0, tok] = logits[0, tok] / repetition_penalty
                    else:
                        logits[0, tok] = logits[0, tok] * repetition_penalty

            # Anti-repetition: forbid tokens that would create a repeat n-gram.
            if no_repeat_ngram_size > 0 and input_ids.shape[1] >= no_repeat_ngram_size - 1:
                seq = input_ids[0].tolist()
                n = no_repeat_ngram_size
                prefix = tuple(seq[-(n - 1):]) if n > 1 else ()
                if n > 1:
                    forbidden = set()
                    for i in range(len(seq) - n + 1):
                        if tuple(seq[i:i + n - 1]) == prefix:
                            forbidden.add(seq[i + n - 1])
                    for tok in forbidden:
                        logits[0, tok] = float("-inf")

            if temperature > 0:
                logits = logits / temperature

                # Top-k filtering
                if top_k > 0:
                    v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                    logits[logits < v[:, [-1]]] = float("-inf")

                # Top-p (nucleus) filtering
                if top_p < 1.0:
                    sorted_logits, sorted_indices = torch.sort(logits, descending=True)
                    cumulative_probs = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)
                    sorted_indices_to_remove = cumulative_probs > top_p
                    sorted_indices_to_remove[:, 1:] = sorted_indices_to_remove[:, :-1].clone()
                    sorted_indices_to_remove[:, 0] = False
                    indices_to_remove = sorted_indices_to_remove.scatter(1, sorted_indices, sorted_indices_to_remove)
                    logits[indices_to_remove] = float("-inf")

                probs = F.softmax(logits, dim=-1)
                next_token = torch.multinomial(probs, num_samples=1)
            else:
                next_token = logits.argmax(dim=-1, keepdim=True)

            input_ids = torch.cat([input_ids, next_token], dim=1)

            if eos_token_id is not None and (next_token == eos_token_id).all():
                break

        return input_ids

    def count_parameters(self) -> dict[str, int]:
        """Count parameters by component."""
        counts = {
            "embedding": sum(p.numel() for p in self.tok_emb.parameters()),
            "attention": 0,
            "ffn": 0,
            "norm": 0,
        }
        for layer in self.layers:
            counts["attention"] += sum(p.numel() for p in layer.attn.parameters())
            counts["attention"] += sum(p.numel() for p in layer.attn_norm.parameters())
            counts["ffn"] += sum(p.numel() for p in layer.ffn.parameters())
            counts["ffn"] += sum(p.numel() for p in layer.ffn_norm.parameters())
        counts["norm"] += sum(p.numel() for p in self.norm.parameters())
        if self.output is not None:
            counts["output_proj"] = sum(p.numel() for p in self.output.parameters())
        else:
            counts["output_proj"] = 0  # tied with embedding
        counts["total"] = sum(p.numel() for p in self.parameters())
        return counts
