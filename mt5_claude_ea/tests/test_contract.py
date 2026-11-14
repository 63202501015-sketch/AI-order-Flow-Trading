"""Static contract checks between the MQL5 sources and the Python bridge, plus safe defaults.
These read the .mq5/.mqh text; they do not compile or execute MQL5."""
import os
import re
import subprocess
import sys

from bridge.models import SignalRequest, SignalResponse

ROOT = os.path.join(os.path.dirname(__file__), "..")
EA = os.path.join(ROOT, "EA")


def read(*parts):
    with open(os.path.join(EA, *parts), encoding="utf-8") as fh:
        return fh.read()


def all_sources():
    out = {}
    for base, _, files in os.walk(EA):
        for f in files:
            if f.endswith((".mq5", ".mqh")):
                out[f] = open(os.path.join(base, f), encoding="utf-8").read()
    return out


def test_bracket_lint_passes():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools_mql_lint.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_sources_are_ascii():
    for name, src in all_sources().items():
        assert src.isascii(), name


def test_request_keys_match_bridge_schema():
    src = read("Include", "ClaudeEA", "Bridge.mqh")
    body = src[src.index("bool CaiBuildRequest"):src.index("int CaiHttp")]
    keys = set(re.findall(r'\\"([a-z_]+)\\":', body))
    candle = {"time", "open", "high", "low", "close"}
    assert keys - candle == set(SignalRequest.model_fields)
    assert candle <= keys


def test_response_keys_match_bridge_schema():
    src = read("Include", "ClaudeEA", "Bridge.mqh")
    body = src[src.index("int CaiParseResponse"):]
    keys = set(re.findall(r'Get(?:String|Number)\("([a-z_]+)"', body))
    assert keys == set(SignalResponse.model_fields)
    assert f"json.Count() != {len(SignalResponse.model_fields)}" in body


def test_request_id_format_accepted_by_bridge():
    from bridge.models import REQUEST_ID_RE
    assert '"%s-M5-%I64d-%I64d"' in read("Include", "ClaudeEA", "Bridge.mqh")
    assert REQUEST_ID_RE.fullmatch("XAUUSD.m-M5-1793600000-770001")


def defaults():
    src = read("Claude_AI_MT5.mq5")
    return dict(re.findall(r"input\s+\w+\s+(Inp\w+)\s*=\s*([^;]+);", src))


def test_safe_defaults():
    d = defaults()
    assert d["InpAllowOrders"] == "false"
    assert d["InpReverseMode"] == "false" and d["InpCloseOnHold"] == "false"
    assert d["InpQuickProfit"] == "false" and d["InpUseAsia"] == "false"
    assert d["InpUseLondon"] == "true" and d["InpUseNewYork"] == "true"
    assert (d["InpSlAtr"], d["InpTpAtr"]) == ("1.0", "3.0")
    assert (d["InpBeTriggerAtr"], d["InpTrailStartAtr"], d["InpTrailDistAtr"], d["InpBeBufferTicks"]) == ("1.0", "1.5", "1.0", "0")
    assert (d["InpDailyProfit"], d["InpDailyLoss"], d["InpQuickProfitMoney"]) == ("200.0", "100.0", "9.0")
    assert d["InpEvalIntervalSec"] == "300" and d["InpBridgeUrl"].startswith('"http://127.0.0.1:')


def test_no_secrets_or_remote_hosts_in_ea():
    for name, src in all_sources().items():
        low = src.lower()
        assert "sk-ant" not in low and "anthropic_api_key" not in low and "x-api-key" not in low, name
        assert "api.anthropic.com" not in low, name
        for url in re.findall(r"https?://[^\s\"'<>]+", src):
            assert url.startswith(("http://127.0.0.1:", "http://localhost:")) or "example.com" in url or "10.0.0.5" in url, (name, url)


def test_ontick_has_no_http_and_no_sleep():
    src = read("Claude_AI_MT5.mq5")
    ontick = src[src.index("void OnTick()"):src.index("void OnTimer()")]
    assert "BridgeStep" not in ontick and "CaiHttp" not in ontick and "WebRequest" not in ontick
    for name, text in all_sources().items():
        code = re.sub(r"//[^\n]*", "", text)              # ignore comments
        assert not re.search(r"\bSleep\s*\(", code), name
    protect = src[src.index("void Protect()"):src.index("bool NextClosedBar")]
    assert "CaiHttp" not in protect and "BridgeStep" not in protect and "HandleSignal" not in protect


def test_ai_is_not_asked_when_no_action_is_possible():
    src = read("Claude_AI_MT5.mq5")
    assert defaults()["InpSkipAiWhenBlocked"] == "true"
    step = src[src.index("void BridgeStep()"):src.index("void OnTick()")]
    assert step.index("AskBlockedReason()") < step.index("CaiBuildRequest(") < step.index("CaiHttp(")
    skip = src[src.index("string AskBlockedReason()"):src.index("void TryEnter")]
    for reason in ("daily stop latched", "daily trade cap reached", "outside allowed sessions", "cooldown active"):
        assert f'return "{reason}"' in skip
    assert "InpAllowOrders" not in skip            # observation mode (orders OFF) still collects signals


def test_single_order_send_site_and_write_ahead_dedup():
    src = read("Claude_AI_MT5.mq5")
    assert src.count("CaiOpen(") == 1
    assert src.index('CaiGvSet("LASTORDERBAR"') < src.index("CaiOpen(")
    ex = read("Include", "ClaudeEA", "Execution.mqh")
    assert ex.count("g_caiTrade.Buy(") == 1 and ex.count("g_caiTrade.Sell(") == 1
    # every loop over positions filters on symbol AND magic before acting
    assert ex.count("POSITION_MAGIC") >= 3 and "OrderSend" not in src


def test_gate_reasons_mirror_reference_model():
    import inspect

    from refmodel import risk
    ea = read("Claude_AI_MT5.mq5")
    for reason in re.findall(r', "([^"]+)"\),', inspect.getsource(risk.entry_gate)):
        if reason in ("BUY", "SELL"):                   # the signal tuple, not a reason
            continue
        assert f'block = "{reason}"' in ea, reason
    order = [ea.index(f'block = "{r}"') for r in (
        "signal is HOLD/invalid", "live orders not enabled (InpAllowOrders=false)", "trading not permitted",
        "signal stale", "bar already traded (dedup)", "daily stop latched", "outside allowed sessions",
        "spread above limit", "daily trade cap reached", "cooldown active", "managed position already open",
        "volume below broker minimum", "SL/TP violate broker stop level", "insufficient free margin")]
    assert order == sorted(order)
