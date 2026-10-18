# C4-ADR-005 — torch as an inference-only runtime dependency, CPU wheels

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T03 Tooling & quality gates

## Context

CLAUDE.md §2 forbids deep-learning training anywhere in C4, but allows two
pretrained models **for inference only**: a sentence-transformers encoder for
evidence retrieval (`all-MiniLM-L6-v2`) and an NLI cross-encoder for the
faithfulness audit (`cross-encoder/nli-deberta-v3-base`). `sentence-transformers`
depends on **torch**, so torch must be installed even though C4 never defines,
trains or fine-tunes a model.

The dependency check in C4-ADR-000 §3 found that the default PyPI torch wheel for
Linux pulls ~15 `nvidia-*` CUDA packages (several GB). Nothing in C4 uses a GPU:
the encoder and the judge run on a handful of short texts per run.

## Decision

1. torch is a **runtime dependency for inference only**, installed through the
   `scoring-ml` dependency group (`uv sync --group scoring-ml`), not the default
   install. No C4 module may import `torch` directly — models are reached only
   through the `TextEmbedder` and `EntailmentJudge` ports, implemented under
   `app/infrastructure/ai/`. The layer-boundary test
   (`tests/components/degradation_scoring/test_layer_boundaries.py`) already fails on
   a `torch` import inside the component.
2. torch is pinned to the **CPU-only wheel index** in `backend/pyproject.toml`
   (`[[tool.uv.index]] pytorch-cpu`, `explicit = true`, with
   `[tool.uv.sources] torch = { index = "pytorch-cpu" }`). torch is listed directly in
   the `scoring-ml` group because uv applies index pins only to direct dependencies.

## Alternatives considered

- **Default PyPI torch.** Rejected: multi-GB CUDA downloads on Linux/CI for no use.
- **ONNX Runtime with exported models.** Avoids torch entirely, but adds an export
  step and a second model format to document and defend; not worth it for PP1.
- **Hosted embedding / NLI APIs.** Rejected: adds cost, network dependence and a
  non-reproducible judge to the faithfulness audit.

## Consequences

- Verified on 2026-10-18: `uv.lock` resolves torch 2.14.1 from
  `https://download.pytorch.org/whl/cpu`, with **zero** `nvidia-*`/`triton` packages,
  and no previously locked package changed version.
- Developers who only work on ingestion/features/scoring never download torch
  (`uv sync` without the group).
- If a GPU is ever wanted, that is a new decision record, not a silent change of index.
