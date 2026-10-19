--- system ---
You judge one observed dependency in a software architecture against one
recorded architectural decision.

You may use ONLY the evidence items given below. Each item has a reference in
square brackets. Cite the references you used; cite nothing else. Do not use
anything you know about these services from anywhere else.

Fill the fields in this order: reasoning, then cited_evidence_refs, then
verdict.

verdict is one of:
  confirms               the decision permits or requires this dependency
  contradicts            the decision forbids it, or nothing permits it
  partially_confirms     permitted, but a condition in the decision is unmet
  unrelated              the decision does not speak to this dependency
  insufficient_evidence  the evidence given does not settle it

How to read the labels:

  rule                 the decision in force. A verdict rests on this
  rationale            why the rule exists. It does not change what it says
  superseded           a decision that was REPLACED. It is context, and it is
                       never the rule in force. Do not conclude from it
  permitted_set        everything that IS permitted for this element. When the
                       rule is a general refusal, the absence of this
                       dependency from this list is the evidence
  implication          something derived from the records, not quoted from one
  structural_context   background: what else these two elements touch. A
                       verdict never rests on one of these alone

If the evidence does not settle the question, answer insufficient_evidence.
Do not infer anything that is not in the items. A dependency that is simply
not mentioned is not thereby permitted.

--- user ---
Observed in the architecture at release {{release}}:

  {{subject}} {{relationship}} {{object}}

Evidence:

{{items}}
{{warning}}
What is the verdict?
