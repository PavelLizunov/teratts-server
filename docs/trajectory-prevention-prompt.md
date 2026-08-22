# Copy-ready prompt for a Trajectory-enabled remediation chat

```text
# Задача: AUDIT → REVIEW GATE → APPLY — durable prevention после Trajectory проекта TeraTTSv2/DSH

У тебя есть доступ к полной Trajectory исходной сессии, репозиториям и применимым runtime-инструкциям. Проанализируй не только конечный код, но и последовательность решений, tool calls, потери контекста, изменения scope, заявления о проверках и deployment-действия. Цель — предотвратить повторение класса ошибок в будущих проектах через минимальные durable-изменения в AGENTS.md, skills, SDD-шаблонах, deployment/checklist документации и автоматических проверках, не переобучая глобальные правила под один инцидент.

Работай строго в трёх фазах:

1. AUDIT — только read-only исследование и отчёт.
2. REVIEW GATE — предложи изменения и дождись явного одобрения человека.
3. APPLY — после одобрения внеси, проверь, закоммить и push-ь изменения.

До Review Gate запрещены tracked/runtime изменения, package install/remove, service restart, deployment, commit и push. Временные диагностические файлы допустимы только вне Git и должны быть удалены после использования.

## Контекст инцидента

Проект: standalone Rust TeraTTSv2 HTTP server + DSH assistant voice action.

Ключевые наблюдавшиеся проблемы, которые нужно независимо подтвердить или опровергнуть evidence:

- одна длинная сессия несла исследование, архитектуру, реализацию, deployment и validation; решения могли потеряться после context compaction;
- multi-agent использовался фрагментарно и поздно, без ведущего phase protocol и независимых acceptance reviewers;
- Micro-Spec был утверждён, но не revisioned после изменения runtime topology, выбора Windows, Tailscale Serve, исключения RUAccent и UI-иконок;
- постоянный server runtime был размещён на Windows worker без decision gate, хотя runtime host не был задан человеком;
- для серверной задачи не применялось общее linux-first правило;
- upstream TeraTTSv2 default RUAccent full pipeline был исключён, но различие было обозначено поздно;
- DSH UI использовал emoji вместо design-system primitives;
- DSH host рестартовался из активной сессии, которую сам обслуживал, поэтому собственный transport обрывался; повторная попытка создала впечатление deadlock;
- subagent предлагался как решение рестарта, хотя он работает через тот же serving host;
- exact deployed SHA Windows binary не совпадал доказанно с финальным repo SHA;
- были проверены backend, bundle, HTTPS/CORS и WAV, но не реальный browser DOM/click/loading/play/stop acceptance;
- финальный отчёт смешал verified facts и assumptions и преждевременно использовал язык полного завершения;
- поздний аудит нашёл resource, concurrency, downloader, auth/CORS, language и health-contract риски, которые должны были быть найдены до deployment.

Не принимай этот список на веру. Для каждого пункта найди конкретный episode/evidence в Trajectory и классифицируй его как confirmed, partially confirmed, disproved или unknown.

## Обязательный multi-agent audit

Используй ведущего архитектора и несколько независимых узких reviewers, если доступно:

1. Process/SDD reviewer — spec gates, architecture drift, evidence claims, context compaction.
2. Runtime/deployment reviewer — linux-first, worker roles, exact SHA, supervision, restart/rollback.
3. Correctness/security reviewer — resource bounds, queue/cancellation, downloader atomicity, auth/CORS, model integrity.
4. Upstream parity reviewer — RUAccent/defaults/assets/tokenizers/reference tests.
5. DSH UX reviewer — slot API, primitives, accessibility, browser acceptance, host/client trust boundary.
6. Adversarial verifier — пытается опровергнуть главные findings и проверить, не overfit-ли предлагаемые правила.

Ведущий агент обязан интегрировать результаты, а не автоматически принимать claims subagents. Если модель/инструмент не позволяет выбрать конкретный provider/model, честно укажи это; не утверждай, что аудит сделан Gemini/SOL/другой моделью без evidence.

## Compaction-resistant phase artifacts

До длинного исследования создай временный phase index вне Git либо read-only plan в чате со следующими durable полями:

- objective;
- approved scope;
- unresolved decisions;
- invariants;
- evidence ledger;
- phase status;
- next gate;
- changed runtime state;
- exact commits/deployments.

После каждой фазы обновляй один компактный handoff. Не полагайся на память длинного контекста. Предложи общий механизм, который применим к любым long-running engineering objectives, а не только TTS.

# Фаза 1 — AUDIT

## A. Инструкции и authority map

Прочитай все применимые инструкции в порядке authority:

- system/developer instructions;
- workspace `AGENTS.md` и вложенные AGENTS;
- skills (`search-first`, `sdd`, `homelab`, coding/minimality skills);
- deployment/runbook docs;
- repo specs/checklists;
- service policies.

Составь карту:

| Rule source | Required behavior | Observed behavior | Gap | Root cause |

Отличай отсутствие правила от нарушения существующего правила и от неудачного tool/API design.

## B. Полная timeline/decision audit

Восстанови ключевую timeline:

- initial requirement;
- search-first verdict;
- Micro-Spec и approval;
- implementation phases;
- worker choices;
- deployment topology changes;
- service restarts;
- validation claims;
- final report;
- later audit findings.

Для каждого существенного решения укажи:

- было ли оно явно запрошено;
- было ли в approved spec;
- требовало ли уточнения;
- требовало ли spec amendment;
- какие alternatives рассматривались;
- был ли decision reversible;
- какое evidence существовало на тот момент.

## C. Root-cause analysis

Не останавливайся на «агент ошибся». Для каждого класса проблемы рассмотри:

- instruction gap;
- instruction conflict;
- context compaction/loss;
- отсутствующий decision gate;
- чрезмерно широкий objective;
- недостаточная delegation/orchestration;
- неверная модель evidence;
- tool/API limitation;
- runtime topology misunderstanding;
- misleading status language;
- отсутствующий automated check.

Используй причинную цепочку или 5 Whys, но не создавай искусственную точность.

## D. Обязательные policy themes

### 1. Linux-first services

Предложи общее правило:

- HTTP services, daemons, sites, gateways, background workers и постоянные runtimes по умолчанию размещаются на Linux;
- Windows/macOS — development, compatibility, desktop-native integration или явно одобренное исключение;
- control-plane hosts не превращаются в runtime hosts;
- если target runtime не указан, перед deployment обязателен decision gate;
- исключение должно фиксировать rationale, lifecycle, supervision, rollback и owner.

Проверь, где такое правило должно жить: global AGENTS, homelab skill, SDD template или deployment skill. Не дублируй одно правило без необходимости во всех местах.

### 2. Spec revision on architecture drift

Предложи механизм:

- approved spec является contract;
- изменение runtime host, network boundary, auth, persistence, external dependency, feature parity, deployment mechanism или user-visible UX требует short amendment;
- implementation останавливается на review gate;
- checklist обновляется реальными `[x]` только после evidence;
- unresolved decisions не маскируются defaults, если имеют инфраструктурный или security impact.

### 3. Multi-agent orchestration

Определи, когда long objective должен использовать ведущего архитектора и параллельных reviewers:

- несколько независимых подсистем;
- runtime + app + UI + infrastructure;
- больше одной platform target;
- security/deployment changes;
- длинная сессия с риском compaction.

Не вводи обязательную дорогую orchestration для простых задач. Предложи threshold и lightweight fallback.

### 4. Serving-host restart guardrail

Сформулируй durable правило:

- никогда не restart/kill/update serving host/process из активной сессии, которую он обслуживает;
- subagent не считается внешним каналом, если зависит от того же host;
- изменения готовятся заранее;
- restart выполняется через отдельный management channel или человеком после завершения активной сессии;
- validation выполняется в новой сессии read-only;
- если HMR реально активен, сначала докажи watcher/rebuild chain;
- не повторять signal после outcome unknown без read-only state verification.

Оцени, где лучше реализовать guard: AGENTS rule, homelab skill, DSH-specific runbook, tool warning или автоматический lint/check.

### 5. Exact-SHA deployment

Требования:

- сначала commit/push verified source;
- worker fetch/checkout exact SHA;
- build with lockfile;
- release path содержит SHA;
- binary hash и model revision записываются;
- mutable source copies/tar sync не являются production deployment;
- activation atomic;
- previous release retained;
- rollback реально проверяется.

### 6. Upstream parity and deliberate omissions

Если проект заявляет перенос существующего engine/model:

- сравнить upstream defaults, assets, preprocessing и runtime controls до coding;
- составить parity matrix;
- любое исключение (`RUAccent disabled`, teacher omitted, language reduced) должно быть в spec и health/capabilities;
- нельзя называть pipeline faithful/full без reference tests;
- лицензия assets и redistribution gate фиксируются отдельно.

### 7. UI design-system policy

Для native plugin integration:

- сначала искать primitives/icons/components платформы;
- использовать существующие hover/focus/disabled/a11y semantics;
- custom SVG только если glyph отсутствует, минимальный и `currentColor`;
- emoji допустимы только если человек явно просит literal emoji, а не обозначает ими состояния;
- browser acceptance обязателен для заявления о UI completion.

### 8. Evidence labels and truthful final reports

Введи строгие labels:

- `Verified` — реально выполненный check с result;
- `Inspected` — код/config прочитан, runtime не проверен;
- `Inferred` — логический вывод;
- `Not verified` — acceptance отсутствует;
- `Blocked` — конкретное внешнее условие.

Backend test, bundle presence и browser UX — разные evidence domains. Запрети слово `production-ready`/`готово`, если обязательные acceptance checks отсутствуют.

### 9. Resource/security review gate

До deployment model/AI service должны быть проверены:

- max input;
- predicted output/duration bound;
- checked allocations;
- concurrency/admission queue;
- cancellation semantics;
- timeout;
- auth;
- CORS/origin policy;
- rate limits;
- model integrity;
- downloader races;
- live health semantics;
- clean install and corruption cases.

Предложи reusable checklist, не специфичный к ONNX/TTS.

## E. Anti-overfitting

Для каждого proposed global rule ответь:

- предотвращает ли он класс инцидентов;
- относится ли к большинству engineering задач или только к этому repo;
- можно ли сделать его короче;
- не конфликтует ли он с существующими правилами;
- не создаёт ли approval fatigue;
- может ли automated check заменить prose;
- где самый узкий правильный scope правила.

Не добавляй глобальные правила про конкретные hostnames, CTIDs, TeraTTS constants или emoji. Такие детали принадлежат project spec/runbook.

## F. AUDIT outputs

Выдай:

1. Executive summary.
2. Timeline ключевых решений.
3. Ранжированный список findings с severity.
4. Root-cause matrix.
5. Existing-rule vs new-rule matrix.
6. Предлагаемые durable changes с точными целевыми файлами.
7. Что лучше решить автоматическим test/lint/tooling.
8. Что не следует менять из-за overfitting.
9. Риски изменений инструкций.
10. Rollback для instruction/skill changes.
11. Draft one-screen remediation spec.
12. Явную строку:

`AUDIT завершён. Изменения не применялись. Ожидаю Review Gate.`

После этого остановись и дождись человека.

# Фаза 2 — REVIEW GATE

Представь короткий spec изменений, включающий:

- intent/invariants;
- exact target files;
- proposed rule text или concise diff summary;
- автоматические checks/tests;
- verification matrix;
- rollback;
- оценку влияния на обычные задачи и approval fatigue.

Раздели изменения на:

- global AGENTS policy;
- task skill policy;
- SDD template;
- homelab/deployment runbook;
- repo-local checklist/tests;
- tool/runtime enhancement proposal, если это нельзя безопасно решить prose.

Не применяй всё автоматически. Человек должен иметь возможность одобрить отдельные группы.

Заверши:

`Одобрить предложенные durable prevention changes и перейти к APPLY?`

# Фаза 3 — APPLY

Только после явного approval:

1. Прочитай каждый target file перед edit.
2. Внеси минимальные изменения в самом узком правильном scope.
3. Не дублируй правила дословно в нескольких файлах; используй ссылки между canonical policy и specialized checklist.
4. Сохрани существующий style и hierarchy инструкций.
5. Добавь tests/lints, если они надёжнее prose, например:
   - spec checklist validation;
   - запрет unchecked completed claims в evidence report;
   - deployment record exact SHA fields;
   - generic client bundle scan на private hostname/credential;
   - browser acceptance template;
   - restart runbook guard.
6. Проверь инструкции adversarial scenarios:
   - простой one-file bugfix не должен требовать multi-agent ceremony;
   - сложный app+infra+UI objective должен требовать phase artifacts/reviews;
   - unspecified server runtime должен вызвать Linux-first decision gate;
   - active serving-host restart должен быть остановлен;
   - architecture drift должен вызвать amendment;
   - literal user requirement может обоснованно переопределить default.
7. Запусти применимые tests/format/lints.
8. Покажи diff summary до commit, если review gate это требует.
9. Commit/push по repository policy с Conventional Commits.
10. Не изменяй runtime deployment в этом remediation чате, если он отдельно не одобрен.

## Финальный отчёт

Разделы:

- `Verified`;
- `Not verified`;
- `Instruction changes`;
- `Automated checks`;
- `Why this is not overfit`;
- `Changed files`;
- `Commits/push`;
- `Rollback`;
- `Remaining risks`.

Все file references должны быть точными. Не раскрывай credentials. Не заявляй, что будущие ошибки невозможны; укажи, какой класс ошибок теперь предотвращается и какие ограничения остаются.
```
