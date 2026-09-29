"""The cockpit: a local control surface over the same code paths the CLI uses.

Not a second implementation. Every endpoint calls `pcp.pipeline` and `pcp.reporting`, so a result seen
here is the result the CLI would write.
"""
