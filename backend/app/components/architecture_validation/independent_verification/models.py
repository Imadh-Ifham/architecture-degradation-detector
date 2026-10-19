"""Independent verification data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py, which is where
    `Objection` and `Verification` live: M6 reads the objections off a
    verification and M8 publishes them, so neither shape is this directory's
    alone.

    What is left is the one string that names the mechanism. It is here
    because nothing outside this subcomponent chooses it, and it is a named
    constant because it is recorded on every output and compared across runs
    from different weeks - a literal spelled twice is two mechanisms as far as
    any later comparison can tell.

    There was a `VerificationRequest` here, and V2 removed it. The renderer
    takes the `PrimaryVerdict` itself, so the request object was a lossy copy
    of one - it carried no `cited_evidence_refs`, which the prompt renders and
    without which `citation_does_not_support` is unanswerable. V5's
    `BlindRequest` is a different case and will be kept: a shape with no field
    that can hold a verdict is a structural guarantee, and this one guaranteed
    nothing by leaving something out.
"""

MECHANISM_CRITICAL_REFRAMING = "critical-reframing"
MECHANISM_BLIND_VERDICT = "blind-verdict"
"""The two arms, named.

`critical-reframing` is shown the verdict and asked what is wrong with the
argument. `blind-verdict` is shown the evidence and not the answer, and
returns a verdict of its own. One string on every output is what makes a
later comparison of the two a query rather than a harness.
"""
