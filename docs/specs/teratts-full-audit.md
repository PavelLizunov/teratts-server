# Spec: Swarm-аудит TeraTTS/DSH перед продолжением

## 1. Intent & Invariants
- What: независимый read-only Gemini-swarm ищет дефекты и evidence gaps во всей цепочке DSH client → Host Remote → Tailnet HTTPS → Rust API → speech-front/RUAccent → ORT → WAV.
- Lead определяет области, перепроверяет Critical/High и владеет финальными выводами; workers ничего не меняют.
- Запрещены рестарты, деплой, изменение конфигов/моделей/credentials; каждый finding требует location + evidence + verification.
- Browser UX, numerical parity, HTTP health и perceptual audio quality не подменяют друг друга.

## 2. Interface / Data Contract
```rust
enum Severity { Critical, High, Medium, Low }
enum Confidence { Proven, Likely, Hypothesis }
struct Finding {
    area: String,
    severity: Severity,
    confidence: Confidence,
    location: String,
    problem: String,
    evidence: String,
    impact: String,
    minimal_fix: String,
    verification: String,
}
struct AuditReport {
    findings: Vec<Finding>,
    false_positives_rejected: Vec<String>,
    blockers: Vec<String>,
    recommended_order: Vec<String>,
}
```

## 3. Verification Checklist (Definition of Done)
- [x] Шесть workers, только `ninitux/gemini-3.7-flash-high`, непересекающиеся read-only области.
- [x] Зафиксированы HEAD, working tree, active release, DSH plugin/config и runtime flags.
- [x] Critical/High перепроверены lead по коду или read-only runtime evidence.
- [x] Отдельно проверены cancellation, text loss, SSRF, INT8 evidence, perf claims, immutable deployment и browser lifecycle.
- [x] Итоговый отчёт сохранён в `docs/audits/`; исправления требуют отдельного SDD gate.
