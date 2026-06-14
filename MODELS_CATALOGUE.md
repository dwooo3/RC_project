# Полный каталог моделей оценки инструментов (индустрия) + покрытие RiskCalc

**Дата:** 2026-06-13
**Назначение:** исчерпывающий список моделей ценообразования, применяемых в
промышленных продуктах (Bloomberg MARS/DLIB, Murex MX.3, Numerix CrossAsset,
Calypso, FINCAD, FIS, QuantLib), с пометкой статуса в RiskCalc:
✅ есть · 🟡 частично/прокси · ❌ нет.

Numerix CrossAsset как ориентир — 40+ моделей по всем классам активов,
multi-curve/multi-currency, гибридный фреймворк ([Numerix](https://www.numerix.com/crossasset)).

---

## 1. Аналитические формулы для ванильных опционов
| Модель | Назначение | RiskCalc |
|---|---|---|
| Black-Scholes-Merton | equity опционы, непрерывный дивиденд | ✅ |
| Black-76 | опционы на форварды/фьючерсы, caps/swaptions | ✅ |
| Garman-Kohlhagen | FX опционы | ✅ |
| Bachelier (нормальная) | отрицательные ставки/спреды | ✅ |
| Displaced diffusion (shifted lognormal) | смещённая лог-норм., отриц. ставки | ❌ |
| CEV (constant elasticity of variance) | скос волатильности | ❌ |
| Merton (discrete dividends) | дискретные дивиденды | ❌ |

## 2. Численные методы (движки)
| Метод | RiskCalc |
|---|---|
| Биномиальное дерево CRR | ✅ |
| Jarrow-Rudd / Tian биномиальные | ❌ |
| Leisen-Reimer (быстрая сходимость) | ✅ |
| Триномиальное дерево | ✅ |
| Конечные разности: явная/неявная схемы | 🟡 (через CN) |
| Crank-Nicolson PDE (+ Rannacher) | ✅ |
| ADI (2D PDE: Heston/quanto) | ❌ |
| Monte Carlo (GBM, antithetic, control variate, moment matching) | ✅ |
| Longstaff-Schwartz (американский MC) | ✅ (Prototype) |
| Quasi-MC (Sobol / Halton) | ❌ |
| Fourier: Carr-Madan FFT | ❌ |
| Fourier: COS-метод (Fang-Oosterlee) | ❌ |
| Fourier: Lewis / Gil-Pelaez | ✅ (в Heston/Bates CF) |
| Американские аппрокс.: Barone-Adesi-Whaley | ❌ |
| Американские аппрокс.: Bjerksund-Stensland | ❌ |

## 3. Стохастическая волатильность и поверхности
| Модель | RiskCalc |
|---|---|
| Heston (характеристич. функция) | ✅ (Prototype) |
| Heston MC (Euler) | ✅ (Prototype) |
| Heston MC (Andersen QE) | ✅ |
| Bates (Heston + скачки) | ✅ (Prototype) |
| SABR (Hagan) | ✅ (Prototype) |
| ZABR / no-arb SABR (Hagan 2014) | ❌ |
| Local volatility (Dupire) | ✅ (MC) |
| Stochastic-Local Vol (SLV) | ❌ |
| SVI / SSVI (параметрич. поверхность) | ✅ (SVI fit) |
| GARCH option pricing (Duan) | 🟡 (GARCH есть, не опционный) |
| Rough volatility (rough Bergomi / rough Heston) | ❌ |
| Lognormal/normal mixture | ❌ |
| Vanna-Volga (FX) | 🟡 (Malz smile вместо) |

## 4. Скачковые / Лévy процессы
| Модель | RiskCalc |
|---|---|
| Merton jump-diffusion | ✅ |
| Kou (double-exponential jumps) | ❌ |
| Variance Gamma (VG) | ❌ |
| CGMY / KoBoL | ❌ |
| Normal Inverse Gaussian (NIG) | ❌ |
| Bates (см. §3) | ✅ |

## 5. Короткие ставки (short-rate)
| Модель | RiskCalc |
|---|---|
| Vasicek | ✅ |
| CIR (Cox-Ingersoll-Ross) | ✅ |
| Ho-Lee | ✅ |
| Hull-White 1-фактор (+ trinomial tree) | ✅ |
| Hull-White 2-фактор / G2++ | ❌ |
| Black-Derman-Toy (BDT) | ✅ (в callable) |
| Black-Karasinski | ❌ |
| Kalotay-Williams-Fabozzi | ❌ |

## 6. Ставки: рыночные модели и терм-структура
| Модель | RiskCalc |
|---|---|
| HJM (Heath-Jarrow-Morton) | ❌ |
| LIBOR Market Model (LMM/BGM) | ❌ |
| SABR-LMM | ❌ |
| Swap Market Model | ❌ |
| Cheyette / quasi-Gaussian | ❌ |
| Markov-functional | ❌ |
| Multi-curve / OIS-дисконтирование | ✅ (dual-curve) |
| Cross-currency basis | 🟡 (XCCY есть, без бутстрапа базиса) |
| Swaption cube + SABR-калибровка | ✅ |
| CMS convexity / timing adjustment | ✅ |

## 7. Ставочные продукты (прайсеры)
| Прайсер | RiskCalc |
|---|---|
| Bond (fixed/zero/FRN/amortizing/step/perpetual/linker) | ✅ |
| IRS / OIS / basis swap | ✅ |
| FRA | ✅ |
| Cap / Floor / Collar (Black-76 strip) | ✅ |
| European swaption (Black/Bachelier) | ✅ |
| Bermudan swaption (HW tree, cube-calibrated) | ✅ |
| Callable/putable bond + OAS | ✅ (Prototype) |
| CMS swap / CMS spread option | ✅ |
| Bond future (CTD) / STIR future | ✅ |
| Repo / money market / T-bill / CP | ✅ |
| Inflation swap (ZC / YoY) | ✅ |
| Jarrow-Yildirim inflation | ❌ |

## 8. Кредит
| Модель | RiskCalc |
|---|---|
| Reduced-form / hazard (intensity) | ✅ |
| CDS bootstrap (par spreads) | ✅ |
| ISDA standard CDS model (IMM, upfront) | ❌ |
| Structural: Merton | 🟡 (BSM-эквивалент) |
| Structural: Black-Cox / KMV | ❌ |
| Jarrow-Turnbull / Duffie-Singleton | 🟡 (hazard-эквивалент) |
| Gaussian copula (CDO/basket/FTD) | ✅ (Prototype) |
| t-copula / Clayton / Marshall-Olkin | ❌ |
| Base correlation | ❌ |
| Risky bond (survival-weighted) | ✅ |
| Credit spread option | ✅ |

## 9. XVA
| Метрика/метод | RiskCalc |
|---|---|
| CVA / DVA | ✅ |
| Exposure simulation (EPE/ENE/PFE) | ✅ |
| FVA (funding) | ❌ |
| MVA (initial margin) / KVA (capital) / ColVA | ❌ |
| Wrong-way risk | ❌ |
| Netting sets / collateral (CSA) | ❌ |
| American Monte Carlo для экспозиций | ❌ |

## 10. FX
| Модель | RiskCalc |
|---|---|
| FX forward / swap (IRP) | ✅ |
| Garman-Kohlhagen опционы | ✅ |
| FX smile (RR/BF, Malz) | ✅ |
| Vanna-Volga | ❌ |
| NDF (cash-settled) | ✅ |
| Cross-currency swap | ✅ |
| FX-Heston / FX-SABR / FX-SLV | ❌ |
| Quanto adjustment | ✅ |

## 11. Commodity
| Модель | RiskCalc |
|---|---|
| Black-76 на фьючерсной кривой | 🟡 (через Black-76) |
| Gibson-Schwartz (2-фактор) | ❌ |
| Schwartz-Smith (short/long) | ❌ |
| Mean-reverting (Pilipovic) | ❌ |
| Сезонность | ❌ |
| Spread options (Kirk / Margrabe / Bjerksund-Stensland) | 🟡 (Kirk/Margrabe есть) |

## 12. Экзотика (аналитика и MC)
| Прайсер | RiskCalc |
|---|---|
| Барьерные (Reiner-Rubinstein single) | ✅ |
| Двойные барьеры (Ikeda-Kunitomo) | 🟡 (Prototype) |
| Lookback (Goldman-Sosin-Gatto / Conze-Viswanathan) | ✅ |
| Asian geometric (Kemna-Vorst) | ✅ |
| Asian arithmetic (Turnbull-Wakeman / Levy / Curran) | 🟡 (MC+CV вместо) |
| Digital / binary (cash/asset-or-nothing) | ✅ |
| One-touch / no-touch / double-no-touch | ✅ |
| Compound (Geske) | ✅ |
| Chooser | ✅ |
| Cliquet / ratchet | ✅ |
| Forward-start (Rubinstein) | ✅ |
| Power / gap / supershare | ✅ |
| Rainbow / best-of / worst-of (Stulz) | ✅ |
| Basket (MC / moment-matching) | ✅ |
| Spread (Kirk) | ✅ |
| Exchange (Margrabe) | ✅ |
| Quanto | ✅ |
| Mountain range (Himalaya / Altiplano) | ✅ |
| Variance / vol swap (Demeterfi log-contract) | ✅ |
| Gamma / corridor / conditional var swap | ✅ |
| Autocallable / Phoenix | ✅ (Prototype) |
| Reverse convertible / PPN / worst-of RC | ✅ |
| TARN / accumulator | ❌ |

## 13. Конвертируемые / гибриды
| Модель | RiskCalc |
|---|---|
| Tsiveriotis-Fernandes (equity/debt split) | ✅ |
| Ayache-Forsyth-Vetzal (AFV PDE) | ❌ |
| Convertible с stochastic credit | ❌ |

## 14. Ипотека / структурное финансирование
| Модель | RiskCalc |
|---|---|
| Prepayment (PSA / OAS) | ❌ |
| MBS / ABS | ❌ |
| CLN / FTD / nth-to-default | ✅ (Prototype) |

## 15. Построение поверхностей и кривых
| Метод | RiskCalc |
|---|---|
| Кривые: bootstrapping | ✅ |
| Nelson-Siegel / Svensson | ✅ |
| Сплайны (cubic / monotone / tension) | 🟡 (cubic) |
| Multi-curve construction | ✅ |
| Vol surface: SVI / SSVI | 🟡 (SVI) |
| Local vol из implied (Dupire) | ✅ |
| Arbitrage-free интерполяция | 🟡 |
| Vanna-Volga surface | ❌ |

## 16. Риск-модели
| Модель | RiskCalc |
|---|---|
| Parametric VaR (delta-normal, Student-t) | ✅ |
| Historical VaR (+ age-weighted) | ✅ |
| Filtered historical (FHS) | 🟡 |
| Monte Carlo VaR | ✅ |
| Full-reprice VaR | ✅ |
| EVT / POT-GPD tail | ✅ |
| Expected Shortfall (ES) | ✅ |
| Cornish-Fisher | ❌ |
| PCA VaR (кривые) | ✅ |
| Component / incremental / marginal VaR | 🟡 |
| GARCH / EWMA волатильность | ✅ |
| Copula VaR | ❌ |
| FRTB SA / IMA | ❌ |
| Backtesting (Kupiec / Christoffersen / Basel) | ✅ |
| SA-CCR (EAD) | ✅ |

---

## Сводка покрытия

| Класс | ✅ | 🟡 | ❌ |
|---|---:|---:|---:|
| Ванильные формулы | 4 | 0 | 3 |
| Численные методы | 7 | 2 | 6 |
| Стох. вол / поверхности | 7 | 3 | 4 |
| Скачки / Lévy | 2 | 0 | 4 |
| Короткие ставки | 5 | 0 | 3 |
| Рыночные модели ставок | 4 | 1 | 6 |
| Ставочные продукты | 11 | 0 | 1 |
| Кредит | 6 | 2 | 4 |
| XVA | 2 | 0 | 5 |
| FX | 6 | 0 | 2 |
| Commodity | 0 | 2 | 4 |
| Экзотика | 24 | 2 | 1 |
| Конвертируемые | 1 | 0 | 2 |
| Ипотека/структурное | 1 | 0 | 2 |
| Кривые/поверхности | 6 | 3 | 1 |
| Риск | 11 | 3 | 3 |
| **ИТОГО** | **~97** | **~23** | **~51** |

**Главные пробелы относительно промышленных библиотек:**
1. Рыночные модели ставок (LMM/HJM/Cheyette) — для path-dependent ставочной экзотики.
2. Lévy/скачки (Kou, VG, CGMY, NIG) — fat tails для коротких сроков и FX.
3. XVA-семейство (FVA/MVA/KVA, netting/collateral, AMC, wrong-way).
4. Fourier-движки (FFT/COS) — быстрая калибровка стох-вол.
5. Commodity 2-факторные (Gibson-Schwartz, Schwartz-Smith) + сезонность.
6. SLV / rough vol / ZABR — современный фронт волатильности.
7. FRTB / регуляторный капитал.

**Сильные стороны RiskCalc:** экзотика (24 ✅ — на уровне промышленных),
ставочные продукты, риск-семейство, кривые. Это даёт широкое покрытие
«ванильно-экзотического» спектра; пробелы — в продвинутых стох-моделях
ставок/вола и XVA-полноте.
