# golden/

The frozen references. The raw snapshot here is the reference for every downstream golden
test (datafeed engine page, section 5): its checksum must match its manifest.

| File | What it is |
|---|---|
| `snapshot_2026-01-05/manifest.json` | The `Snapshot` manifest of `matlab-m_ts-2026-01-05.r3`, with its checksum |
| `snapshot_2026-01-05/panel.json` | Its full panel (`panel@1.1.0`) |
| `snapshot_2026-01-05/definitions.json` | Its 704 series definitions (16 x 44), ticker included |
| `snapshot_2026-01-05/zero_rule.json` | What MATLAB's zeros became, per series |
| `public_2026-09-27.json` | The 16 public responses the fills use, as fetched on 2026-09-27 |
| `market_2026-09-27.json` | The 17 market responses the market layer uses (Cboe SKEW, VXFXI, VXEWZ; BIS broad NEER for 14 areas), as fetched on 2026-09-27 (DF-18) |

`bootstrap --frozen --offline` rebuilds the store from these alone; the tests do exactly
that. `test_loaders.py` checks that importing the real `M_TS.mat` reproduces the frozen
checksum.

Refresh:

```bash
python -m datafeed bootstrap --freeze-raw              # after a new M_TS.mat (new snapshot id!)
python -m datafeed bootstrap --refresh --freeze-public # fetch the public series again
python -m datafeed bootstrap --refresh --freeze-market # fetch the market series again
```

A new M_TS.mat is a new snapshot: change `import.matlab.snapshot_id` and `as_of` first,
because a used id is immutable.
