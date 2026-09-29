"""The numpy model: a port of the draft's ``personal_alm/model`` (params, dynamics, state, controls, bvg, canton,
fiscal, and the expertise and venture types the state needs). No casadi here or below (LBSIM-03).

The port is the draft's code with two changes, both in the table loading of ``bvg`` and ``canton``: the tables
are the lbsim calibration's seed records ``social-insurance`` and ``canton-tax`` instead of a folder that does not
exist (LBSIM-12). Everything else is the draft's, line for line, so golden layer A can hold it to 1e-9.
"""
