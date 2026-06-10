# RiskCalc — известные недочёты и план развития

**Дата:** 2026-06-10
**Состояние:** завершены фазы 0–4 программы 2026-06 (коммиты `e6a334d` → Phase 4).
**Тесты:** 503 passed; постоянный валидационный гейт `tests/test_validation_identities.py`
+ длинный harness `validation_audit_2026_06.py` (63 проверки).

Этот документ — единственный актуальный список незакрытых недочётов и план.
Предыдущие аудиторские .md (AUDIT, MODEL_REVIEW, GAP_ANALYSIS и т.д.) — исторические.

---

## 1. Что уже есть (итог фаз 0–4)

- **Прайсинг**: ~75 governed-инструментов — ваниль (4 закрытые формулы, 3 дерева,
  MC, PDE CN), экзотика (барьеры/азиаты/lookback/digital — валидированы против MC),
  FI (вся линейка облигаций, IRS/FRA/cap-floor/свопционы dual-curve, callable+OAS,
  бермудцы на дереве HW, CMS с convexity), кредит (CDS на hazard-кривой, risky bond,
  конвертируемые TF), FX (форварды/NDF/опционы с улыбкой Malz/XCCY), инфляция
  (линкеры на реальной кривой, ZCIIS/YoY), структурки (феникс, RC, PPN).
- **Движки**: деревья, MC (антитетика/CV/QE), LSM, PDE Кранка-Николсон,
  Merton/Bates, local vol (Дюпир), short-rate (Vasicek/CIR/HW аналитика + дерево).
- **Рыночные данные**: MOEX ISS + CBR инжест, снапшоты с lineage, hazard-бутстрап,
  реальная кривая, vol-поверхности (SVI/RR-BF), demo-набор для оффлайна.
- **Риск**: VaR (hist/param/MC/EVT/full-reprice), ES, стресс, Kupiec/Christoffersen,
  exposure-симуляция EPE/PFE + CVA/DVA на hazard-кривых.
- **Платформа**: реестр моделей с governance-гейтингом, аудит с хэшем входов
  (персистентный), портфельная книга в SQLite, PySide6-воркстейшн с 7 workspace.

## 2. Известные недочёты (не блокеры, по убыванию важности)

### Модельные
| # | Недочёт | Где |
|---|---|---|
| M1 | Свопционная вола — скаляр: нет куба (tenor×expiry×strike), нет SABR-калибровки cap/floor и свопционов | swaption, capfloor, bermudan |
| M2 | Бермудец/каллабл: kappa/sigma HW — ручные входы, нет калибровки к свопционному кубу | bermudan_swaption, callable_bond |
| M3 | YoY-инфляционный своп без convexity adjustment (нужна inflation vol) | inflation_swaps |
| M4 | CMS: нет timing adjustment при лаге платежа, вола скалярная | cms_swap |
| M5 | XCCY: basis-спред — вход, нет бутстрапа базисной кривой из рынка; нет MtM-resets | xccy |
| M6 | CDS: нет ISDA standard model (IMM-даты, фикс-купон + upfront) | cds_curve |
| M7 | Конвертируемые: нет soft-call триггеров, stock borrow, дискретных дивидендов | convertible |
| M8 | Exposure/CVA: нет неттинг-сетов, CSA/коллатерала, wrong-way risk; только IRS+FX forward | risk/exposure |
| M9 | Full-reprice VaR: 4 жирных фактора (EQ/IR/VOL/FX), нет пер-именной гранулярности и KRD-шоков кривой | risk_service |
| M10 | PDE: равномерная сетка (нет сгущения у страйка/барьера), нет 2D (Heston PDE) | models/pde |
| M11 | American greeks: theta/vega только бамп-репрайс; нет adjoint/AAD | trees, pde |
| M12 | FRN: par-reset абстракция, нет forward-проекции купонов и фиксинг-лагов | frn (Prototype) |
| M13 | Double barrier: серия Ikeda-Kunitomo не валидирована (Prototype) | barrier |
| M14 | CDO LHP: формула PV транша сомнительна, не валидирована | credit (Prototype) |
| M15 | Day count: ACT/ACT ISDA упрощён; нет праздничных календарей (MOEX/TARGET) | fixed_income |

