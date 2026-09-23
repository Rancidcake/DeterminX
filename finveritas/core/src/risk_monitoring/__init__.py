"""Anomaly Alert System — continuous risk monitoring (section 10 of the V2 brief).

Extends V1's one-time Credibility Engine (`src/data_verifier.py`) pattern —
same CredibilityCheck-style PASS/WARN/FAIL/SKIP status shape — into a
reusable service that compares the current period's structural ratios
against the company's own historical range. It runs whenever fresh data is
ingested or an analysis is requested; no scheduler/real-time infra is added,
per the brief's explicit instruction not to over-build this.
"""
