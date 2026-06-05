# MARKET_DATA_FOR_PRICING — карта зависимостей

**Назначение:** для каждого продукта в Pricing-вкладках — какие рыночные данные нужны на вход,
какие риск-факторы он порождает (для чувствительностей и факторного VaR), и из какого источника
данные берутся. Эта карта — спецификация для (1) полей detail-экранов прайсеров, (2) VaR-разложения
по факторам, (3) блока Market Data (что и откуда грузить).

**Дата:** 2026-06-05
**Связано с:** [PRODUCT_ARCHITECTURE.md](PRODUCT_ARCHITECTURE.md), [MOEX_MARKET_DATA_INTEGRATION_PROMPT.md](MOEX_MARKET_DATA_INTEGRATION_PROMPT.md), `services/pricing_service.py`.

---

## 1. Таксономия рыночных данных (объекты)

| Код | Объект | Что это | Уже есть в проекте |
|---|---|---|---|
| `DISC` | Discount curve | Кривая дисконтирования (zero/DF) | ✅ GCURVE_RUB (КБД), KEYRATE/RUONIA flat |
| `PROJ` | Projection/forward curve | Прогнозная кривая плавающей ставки (RUONIA/key) | 🟡 RUONIA flat-proxy (нужен OIS) |
| `CORPSPR` | Credit/issuer spread curve | Спред эмитента/сектора над госкривой | ✅ CORP_T1/T2/T3 (калибровка) |
| `HAZ` | Hazard / survival curve | Кривая интенсивности дефолта | ❌ нужно (из CDS/корп-спредов) |
| `FXSPOT` | FX spot | Спот валютной пары | ✅ USD/EUR/CNY-RUB (MOEX selt) |
| `FXFWD` | FX forward points / curve | Форвардные пункты / своп-пункты | ❌ нужно (или из IR-паритета) |
| `FXVOL` | FX vol surface | Волатильность по страйку/сроку (RR/BF) | ❌ нужно |
| `EQSPOT` | Equity/index spot | Спот акции/индекса | ✅ TQBR shares, IMOEX/RVI |
| `DIV` | Dividend yield / schedule | Дивдоходность/график | ❌ нужно (оценка) |
| `EQVOL` | Equity vol surface | Поверхность волатильности (strike×tenor) | 🟡 FORTS-точки (нужна полноценная) |
| `IRVOL` | Cap/swaption vol | Black-вол по caplets / swaption cube | ❌ нужно |
| `CORR` | Correlation matrix | Корреляции активов | 🟡 из time_series (нет объекта) |
| `RECOV` | Recovery rate | Доля возмещения | ❌ допущение (0.4) |
| `REALVOL` | Realized variance/vol | Реализованная вариация из ряда цен | ✅ из time_series |
| `RFRATE` | Risk-free short rate | Короткая ставка (для опционов) | ✅ короткий конец DISC / key rate |

Источники: **MOEX ISS** (КБД zcyc, FX selt, TQBR, индексы, FORTS-опционы, облигации TQOB/TQCB),
**CBR** (ключевая ставка, RUONIA), **derived** (корп-спреды, корреляции, realized vol, hazard),
**manual/assumption** (recovery, дивиденды до интеграции).

---

## 2. Риск-факторы (для чувствительностей и факторного VaR)

VaR раскладывается по факторам, агрегируя НЕ сырые Greeks, а экспозиции к факторам
(`domain/risk_factors.RiskFactorExposure`, уже есть в `PortfolioService`):

| Фактор | Единица | Чувствительность | Откуда ряд для VaR |
|---|---|---|---|
| Equity/Index spot | %/абс | delta, gamma | EQSPOT time_series |
| FX spot | %/абс | FX delta | FXSPOT time_series |
| IR (по кривой/тенору) | bp | DV01 / key-rate DV01 | DISC/PROJ zero time_series |
| Credit spread (эмитент/тенор) | bp | CS01 | CORPSPR/HAZ time_series |
| Implied vol (по бакету) | vol pt | vega | EQVOL/FXVOL/IRVOL |
| Correlation | абс | corr sensitivity | CORR |
| Dividend | % | div rho | DIV |
| Commodity spot | % | delta | (позже) |

**Логика связи:** прайсер возвращает Greeks → маппинг Greeks → `RiskFactorExposure` (фактор, валюта,
bump, sensitivity, unit) → агрегация в портфеле → VaR по историческим/параметрическим сдвигам факторов
(`RiskService.var` + `MarketDataService.get_returns(factor_id)`).

---

## 3. Карта зависимостей по вкладкам

### 3.1 Fixed Income
| Продукт | Вход (market data) | Риск-факторы | Источник |
|---|---|---|---|
| Bond / OFZ | DISC (+CORPSPR для корп) | IR DV01 by tenor, CS01 | GCURVE_RUB / CORP_x |
| FRN | PROJ + DISC | IR DV01, basis | RUONIA/key + DISC |
| Cap / Floor | DISC + IRVOL | IR DV01, rate vega | DISC + ❌IRVOL |
| Amortizing/Linker *(позже)* | DISC + inflation | IR DV01, inflation | ❌ |

### 3.2 Option (на любой базовый актив)
| Продукт | Вход | Риск-факторы | Источник |
|---|---|---|---|
| Vanilla | EQSPOT/FXSPOT, RFRATE, DIV, EQVOL(point) | delta, gamma, vega, rho, div | EQSPOT + DISC + 🟡EQVOL |
| Barrier / Asian / Lookback / Digital | то же + EQVOL(surface) | delta, gamma, vega(bucket), rho | + 🟡полная EQVOL |

