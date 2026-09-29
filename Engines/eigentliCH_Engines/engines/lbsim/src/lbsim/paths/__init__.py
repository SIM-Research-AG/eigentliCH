"""The vectorised Monte Carlo (``LifeBalancePaths``). numpy only; never imports casadi (LBSIM-03).

``market``     the market rule of LBSIM-07: state draws with common random numbers, per-state returns, inflation,
               property growth.
``engine``     the draft's Euler step of ``lbsim.model.dynamics``, vectorised over paths, monthly.
``reference``  the parity targets: the draft's per-path ``simulate`` verbatim, and lbsim's step one path at a time.
``household``  the stated plan read from the sheet, the adapter and the findings.
``build``      the artefact: bands in both bases, chances in the goal's basis, the allocation view.
"""
