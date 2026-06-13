# Аудит состояния перед детальными правками моделей

**Дата:** 2026-06-13
**Цель:** убедиться, что текущая база корректна, прежде чем начинать
детальную доработку каждой категории моделей.

---

## 1. Здоровье системы — ✅ корректно

| Проверка | Результат |
|---|---|
| Полный pytest | **586 passed, 0 failed** (80 c) |
| Независимый валидационный аудит (тождества) | **63 PASS, 0 FAIL, 0 WARN** |
| Git | чисто, всё запушено (origin/main = main) |
| Модулей | 16 instruments + 12 models; 57 тест-файлов |
| Приложение | все 7 workspace конструируются (в тестах) |

База корректна: можно начинать детальные правки, не опасаясь регрессий —
есть постоянный гейт (`tests/test_validation_identities.py` + `validation_audit_2026_06.py`).

## 2. Карта моделей (66 в реестре)

| Домен | Моделей | Prototype | Approximation | Validated |
|---|---:|---:|---:|---:|
| Pricing | 43 | 6 | 37 | 0 |
| Analytics | 14 | 6 | 8 | 0 |
| Risk | 7 | 1 | 6 | 0 |
| Portfolio | 1 | 1 | 0 | 0 |
| Market | 1 | 0 | 1 | 0 |
| **Итого** | **66** | **14** | **52** | **0** |

## 3. Находки аудита (на что обратить внимание перед правками)

### F1. Ни одной модели в статусе Validated (governance-разрыв)
Даже BSM/Black76/Garman-Kohlhagen/Bachelier и деревья — формально
«Approximation», хотя проходят и тождества, и опубликованные бенчмарки
(Hull, Haug). **Рекомендация:** ввести промоушн `Approximation → Validated`
для моделей с (а) пройденными identity-тестами и (б) совпадением с эталоном.
Это даст честную трёхуровневую шкалу (Validated → Approximation → Prototype),
а не «потолок Approximation».

### F2. Рассинхрон поля `tests[]` в реестре с фактическим покрытием
20 Pricing-моделей имеют `tests=[]` в реестре, хотя реально покрыты
(swaption/fra/capfloor/ndf/xccy/cms/bermudan и др. — в Stage A/2/validation
тестах). Поле реестра не отражает фактическое покрытие. **Рекомендация:**
при детальных правках синхронизировать `tests[]` с именами реальных тестов
(как сделано для barrier/lookback/variance_swap).

### F3. Устаревшие заметки у части Prototype
- `cva_dva`: notes «No exposure simulation» — но в P4 добавлен `cva_exposure`
  с HW-симуляцией EPE/PFE и CVA/DVA; cva_dva — устаревший простой вариант.
- `heston_cf`: уже dividend-adjusted и с устойчивой формой — кандидат в
  Approximation после бенчмарка против эталонных цен.
- `callable_bond`: «flat rate vol» — теперь есть swaption_cube для калибровки.

### F4. Технические ограничения окружения
- `validation_audit_2026_06.py` — MC-прогоны урезаны по памяти (~60k×1500);
  при детальной валидации запускать точечно с большим n_sims по конкретной модели.
- Python только 3.14 (`/usr/local/bin/python3.14`); launchd-автозапуск
  заблокирован TCC на iCloud (нужен Full Disk Access — отдельный вопрос).

## 4. Готовность к детальным правкам по категориям

**Первоочередные — 14 Prototype** (по убыванию отдачи):

| Категория | Модель | Что доработать |
|---|---|---|
| Стох. вол | heston_cf | бенчмарк против эталонных цен → Validated/Approximation |
| Стох. вол | mc_heston | Euler→QE по умолчанию (QE уже есть), сходимость deep-OTM |
| Стох. вол | sabr | ATM-предел, гарантия положительной волы, no-arb |
| Стох. вол | bates | калибровка к рынку (пока только пределы) |
| FI | callable_bond | vol term structure из swaption_cube вместо flat |
| FI | frn | par-reset, forward-купоны, projection-curve (помечен «replace before production») |
| FI | short_rate | калибровка к терм-структуре (заготовка есть) |
| Экзотика | asian | сравнение с точной геом. формулой, контроль вариации |
| Экзотика | multi_asset | nearest-PD коррекция корреляц. матрицы |
| Структурные | structured_autocall | observation schedule, barrier convention, coupon memory |
| Структурные | cln_ftd | калибровка к рыночным tranche-спредам |
| Кредит | cva_dva | пометить устаревшим / перенаправить на cva_exposure |
| MC | mc_lsm | out-of-sample exercise policy |
| Портфель | portfolio_aggregation | риск-факторное маппирование (смешанные единицы greeks) |

**Вторая очередь — промоушн Approximation → Validated** (F1): ваниль,
деревья, digital, down-barrier, FX forward, паритеты rates — после
формального бенчмарка и синхронизации `tests[]`.

## 5. Рекомендуемый порядок

1. **Governance-каркас** (быстро): ввести правило промоушна в Validated +
   синхронизировать `tests[]` (F1, F2) — это сделает «детальные правки»
   измеримыми (видно, что повысило статус).
2. **Stoch-vol блок** (heston_cf/mc_heston/sabr/bates) — самые ценные Prototype,
   общий бенчмарк-харнесс против эталонных цен.
3. **FI-блок** (callable_bond/frn/short_rate) — на готовом swaption_cube.
4. **Экзотика/структурные** (asian/multi_asset/autocall/cln_ftd).
5. **Чистка** (cva_dva, portfolio_aggregation).

Каждый шаг — identity/benchmark-тест первым, затем правка, затем промоушн
статуса и синхронизация реестра. База к этому готова.
