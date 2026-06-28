# FX Sniper Copilot — XAUUSD

Telegram copilot pro jednu konzistentní XAUUSD strategii. `analyzer.py` je jediný
zdroj signálů, risk managementu i paper-trade výsledků. `bot.py` je pouze
kompatibilní spouštěč stejného runtime.

## Spuštění

```powershell
python bot.py
```

Nespouštějte současně `bot.py` a `analyzer.py`; oba vedou ke stejnému Telegram
botovi a dvě instance způsobí konflikt `getUpdates`.

## Strategie

- M5 vstup, M15 trendové potvrzení.
- Pouze XAUUSD a pouze ve stanovené obchodní seanci.
- Směr EMA50/EMA200 a měřitelný sklon EMA50.
- Pullback do ATR pásma kolem EMA50, následovaný price-action potvrzením.
- Market vstup pouze při breaku předchozí svíčky a silném ADX; jinak limitní
  vstup uvnitř návratu k EMA50.
- Blokace late chase, news spike svíček, chopu, protisměrného HTF a blízké
  struktury bez prostoru.
- Strukturální SL s ATR minimem, pevné RRR z `.env`, náklady a velikost pozice
  podle skutečné vzdálenosti SL.
- Denní limit, cooldown po ztrátové sérii a maximálně jeden aktivní XAU obchod.

AI skóre pouze rozlišuje běžný alert od `ALERT+`; technický setup nepřepisuje.

## Kontrola syntaxe

```powershell
python -m py_compile analyzer.py ai/execution.py bot.py
```

Paper výsledky jsou ukládány v `logs/`. Před reálnou exekucí je nutné nejprve
nasbírat reprezentativní XAU paper obchody a ověřit náklady konkrétního brokera.
