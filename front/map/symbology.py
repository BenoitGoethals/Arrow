"""15-character APP-6B / MIL-STD-2525B legacy SIDC builder (milsymbol v1.x).

Format: SXDPUUUUUUMMCC0  (15 chars, 0-indexed)
  [0]  S  = Coding scheme   (S=Warfighting, G=Tactical Graphics)
  [1]  X  = Standard identity  F=Friend  H=Hostile  U=Unknown  N=Neutral
  [2]  D  = Battle dimension   G=Ground  A=Air  S=SeaSurface  U=Subsurface
  [3]  P  = Status            P=Present  A=Anticipated
  [4-9]   = Function ID (6 chars, pad with -)
  [10-11] = Echelon/modifier  --=None  A-=Team  C-=Squad  D-=Section
                               E-=Platoon  F-=Company  G-=Battalion
  [12-13] = Country code      --=Unknown
  [14]    = Order of battle   -=None
"""

# ---- Identity codes --------------------------------------------------
F = "F"   # Friendly (blue)
H = "H"   # Hostile  (red)
U = "U"   # Unknown  (yellow)
N = "N"   # Neutral  (green)
A = "A"   # Assumed friend

# ---- Echelon modifier codes (positions 10-11) -----------------------
ECHELON = {
    "none":      "--",
    "team":      "A-",
    "crew":      "B-",
    "squad":     "C-",
    "section":   "D-",
    "platoon":   "E-",
    "company":   "F-",
    "battalion": "G-",
    "regiment":  "H-",
    "brigade":   "I-",
    "division":  "J-",
    "corps":     "K-",
}

# ---- Ground combat function IDs ------------------------------------
_FUNC = {
    "unit":      "U-----",
    "infantry":  "UCI---",
    "armor":     "UCA---",
    "arty":      "UCF---",
    "engineer":  "UCE---",
    "recon":     "UCR---",
    "aviation":  "UCCAF-",   # combat aviation
    "at":        "UCJ---",   # anti-tank
    "aaa":       "UCAA--",   # anti-aircraft
    "signal":    "US----",
    "medical":   "UH----",
    "medevac":   "UH-M--",
    "special":   "USSF--",   # SOF
    "hq":        "UH----",   # used for HQ flag too
    "cbrn":      "UCB---",
    "logistics": "USS---",
    "observer":  "UUOO--",   # forward observer
    "location":  "USS---",   # support star — used as POI pin
    "drone":     "A-----",   # air unit — used for hostile UAV/drone (pair with dim="A")
}


def build(identity: str = F, func: str = "unit", echelon: str = "none",
          dim: str = "G", status: str = "P") -> str:
    """Return a 15-character SIDC string."""
    ech = ECHELON.get(echelon, "--")
    fid = _FUNC.get(func, "U-----")
    return f"S{identity}{dim}{status}{fid}{ech}---"


# ---- Pre-built common SIDCs ----------------------------------------

def friendly_infantry(echelon: str = "platoon") -> str:
    return build(F, "infantry", echelon)

def hostile_infantry(echelon: str = "section") -> str:
    return build(H, "infantry", echelon)

def hostile_armor(echelon: str = "section") -> str:
    return build(H, "armor", echelon)

def hostile_arty(echelon: str = "section") -> str:
    return build(H, "arty", echelon)

def unknown_unit(echelon: str = "none") -> str:
    return build(U, "unit", echelon)

def neutral_unit() -> str:
    return build(N, "unit")

def friendly_hq(echelon: str = "company") -> str:
    s = build(F, "hq", echelon)
    # Set HQ bit: position 10 = 'H' modifier not trivially in 15-char
    # milsymbol v1 accepts 'SFGPUH----F----' for HQ
    return f"S{F}GP" + "UH----" + ECHELON.get(echelon, "F-") + "---"

def medevac() -> str:
    return build(F, "medevac", "none", "A")   # Air dimension for helo

def fire_mission_marker() -> str:
    return build(H, "arty", "none")  # hostile arty = target

def cbrn_marker() -> str:
    return build(H, "cbrn", "none")

def poi() -> str:
    return build(N, "location", "none")


# ---- CoT type → SIDC -----------------------------------------------
# CoT type format: "a-f-G-U-C-I"  atom, identity, dimension, type...
_COT_IDENTITY = {"f": F, "h": H, "u": U, "n": N, "j": U, "k": U}
_COT_DIM      = {"G": "G", "A": "A", "S": "S", "U": "U", "F": "G"}
_COT_FUNC     = {
    ("U","C","I"): "UCI---",
    ("U","C","A"): "UCA---",
    ("U","C","F"): "UCF---",
    ("U","C","R"): "UCR---",
    ("U","C",):    "UC----",
    ("U",):        "U-----",
}


def from_cot_type(cot_type: str) -> str:
    parts = (cot_type or "").split("-")
    ident = _COT_IDENTITY.get(parts[1] if len(parts) > 1 else "u", U)
    dim   = _COT_DIM.get(parts[2] if len(parts) > 2 else "G", "G")
    # Try to match function code from CoT type sub-parts
    subtypes = tuple(parts[3:]) if len(parts) > 3 else ()
    func_id = "U-----"
    for length in range(len(subtypes), 0, -1):
        key = subtypes[:length]
        if key in _COT_FUNC:
            func_id = _COT_FUNC[key]
            break
    return f"S{ident}{dim}P{func_id}-----"


# ---- Entity type → SIDC --------------------------------------------
def from_tactical_object(obj_type: str, affiliation: str = "UNKNOWN") -> str:
    aff_code = {"FRIENDLY": F, "FRIEND": F,
                "HOSTILE": H, "ENEMY": H,
                "NEUTRAL": N}.get(affiliation.upper(), U)
    mapping = {
        "ENEMY":    build(H, "infantry",   "section"),
        "HOSTILE":  build(H, "infantry",   "section"),
        "FRIENDLY": build(F, "infantry",   "section"),
        "VEHICLE":  build(H, "armor",      "section"),
        "ARTILLERY":build(H, "arty",       "section"),
        "POI":      build(N, "location",   "none"),
        "DRONE":    build(H, "drone",      "none", dim="A"),
        "MARKER":   build(aff_code, "unit","none"),
        "OBJECTIVE":build(F, "unit",       "company"),
        "ZONE":     build(N, "unit",       "none"),
        "ROUTE":    build(F, "unit",       "none"),
    }
    return mapping.get(obj_type.upper(), build(aff_code, "unit", "none"))


# ---- Operator role → SIDC ------------------------------------------
def from_operator_role(role: str, echelon: str = "section") -> str:
    if role in ("ADMIN", "BATTLE_CAPTAIN", "OPS"):
        return friendly_hq("company")
    if role in ("FO", "INTEL"):
        return build(F, "observer", "none")
    if role == "MED":
        return build(F, "medical", "none")
    if role == "CBRN":
        return build(F, "cbrn", "none")
    return friendly_infantry(echelon)


# ---- SIDC class (for legacy code compatibility) --------------------
class SIDC:
    friendly_operator = staticmethod(from_operator_role)
    from_operator_role = staticmethod(from_operator_role)
    from_tactical_object = staticmethod(from_tactical_object)
    from_cot_type = staticmethod(from_cot_type)
    friendly_infantry = staticmethod(friendly_infantry)
    hostile_infantry  = staticmethod(hostile_infantry)
    unknown_unit      = staticmethod(unknown_unit)
    medevac           = staticmethod(medevac)
