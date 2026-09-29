"""Personal ALM engine — the Life Balance Sheet.

A person's life modelled as a controlled stochastic dynamical system: several
capitals (wealth, expertise, network, health) evolve under two scarce budgets
(time and money), buffeted by shocks; goals are liabilities that must be met on
time with a required confidence.

Build order (spec §16.4): data structures → deterministic sim → Nicolas
backtest → feasibility (MC + CVaR) → optimiser (Route A NLP) → MPC → output.
This package currently implements the first two stages.
"""

__version__ = "0.1.0"
