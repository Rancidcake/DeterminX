"""Working Capital & Credit Intelligence (sections 11-14 of the V2 brief).

All working-capital math (WCG, minimum NWC, estimated MPBF, DSO/DPO/CCC) is
plain Python. MPBF is always labelled ESTIMATED — this is explicitly NOT a
bank-grade computation (section 13): precise MPBF/Drawing Power needs
existing sanctioned limits, inventory/receivables ageing, borrower
contribution history, and CMA data that FinVeritas does not ingest.
"""