### Данные
| # | Недочёт | Где |
|---|---|---|
| D1 | Деривация IRVOL (cap/swaption vol) из MOEX — нет источника | market data |
| D2 | FX vol: RR/BF-котировки ручные; нет инжеста с рынка | fx_usdrub_demo |
| D3 | Дивидендные ожидания — нет источника (q ручной) | equity pricing |
| D4 | Recovery rates — допущение 0.4/0.3, нет источника | hazard curves |
| D5 | Hazard demo строится из z-спредов через CDS-бутстрап — методологическая натяжка (нет рынка CDS RU) | demo snapshot |
| D6 | Vol-поверхность MOEX FORTS: точки сырые, нет арбитраж-фри сглаживания (SVI есть, не подключён к инжесту) | infra/moex_iss |

### Платформенные
| # | Недочёт | Где |
|---|---|---|
| P1 | Отчётность: нет PDF/Excel экспорта портфельных/риск-отчётов | reporting_service |
| P2 | Снапшоты рыночных данных персистятся только для MOEX-инжеста; manual/demo — in-memory lineage | MarketDataStore |
| P3 | Нет REST API / headless-режима для батч-прайсинга | — |
| P4 | UI: новые продукты (Phase 2-3) в каталоге, но нет deep-link на бенчмаркинг/Analytics Lab для новых движков | analytics workspace |
| P5 | Бэктестинг VaR живёт в risk/, нет сервисного маршрута и UI | backtest_var |
| P6 | Производительность: full-reprice VaR — Python-цикл по дням×позициям; нет параллелизма | risk_service |
| P7 | Нет CI (GitHub Actions): тесты гоняются локально | .github |

## 3. План развития (приоритезирован)

### Этап A — Калибровка и качество ставочного стека (3–4 нед)
Самый большой разрыв с профессиональными системами — вокруг волатильности ставок:
1. Свопционный куб + cap/floor strip: структуры данных, SABR-калибровка по экспирациям/тенорам (D1, M1).
2. Калибровка HW (kappa, sigma) к кубу — есть заготовка `calibrate_hull_white`; довести и покрыть тестами (M2).
3. Бермудцы/каллаблы поверх калиброванного HW; сверка с Jamshidian на каждом узле куба.
4. CMS timing adjustment + вола из куба (M4).

### Этап B — Кредит и XVA до продакшена (2–3 нед)
1. ISDA standard model для CDS (M6); bond-CDS basis.
2. Неттинг-сеты и CSA/коллатерал в exposure-движке; общий портфельный exposure (микс IRS+FX+опционы через American MC) (M8).
3. FVA по той же инфраструктуре; wrong-way risk хотя бы через корреляцию hazard↔rates.

### Этап C — Риск-платформа (2–3 нед)
1. Факторная гранулярность full-reprice VaR: KRD-шоки кривой по тенорам, пер-именные эквити-факторы из time_series MOEX (M9).
2. VaR-бэктестинг как сервис + workspace-таб (P5).
3. Параллелизация репрайсинга (multiprocessing/joblib) (P6).
4. FRTB-SA как опциональный модуль — спрос у банков-клиентов.

### Этап D — Данные и автоматизация (2 нед)
1. Арбитраж-фри SVI на FORTS-инжесте, автоматическая поверхность в снапшоте (D6).
2. Дивиденды/borrow из MOEX (D3), recovery-матрица по секторам (D4).
3. CI: GitHub Actions с полным pytest + validation_audit на каждый PR (P7) — дёшево и сразу.

### Этап E — Дистрибуция (2–3 нед)
1. Отчёты PDF/Excel (порфтель, риск, governance) (P1).
2. REST API (FastAPI) поверх сервисного слоя — он уже чистый, маршруты лягут тонко (P3).
3. Персистентность всех снапшотов + восстановление сессии (P2).

### Кандидаты в бэклог (по запросу пользователей)
Commodity-кривые (Black76 + сезонность), TARF/аккумуляторы, dividend swaps/TRS,
MBS/ипотечные (ДОМ.РФ) с prepayment, Heston-PDE 2D, rough vol, AAD-греки,
SIMM/initial margin, мульти-курва RUB (RUONIA/KeyRate basis из рынка).

## 4. Правила работы (выводы фаз 0–4)

1. **Identity-first**: каждый новый прайсер входит с тестом-тождеством (паритет,
   предельный случай, MC-кросс-чек) в `tests/` — без него статус не выше Prototype.
2. **Реестр честен**: ограничение, не записанное в notes реестра, считается багом.
3. **Demo-данные обязаны быть согласованы**: нефизичные котировки ломают бутстрапы
   (см. clamp в hazard) — любые новые demo-наборы прогонять через конструкторы кривых.
4. **Python ≥ 3.10**, запуск на этой машине: `/usr/local/bin/python3.14`.
