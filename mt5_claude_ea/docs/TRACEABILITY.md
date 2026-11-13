# Traceability matrix — requirement → module → test → status

สถานะ: **VERIFIED-PY** = มี pytest ผ่านจริงในเครื่องพัฒนา · **IMPLEMENTED-MQL (UNTESTED)** = เขียนแล้วแต่ยังไม่ compile/รัน ·
**OPEN** = ยังไม่ทำหรือยังไม่มีหลักฐาน

pytest ตรวจได้เฉพาะ Python (bridge, reference model, replay) การที่ reference model ผ่านเทสต์ **ไม่ได้พิสูจน์** ว่าโค้ด MQL5 ถูกต้อง
แม้เขียนให้ตรงกันทีละฟังก์ชัน

| # | Requirement | โมดูล | เทสต์ | สถานะ |
|---|---|---|---|---|
| F1 | M5×20 แท่งปิด, ATR(14), spread, digits/tick/contract; ตรวจลำดับเวลา, stale, OHLC ผิดรูป, allowlist | `Bridge.mqh::CaiBuildRequest`, `bridge/models.py`, `service.precheck` | `test_bridge_units::test_request_rejects`, `test_bridge_api::test_stale_and_future_bars_hold`, `::test_symbol_not_allowlisted` | bridge VERIFIED-PY · EA IMPLEMENTED-MQL (UNTESTED) |
| F2 | BUY/SELL/HOLD, CONF 0..100, REASON ≤300, JSON strict, fallback HOLD | `bridge/parsing.py`, `models.AISignal`, `Json.mqh`, `Bridge.mqh::CaiParseResponse` | `test_parse_rejects` (21 กรณี), `test_bad_model_output_holds_without_retry`, SelfTest `TestJson/TestBridgeResponse` | bridge VERIFIED-PY · EA UNTESTED |
| F3 | Voting ปิดเป็นค่าเริ่มต้น; 3 รุ่นต่างกัน, ต้องตอบครบ, 2/3, เฉลี่ย confidence, log disagreement | `bridge/voting.py`, `config.py`, `service.py` | `test_vote_*` (unit 5 + API 5), `test_vote_models_must_be_three_distinct` | VERIFIED-PY (mock) · ยังไม่เคยเรียก 3 รุ่นจริง: OPEN |
| F4 | Session UTC+DST, Asia ปิด; spread, margin, volume, stops/freeze, 1 position, cooldown, daily cap, slippage, stale, permission | `Sessions.mqh`, `Risk.mqh`, `Execution.mqh`, `Claude_AI_MT5.mq5::TryEnter`; `refmodel/` | `test_ref_sessions` (เทียบ IANA รายชั่วโมง 2015–2040), `test_gate_each_guard_blocks` (20 guard), `test_replay::test_trade_invariants` | logic VERIFIED-PY · EA UNTESTED |
| F5 | SL 1 ATR / TP 3 ATR, BE ที่ +1 ATR, trail จาก +1.5 ATR ระยะ 1 ATR, monotonic, BE buffer เป็น tick ค่าเริ่มต้น 0 | `Risk.mqh::CaiTrailSL/CaiInitialStops`, `Protect()` | `test_buy/sell_be_and_trailing_levels`, `test_sl_is_monotonic_on_random_paths`, `test_stop_level_and_freeze_level`, SelfTest `TestRisk` | logic VERIFIED-PY · EA UNTESTED |
| F6 | Quick Profit (optional) ≥9; daily +200/−100 realized+floating+commission; reset วันโบรกเกอร์, latch, ปิดเฉพาะของ EA | `Execution.mqh::CaiDayHistory/CaiManagedFloating/CaiCloseManaged`, `UpdateDaily`, `refmodel.DailyGuard` | `test_daily_latch_*`, `test_corrupt_daily_state_fails_closed`, `test_daily_trade_cap_and_daily_stop`, `test_quick_profit_optional` | logic VERIFIED-PY · EA UNTESTED |
| F7 | Reverse (OFF): ปิด → ยืนยัน → ตรวจใหม่ → กลับด้าน, ไม่ hedge | `HandleSignal`, `refmodel.reverse_plan` | `test_reverse_*` (3), `test_opposite_signal_ignored_when_reverse_off`, `test_reverse_plan` | logic VERIFIED-PY · EA UNTESTED |
| F8 | HOLD ไม่ปิด position; protection ทุก tick; HOLD-close ต้องเปิดเอง | `HandleSignal`, `Protect()` ใน `OnTick`+`OnTimer` | `test_hold_does_not_close_by_default_but_can_be_enabled`, `test_ontick_has_no_http_and_no_sleep` (static) | logic VERIFIED-PY · EA UNTESTED |
| F9 | 400/401/429/529/5xx/timeout → HOLD; backoff+jitter ≤5 retries ใน worker; ไม่บล็อก OnTick; circuit breaker; ไม่ retry หลังส่ง order | `bridge/retry.py`, `service.py`, `server.py` (202+poll), `BridgeStep` | `test_provider_errors_hold` (9), `test_http_errors_hold` (7, SDK จริง+HTTP mock), `test_timeout_holds`, `test_retry_*`, `test_circuit_*`, `test_submit_never_blocks_on_the_provider`, `test_single_order_send_site_and_write_ahead_dedup` (static) | bridge VERIFIED-PY · EA UNTESTED |
| F10 | ประเมินทุก 300 วินาทีเมื่อมีแท่งปิดใหม่; ไม่มี future data/duplicate/look-ahead; live order เป็น opt-in | `NextClosedBar`, `MarkEvaluated`, `InpAllowOrders=false`, `store.py`, `replay/generate.py` | `test_duplicate_request_id_calls_ai_once`, `test_dedup_survives_bridge_restart`, `test_signals_do_not_depend_on_future_bars`, `test_future_bars_cannot_change_past_trades`, `test_safe_defaults` | VERIFIED-PY · EA UNTESTED |
| F11 | Audit CSV/JSONL: UTC, symbol, bar, request id, models, votes, confidence, gate, risk snapshot, ticket/retcode, latency, ค่าใช้จ่าย, redaction | `bridge/audit.py`, `Audit.mqh` | `test_happy_path_single_model`, `test_redaction`, `test_no_secrets_in_audit_log_and_prompt_is_numeric` | bridge VERIFIED-PY · EA UNTESTED |
| F12a | Unit + integration (mock Anthropic API) | `tests/` | 205 ข้อ ผ่าน | VERIFIED-PY |
| F12b | MT5 Strategy Tester ด้วย AI historical replay | `Replay.mqh`, `replay/generate.py` | — | **OPEN** (ไม่มี MT5) |
| F12c | Out-of-sample, walk-forward, Monte Carlo, bootstrap CI, calibration | `replay/backtest.py`, `metrics.py` | `test_report_walkforward_montecarlo_run`, `test_metrics_known_values` | เครื่องมือ VERIFIED-PY · ผลบนข้อมูลจริง **OPEN** |
| F12d | Demo forward test | — | — | **OPEN** |
| S1 | ไม่มี key ใน source/log; .env ไม่ commit | `.gitignore`, `audit.redact`, `Settings(repr=False)` | `test_no_secrets_or_remote_hosts_in_ea`, `test_redaction` | VERIFIED-PY |
| S2 | Token + constant-time compare; local bind; จำกัด origin | `server.guard`, `config.load_settings` | `test_auth_required`, `test_non_loopback_client_and_foreign_host_and_origin_rejected`, `test_bad_config_refused` | VERIFIED-PY |
| S3 | Prompt injection: ข้อมูลแท่งเป็น untrusted; output ของโมเดล override guard ไม่ได้ | `service.build_user_content`, `models` (extra=forbid), `parsing` | `test_request_rejects` (ช่องแปลกปลอม), `test_bad_model_output_holds_without_retry` (ช่อง lot/sl) | VERIFIED-PY |
| S4 | ตรวจรหัสรุ่นก่อนใช้ | `service._models_ok`, `providers.verify_model` | `test_unknown_model_id_holds_and_never_trades`, `test_model_id_unknown_to_models_api_never_reaches_messages` | VERIFIED-PY (mock) · กับ API จริง OPEN |
| A1 | Compile ใน MetaEditor 0 errors, warnings ถูกบันทึก | `EA/` | มีเพียง lexical lint (`tools_mql_lint.py`) | **OPEN** |
| A2 | Daily stop อยู่รอดหลัง EA restart | GlobalVariables + history | `test_daily_latch_survives_restart_and_resets_next_broker_day` (ref model) | logic VERIFIED-PY · EA **OPEN** |
| A3 | Request dedup ปลอดภัยต่อ restart | SQLite, `LASTEVALBAR`/`LASTORDERBAR` | `test_dedup_survives_bridge_restart`, `test_pending_request_becomes_hold_after_restart` | bridge VERIFIED-PY · EA **OPEN** |
| A4 | SL/TP และ volume ถูกต้องตามโบรกเกอร์จริง | `Risk.mqh`, `Execution.mqh` | — | **OPEN** (ยังไม่ทราบค่าของโบรกเกอร์) |
