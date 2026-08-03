# BL-192 — Signal Chain Settings — Tasks

**Дата:** 03.08.2026
**Статус:** done

---

## Задачи

```
T-01 [opus] — Backend: API поддержка signal_*_fallback + дефолт openrouter
  Traces to: US-01, AC-02, AC-03, AC-04
  Files: pm-bot/app/vault_api.py, shared/llm_client.py
  Task:
    1. vault_api.py — UserPrefs model: добавить signal_triage_fallback,
       signal_analysis_fallback, signal_escalation_fallback (list[Any])
    2. vault_api.py — _DEFAULT_USER_PREFS: добавить 3 ключа
    3. vault_api.py — GET /api/v1/user-prefs: добавить defaults + нормализацию
       для 3 новых ключей в цикл на строке ~2880
    4. vault_api.py — PUT /api/v1/user-prefs: добавить 3 ключа в валидацию
       на строке ~2964 и в return dict
    5. shared/llm_client.py — _DEFAULT_FALLBACK: сменить дефолт
       signal_* групп с ["claude"] на ["openrouter", "claude"]
  Depends on: none
  Verify: pytest pm-bot/tests/ knowledge-engine/tests/ -x -q
  Status: [✓] done (03.08.2026)

T-02 [opus] — Frontend: 3 новые группы в Settings FALLBACK CHAINS
  Traces to: US-01, AC-01
  Files: pm-bot/web/settings.html
  Task:
    1. operationGroups ref (~line 625): добавить 3 записи:
       signal_triage (operations: signal_score, quality_check, dedup_check, completeness_check)
       signal_analysis (operations: signal_analyze, report_to_ideas, trend_detect)
       signal_escalation (operations: signal_analyze_escalation)
    2. buildPrefsPayload (~line 728): добавить extraction + payload fields
       для signal_triage_fallback, signal_analysis_fallback, signal_escalation_fallback
    3. onMounted prefs loading (~line 1158): добавить 3 conditional loads
       для signal_*_fallback
  Depends on: T-01 (API must support the keys)
  Verify: Open Settings in browser, verify 7 groups visible
  Status: [✓] done (03.08.2026)
```
