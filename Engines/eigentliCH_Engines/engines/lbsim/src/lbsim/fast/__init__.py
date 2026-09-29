"""The fast half: a port of the draft's deterministic gameplan (``app/gameplan``, ``app/paths``,
``app/findings``, ``app/plausibility``, ``app/search``, ``app/asks``, ``app/workflow``), the one earning-power
computation (LBSIM-11) and the findings artefact built on them. No casadi here or below (LBSIM-03).

The draft's hidden chain ``gameplan -> onboarding -> cases -> optim -> casadi`` is cut: the one alias ``gameplan``
read from ``onboarding`` is restated in ``gameplan``. The lbsim behaviours of calibration 1.1.0 ride in an optional
``lbsim`` block of the submission, which a draft submission never has; without it every function computes what
the draft computes.
"""
