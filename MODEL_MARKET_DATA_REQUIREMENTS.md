# Требования моделей к рыночным данным + аудит нехватки

**Дата:** 2026-06-16
**Назначение:** перенос моделей на реальные рыночные данные и список того, каких
данных не хватает. Заземлено на фактическое содержимое `data/market_data.sqlite`.

---

## 1. Что есть в реальном хранилище (`data/market_data.sqlite`)

| Таблица | Строк | Что даёт моделям |
|---|---:|---|
| `yield_curves` / `curve_points` | 283 / 2928 | КБД, ОФЗ (TQOB), corp T1/T2/T3, RUONIA, CBR key, реальная ОФЗ-ИН |
| `bond_quotes` + `bond_coupons`/`amortizations`/`offers` | 6155 + 5923/301/24 | цены/купоны/амортизация/оферты облигаций |
| `instruments` | 3046 | справочник бумаг |
| `equity_quotes` | 786 | споты акций (для equity-опционов, корзин) |
| `dividends` | 731 | дивиденды (carry для GK/equity) |
| `fx_rates` | 7 | USD/EUR/CNY RUB (споты) |
| `commodity_quotes` | 32 | фьючерсы BR/GOLD/NG/SILV/PLT/SUGAR/CU |
| `vol_points` | 2667 | self-implied волы (из settle-цен фьючерсов/опционов) |
| `time_series` | 16229 | история (индексы, топ-акции, КБД-тенора, CBR-ряды) — для VaR |
| `index_values` | **0** | **пусто (мёртвая таблица)** |

**Источник self-implied вол:** EOD не отдаёт поле VOLATILITY, поэтому волы
имплаятся Black-76 из settle-цен. Это даёт **ATM-уровень**, но **почти нет
strike-измерения** (улыбки) и нет RR/BF.

**Подключение:** `app.runtime.market_service()` авто-коннектится к этой БД;
`active_snapshot()` отдаёт живой снапшот. Сервисные прайсеры со `curve_id`
(`_resolve_curve`) уже тянут реальные кривые. Пробел — не в проводке, а в
**отсутствующих типах данных** (улыбки, CDS, CPI, tranche-quotes).

---

## 2. Статус подключения по классам моделей

Легенда: ✅ работает на реальных данных · 🟡 частично (есть прокси/ATM, нет
полного) · ❌ нет нужных данных в хранилище.

### Ставки (bonds, IRS, FRA, cap/floor, swaptions, short-rate, LMM, Cheyette, BK, G2++, SMM)
| Нужные данные | Источник | Статус |
|---|---|---|
| Дисконт/проекция кривые (КБД, ОФЗ, RUONIA, corp) | `yield_curves` | ✅ |
| Облигационные купоны/амортизация/оферты | `bond_coupons/...` | ✅ |
| **Swaption cube ATM (expiry×tenor)** | self-implied (тонко) | 🟡 нет ликвидного RU-рынка свопционов |
| **Swaption SMILE (strike)** — для Cheyette-skew, SABR-cube, G2++ | — | ❌ нет strike-измерения |
| **Cap/floor vol strip по strike** — для LMM time-dep vol | self-implied ATM | 🟡 только ATM |

### Волатильность (BSM, Heston, SABR, Bates, local-vol, rough Bergomi, Carr-Madan, CEV, mixture, displaced)
| Нужные данные | Источник | Статус |
|---|---|---|
| Equity/FX спот | `equity_quotes`, `fx_rates` | ✅ |
| Дивиденды/carry | `dividends` | ✅ |
| ATM вол | self-implied `vol_points` | 🟡 |
| **Полная implied-vol поверхность (strike×expiry)** — Heston/SABR/SLV/rough калибровка | — | ❌ нет ликвидных RU-опционов по страйкам |

### FX (GK, NDF, XCCY, Vanna-Volga)
| Нужные данные | Источник | Статус |
|---|---|---|
| FX спот | `fx_rates` | ✅ |
| FX-форвардные кривые | `yield_curves` (FXFWD) | ✅ |
| **25Δ RR / BF котировки** — для Vanna-Volga | — | ❌ нет (только self-implied ATM) |

### Commodity (Schwartz-Smith, Gibson-Schwartz, seasonality, Pilipovic)
| Нужные данные | Источник | Статус |
|---|---|---|
| Фьючерсная кривая (стрип) | `commodity_quotes` | ✅ (32 контракта) |
| **Commodity option vol** — калибровка SS/GS на ATM-волы | self-implied (часть) | 🟡 |
| Сезонные historical-паттерны (газ/электро) | `time_series` (частично) | 🟡 |

