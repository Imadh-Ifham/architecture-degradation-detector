"""Degradation scoring ports.

Author: Dahami
Date: 2026-10-14
Description:
    Protocols for everything C4 needs from outside the component: databases,
    git history, AI models and external tools. Implementations live under
    app/infrastructure/ (INSTRUCTIONS §7.1); tests use in-memory fakes.

    Scaffold only (C4-T02). Each Protocol is added by the first task that
    needs it, together with its tests:

      * DegradationEventSource   - C3 events for a (system, release)   C4-T08
      * ArchitectureGraphSource  - validated graph as a DiGraph        C4-T09
      * CommitHistorySource      - mined commit rows between tags      C4-T12
      * MiningCache              - cached commit rows                  C4-T12
      * AdrIndexSource           - C2 ADR index (optional)             C4-T16
      * ScoringRunRepository     - persisted manifest and report       C4-T20
      * TextGenerator            - LLM text generation                 C4-T22
      * GenerationCache          - cached LLM generations              C4-T22
      * TextEmbedder             - sentence embeddings                 C4-T23
      * EntailmentJudge          - NLI entailment scores               C4-T25
      * RefactoringDetector      - RefactoringMiner operations         C4-T29
"""
