"""Python reference model of the EA's deterministic rules.

It mirrors EA/Include/ClaudeEA/*.mqh function-for-function so the rules can be unit-tested
and replayed without a terminal. Passing these tests verifies the SPECIFIED LOGIC; it does
not verify the MQL5 build, which must be compiled and tested in MetaEditor/Strategy Tester.
"""
