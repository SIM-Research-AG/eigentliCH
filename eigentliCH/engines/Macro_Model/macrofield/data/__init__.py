"""The data layer: connectors, provenance, cache, manifest, and quantity assembly.

Every value that reaches the model passes through here, and every value carries a provenance record.
The single sanctioned route from this layer into the model is
`macrofield.data.integrity.check_model_inputs`, which refuses synthetic, interpolated or derived series
unless a caller has explicitly opted into them.
"""