### Кредит (CDS, ISDA, structural Merton/KMV/Black-Cox, copula, base-corr)
| Нужные данные | Источник | Статус |
|---|---|---|
| Hazard-кривые из corp z-спредов | `credit_curves` (бутстрап из `bond_quotes`) | ✅ |
| **Котируемые CDS-спреды (RU-имена)** — ISDA standard | — | ❌ нет рынка single-name CDS |
| **Equity vol + долг (для structural)** — KMV inputs | equity ✅ / долг из `instruments` 🟡 | 🟡 нужна структура капитала эмитента |
| **CDO tranche quotes / base correlation** | — | ❌ нет рынка траншей в RU |

### XVA (CVA/DVA/FVA/MVA/KVA, netting, CSA, WWR, AMC)
| Нужные данные | Источник | Статус |
|---|---|---|
| Дисконт-кривая, hazard контрагента | `yield_curves`, `credit_curves` | ✅ |
| **Funding spread кривая** — FVA/MVA | — | ❌ нет внутренней FTP-кривой |
| **CSA-термины (threshold/MTA/MPoR), IM/SIMM-параметры** | — | ❌ договорные данные, не рыночные |
| **WWR-корреляции экспозиция↔дефолт** | — | ❌ нет оценки |

### Инфляция (ZCIIS, YoY, Jarrow-Yildirim)
| Нужные данные | Источник | Статус |
|---|---|---|
| Реальная кривая ОФЗ-ИН, breakeven | `yield_curves` (REALCURVE_OFZIN) | ✅ |
| **CPI-фиксинги (Росстат)** — индексация линкеров, YoY | — | ❌ нет API Росстата (только CSV) |

### Ипотека / структурное (MBS/PSA, ABS)
| Нужные данные | Источник | Статус |
|---|---|---|
| Кривая дисконта | `yield_curves` | ✅ |
| **Пулы закладных (баланс/WAC/WAM), факторы предоплаты** | — | ❌ нет RU-данных по пулам ИЦБ |

### Риск (VaR hist/param/MC/EVT/ES, FRTB-SA/IMA, copula VaR, SA-CCR)
| Нужные данные | Источник | Статус |
|---|---|---|
| История факторов | `time_series` (16k) | ✅ |
| **Регуляторные RW / корреляции FRTB** | — | ❌ статические таблицы Базеля (вшить, не рынок) |

---

## 3. Список нехватки данных (приоритизированный backlog ингеста)

**P1 — разблокирует калибровку существующих моделей:**
1. **Implied-vol поверхности по страйкам** (equity/index/FX опционы MOEX) —
   разблокирует Heston/SABR/Bates/local-vol/SLV/rough, Cheyette-skew,
   swaption-cube smile, Carr-Madan-калибровку. *Сейчас:* только self-implied ATM.
2. **FX 25Δ RR/BF** — разблокирует Vanna-Volga на реальных данных.
3. **Cap/floor + swaption vol по страйкам** — LMM time-dep vol, G2++/Cheyette
   на реальном кубе.

**P2 — новые классы:**
4. **Котируемые single-name CDS-спреды** (если появится ликвидность) — ISDA CDS,
   structural-калибровка.
5. **Commodity option vols** — калибровка SS/GS на волы (не только кривую).
6. **CPI-фиксинги (Росстат CSV-автоинжест)** — JY/линкеры/YoY.

**P3 — договорные/регуляторные (не рыночный фид, а справочники):**
7. **CSA-термины + SIMM-параметры** — MVA/реалистичный collateral.
8. **Funding/FTP-кривая** — FVA/MVA.
9. **FRTB RW/correlation таблицы** (вшить из Базеля) — FRTB-SA/IMA на регуляторных весах.
10. **Структура капитала эмитентов** (долг/equity-вол) — KMV/Merton по RU-именам.

**P4 — мелочи:**
11. `index_values` пустая — наполнить или удалить.
12. CDO tranche quotes / base correlation — рынка в RU нет; оставить синтетику.

---

## 4. Итог по проводке

- **Уже на реальных данных** (через `market_service()` + `_resolve_curve`):
  все ставочные/облигационные/FX/кредит-кривые-прайсеры, commodity-кривые,
  VaR на истории, equity-споты/дивиденды.
- **Работают, но на синтетических входах из-за отсутствия данных:** калибровки
  на улыбку (vol surface по страйкам, RR/BF, CDS, tranche), CPI, CSA/funding.
  Это **дефицит данных, а не проводки** — модели принимают реальные входы, как
  только соответствующий фид появится в хранилище (P1-P3 выше).
- **Демо-фолбэк** остаётся для оффлайн/тестов (`demo_snapshot`).
