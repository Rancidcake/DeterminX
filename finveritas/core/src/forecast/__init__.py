"""Forward-looking analysis: Assumption Validation + Forecast Engine.

    User assumption -> reference data (historical CAGR, guidance, macro)
        -> Python normalization -> Python comparison -> deviation
        -> deterministic risk/status -> LLM explains WHY.

The LLM never decides whether an assumption is realistic (section 6) and
never changes the forecast number it is asked to explain (section 7).
"""
