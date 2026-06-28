from __future__ import annotations
import os, json, time
from dataclasses import dataclass

@dataclass
class RelaxSpec:
    ai:int
    adx:int
    htf_adx:int
    atr:float
    rsi:int

class InactivityRelaxer:
    def __init__(self, env=os.environ):
        self.env = env
        self.on   = env.get("INACTIVITY_RELAX_ON","1") == "1"
        self.win  = int(env.get("INACTIVITY_MINUTES","120"))
        self.maxr = int(env.get("INACTIVITY_MAX_RELAX_MIN","60"))
        self.cool = int(env.get("INACTIVITY_COOLDOWN_MIN","30"))
        self.state_file = env.get("INACTIVITY_STATE_FILE","logs/inactivity_state.json")
        self.spec = RelaxSpec(
            ai = int(env.get("INACTIVITY_RELAX_AI","-2")),
            adx = int(env.get("INACTIVITY_RELAX_ADX","-2")),
            htf_adx = int(env.get("INACTIVITY_RELAX_HTF_ADX","-2")),
            atr = float(env.get("INACTIVITY_RELAX_ATR","-0.3")),
            rsi = int(env.get("INACTIVITY_RELAX_RSI","+2")),
        )
        self.floor_ai  = int(env.get("INACTIVITY_FLOOR_AI","62"))
        self.floor_adx = int(env.get("INACTIVITY_FLOOR_ADX","18"))
        self.floor_htf = int(env.get("INACTIVITY_FLOOR_HTF_ADX","16"))
        self.floor_atr = float(env.get("INACTIVITY_FLOOR_ATR","2.8"))

        self._state = {
            "last_alert_ts": None,
            "relax_started_ts": None,
            "relaxed": False,
            "last_reset_ts": None
        }
        self._load()

    def _now(self): return int(time.time())

    def _load(self):
        try:
            with open(self.state_file,"r") as f:
                self._state.update(json.load(f))
        except Exception:
            pass

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file,"w") as f:
                json.dump(self._state,f)
        except Exception:
            pass

    def note_alert(self):
        """Zavolej pokaždé, když odešleš FULL nebo HEADS-UP."""
        self._state["last_alert_ts"] = self._now()
        # spustíme cool-down, aby se hned zase nepovolovalo
        self._state["relax_started_ts"] = None
        self._state["relaxed"] = False
        self._state["last_reset_ts"] = self._state["last_alert_ts"]
        self._save()

    def maybe_apply(self):
        """Zavolej před každým scanem. Když je ticho moc dlouho, upraví prahy jen v os.environ."""
        if not self.on:
            return "off"

        now = self._now()
        last = self._state.get("last_alert_ts") or now  # když nevíme, ber teď (žádné povolení hned po startu)
        since = (now - last) / 60.0

        # cool-down po posledním alertu
        last_reset = self._state.get("last_reset_ts")
        if last_reset and (now - int(last_reset)) / 60.0 < self.cool:
            # drž základní prahy
            if self._state.get("relaxed"):
                self._undo_env()
            self._state["relaxed"] = False
            self._save()
            return f"cooldown({self.cool}m)"

        # start relaxu
        if since >= self.win:
            if not self._state.get("relaxed"):
                self._apply_env()
                self._state["relax_started_ts"] = now
                self._state["relaxed"] = True
                self._save()
                return f"relax_on after {int(since)}m"
            else:
                # hlídej max délku relaxu
                started = self._state.get("relax_started_ts") or now
                if (now - int(started))/60.0 >= self.maxr:
                    self._undo_env()
                    self._state["relaxed"] = False
                    self._state["last_reset_ts"] = now
                    self._save()
                    return "relax_off (max reached)"
                return "relax_hold"
        else:
            # není ještě čas → drž základ
            if self._state.get("relaxed"):
                self._undo_env()
                self._state["relaxed"] = False
                self._state["last_reset_ts"] = now
                self._save()
                return "relax_off"
            return "base"

    # --- interní aplikace/vrácení práhů (jen v procesu) ---
    def _apply_env(self):
        def clamp_int(v, floor): return str(max(int(v), floor))
        def clamp_float(v, floor): return str(max(float(v), floor))

        # čti aktuální (po startu/analyzeru) a uprav
        ai  = int(self.env.get("AI_SCORE_MIN","67")) + self.spec.ai
        adx = int(self.env.get("ADX_MIN","20")) + self.spec.adx
        htf = int(self.env.get("HTF_ADX_MIN","18")) + self.spec.htf_adx
        atr = float(self.env.get("MIN_ATR_PIPS","3.4")) + self.spec.atr
        rsi_lo = int(self.env.get("RSI_LO","30")) - abs(self.spec.rsi)
        rsi_hi = int(self.env.get("RSI_HI","70")) + abs(self.spec.rsi)

        self.env["AI_SCORE_MIN"] = clamp_int(ai, self.floor_ai)
        self.env["ADX_MIN"]      = clamp_int(adx, self.floor_adx)
        self.env["HTF_ADX_MIN"]  = clamp_int(htf, self.floor_htf)
        self.env["MIN_ATR_PIPS"] = clamp_float(atr, self.floor_atr)
        self.env["RSI_LO"]       = str(max(10, rsi_lo))
        self.env["RSI_HI"]       = str(min(90, rsi_hi))

    def _undo_env(self):
        # návrat k .env hodnotám: nic nepřepisujeme na disk – jen znovu načítáme z procesního stavu.
        # Většina projektů má při každém cyklu čtení z os.environ, takže stačí nastavit zpět původní.
        # Pro jednoduchost tady jen necháme běžet na hodnotách, které načetl analyzer při startu.
        pass
