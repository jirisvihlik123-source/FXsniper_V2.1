from typing import List, Dict, Any

# 8 lehkých konfigurací okolo základních prahů
DEFAULT_SWARM = [
    {"rsi_lo":32, "rsi_hi":68, "min_atr_pips":2.2, "require_sr":0},
    {"rsi_lo":35, "rsi_hi":65, "min_atr_pips":2.8, "require_sr":1},
    {"rsi_lo":30, "rsi_hi":70, "min_atr_pips":3.2, "require_sr":0},
    {"rsi_lo":34, "rsi_hi":66, "min_atr_pips":2.6, "require_sr":1},
    {"rsi_lo":36, "rsi_hi":64, "min_atr_pips":2.4, "require_sr":0},
    {"rsi_lo":33, "rsi_hi":67, "min_atr_pips":2.9, "require_sr":1},
    {"rsi_lo":31, "rsi_hi":69, "min_atr_pips":2.0, "require_sr":0},
    {"rsi_lo":38, "rsi_hi":62, "min_atr_pips":3.5, "require_sr":1},
]

def swarm_votes_from_last_row(last_row: Dict[str, Any], configs: List[Dict]=None) -> Dict[str,Any]:
    """
    last_row: dict s klíči: close, rsi, atr (v PIPSech!), swing_low, swing_high
    Vrací: {'votes', 'n_configs', 'support_ratio', 'agreeing_configs'}
    Konfig hlasuje 1, když projdou jeho jednoduchá pravidla.
    """
    configs = configs or DEFAULT_SWARM
    votes = 0
    agreeing = []
    total = len(configs)

    close = float(last_row.get("close", 0.0))
    atr_pips = float(last_row.get("atr", 0.0))  # očekáváme už v pipsech
    rsi = float(last_row.get("rsi", 50.0))
    sup = last_row.get("swing_low", None)
    res = last_row.get("swing_high", None)

    for i, conf in enumerate(configs):
        if atr_pips < conf.get("min_atr_pips", 2.0):
            continue
        long_ok = rsi <= conf["rsi_lo"]
        short_ok = rsi >= conf["rsi_hi"]
        if not (long_ok or short_ok):
            continue
        if conf.get("require_sr",0)==1:
            near = False
            if sup is not None and abs(close - sup) <= 0.55 * atr_pips: near = True
            if res is not None and abs(res - close) <= 0.55 * atr_pips: near = True
            if not near:
                continue
        votes += 1
        agreeing.append(i)

    support_ratio = votes / total if total>0 else 0.0
    return {"votes": votes, "n_configs": total, "support_ratio": support_ratio, "agreeing_configs": agreeing}