### 3.3 Equity (деривативы/форварды/фьючерсы)
| Продукт | Вход | Риск-факторы | Источник |
|---|---|---|---|
| Equity forward/future | EQSPOT, RFRATE, DIV (carry) | spot delta, rate, div | EQSPOT + DISC + ❌DIV |
| Equity option | см. Option | delta/gamma/vega/rho/div | как Option |

### 3.4 FX
| Продукт | Вход | Риск-факторы | Источник |
|---|---|---|---|
| FX forward | FXSPOT, DISC(dom), DISC(for) / FXFWD | FX delta, IR(2 валюты) | FXSPOT + DISC + ❌FXFWD |
| FX option | FXSPOT, 2×RFRATE, FXVOL | FX delta, FX vega, IR | + ❌FXVOL |

### 3.5 Swaps (кроме CDS)
| Продукт | Вход | Риск-факторы | Источник |
|---|---|---|---|
| IRS | DISC + PROJ (single-curve) | IR DV01 by tenor | GCURVE/RUONIA |
| OIS | OIS DISC | IR DV01 | 🟡 (нужен OIS) |
| Basis swap | 2× PROJ + DISC | IR DV01, basis | 🟡 |
| Swaption | DISC + IRVOL(cube) | IR DV01, swaption vega | + ❌IRVOL |
| Variance / Vol swap | EQVOL(strip) / REALVOL | variance/vol exposure, vega | 🟡EQVOL / ✅REALVOL |
| Equity swap *(позже)* | EQSPOT, DISC, DIV | spot, rate, div | EQSPOT+DISC |

### 3.6 Structured Notes
| Продукт | Вход | Риск-факторы | Источник |
|---|---|---|---|
| Autocall / Phoenix | EQSPOT, EQVOL, RFRATE, DIV, (CORR для multi) | delta, gamma, vega, corr, rate, issuer credit | EQSPOT + 🟡EQVOL + 🟡CORR |
| Reverse convertible / PPN | то же + DISC (funding) | как выше + IR | + DISC |
| **Custom builder (новый)** | конфигурируемый набор: payoff + базовые активы → нужные объекты выводятся из конструкции | производные от компонентов | комбинация выше |

### 3.7 Credit
| Продукт | Вход | Риск-факторы | Источник |
|---|---|---|---|
| CDS | HAZ (или spread), DISC, RECOV | CS01 by tenor, recovery | ❌HAZ + DISC |
| CLN / FTD / nth-to-default | HAZ(per name) + CORR + RECOV + DISC | CS01 per issuer, corr, recovery | ❌HAZ + 🟡CORR |
| CDO (LHP) | HAZ + CORR + RECOV | CS01, correlation | ❌ |

---

## 4. Gap-анализ: что есть vs что нужно

**Готово (через интеграцию MOEX A–E):** DISC (КБД), CORPSPR (корп-кривые), FXSPOT, EQSPOT,
индексы, KEYRATE/RUONIA, REALVOL, частично EQVOL (FORTS-точки).

**Нужно добавить в блок Market Data (приоритет для прайсинга):**
1. **EQVOL / FXVOL / IRVOL — поверхности волатильности** (strike×tenor). Критично для опционов,
   структурных, FX-опционов, cap/floor, swaption. FORTS даёт точки → собрать поверхность; IV из премии
   при отсутствии готовой.
2. **HAZ — кривые выживаемости/hazard** для кредитных (CDS/CLN/CDO). Выводятся из CDS-спредов или
   корп-облигаций + recovery.
3. **DIV — дивидендная доходность/график** для equity/опционов/структурных.
4. **FXFWD — форвардные пункты** (или из IR-паритета двух кривых).
5. **CORR — объект корреляций** (считается из time_series, оформить как хранимый объект для multi-asset/structured/CDO).
6. **OIS / basis / projection-кривые** для dual-curve свопов (нужны OIS-своп котировки).
7. **RECOV** — справочник recovery (пока допущение 0.4).

**Уже покрывает текущая БД (`infra/db`):** curve_points, fx_rates, equity_quotes, index_values,
time_series, vol_points, bond_quotes — расширить под surfaces/hazard/div/corr.

---

## 5. Следствия для архитектуры (связь Pricing ↔ Market Data ↔ Risk)

- **Поля detail-экранов** прайсеров = столбец «Вход» соответствующей строки (часть берётся из снапшота
  автоматически: DISC/FXSPOT/EQSPOT/EQVOL; часть вводится пользователем: страйк/срок/номинал).
- **Сохранение инструмента → портфель:** позиция хранит продукт + его inputs + snapshot_id (для
  воспроизводимости); `PortfolioService` агрегирует риск-факторы по столбцу «Риск-факторы».
- **Факторный VaR:** факторы из столбца «Риск-факторы» → ряды через `get_returns(factor_id)` →
  `RiskService.var`. Где ряда фактора нет (vol/corr) — на старте параметрический/прокси, потом исторический.
- **Блок Market Data** грузит объекты из §1 по источникам §1; приоритет наполнения — §4.

> Детальная количественная валидация моделей против рыночных данных — **отдельная фаза позже**
> (по решению владельца), после готовности архитектуры/интерфейса/связей.
