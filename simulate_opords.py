"""Seed three full doctrinal OPORDs (offensive, defensive, stability) with map snapshots.

Run:
    uv run python simulate_opords.py
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.opord.tiles import render_snapshot_png
from backend.storage.database import SessionLocal, init_db
from backend.storage.models import Operator, Opord, Photo

PHOTO_DIR = Path("data/photos")


def _attach_snapshot(
    db,
    opord: Opord,
    label: str,
    bbox: list[float],
    zoom: int,
    annotations: str,
    author_id: int,
) -> None:
    """Render OSM tiles for ``bbox`` and append the snapshot to the OPORD."""
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    try:
        png = render_snapshot_png(bbox, zoom)
    except Exception as exc:
        print(f"  ! snapshot render failed for {label}: {exc} (skipping)")
        return
    fn = f"opord_{opord.id}_{uuid.uuid4().hex}.png"
    (PHOTO_DIR / fn).write_bytes(png)
    photo = Photo(
        filename=fn,
        original_name=f"{label}.png",
        mime_type="image/png",
        uploaded_by=author_id,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    snaps = json.loads(opord.map_snapshots or "[]")
    s, w, n, e = bbox
    snaps.append(
        {
            "id": (max((x.get("id", 0) for x in snaps), default=0)) + 1,
            "label": label,
            "bbox": bbox,
            "center": [(s + n) / 2, (w + e) / 2],
            "zoom": zoom,
            "photo_id": photo.id,
            "annotations": annotations,
        }
    )
    opord.map_snapshots = json.dumps(snaps)
    db.commit()


# ── Three full OPORDs ─────────────────────────────────────────────────────────

OPORD_OFFENSIVE = dict(
    title="Attack to Seize OBJ BRAVO",
    opord_number="OPORD 26-001",
    dtg="101800ZMAY26",
    classification="UNCLASSIFIED//FOUO",
    references=(
        "a. Map: Series M745, Sheet 32A-NW, edition 4, scale 1:50,000\n"
        "b. BDE OPORD 26-04 (Operation IRON HAMMER)\n"
        "c. Co/Tm SOPs"
    ),
    task_organization=(
        "1 PL (ME) — 3x rifle squads, 1x WPN squad (2x M240B)\n"
        "2 PL (SE-1) — 3x rifle squads, attached MORT SEC (2x 60mm)\n"
        "3 PL (SE-2 / RES) — 3x rifle squads\n"
        "ATTACHMENTS: ENG TM (1x squad), FO TM, MED TM (2x medic)\n"
        "DETACHMENTS: nil"
    ),
    situation={
        "terrain": (
            "OAKOC. Observation: open desert with limited cover; key high ground vic Hill 412 (NE). "
            "Avenues of approach: Route GREEN (paved) and Route RED (unimproved). Key terrain: Hill 412, "
            "OBJ BRAVO crossroads. Obstacles: dry wadi 200m N of OBJ. Cover/concealment: scattered scrub, "
            "two abandoned compounds vic OBJ."
        ),
        "weather": (
            "BMNT 0518 / Sunrise 0552 / Sunset 1928 / EENT 1954. Illum 12% (waxing crescent), set 2210. "
            "Temp 14°C–32°C. Wind NE 8–12 kt. Visibility >10 km. Light data favours dawn assault."
        ),
        "enemy_cds": (
            "Mech inf platoon (-) IVO OBJ BRAVO, est strength 22 PAX with 2x technicals (DShK), "
            "1x ATGM team. C2 in northern compound."
        ),
        "enemy_mlcoa": (
            "Defend in sector from prepared positions in two compounds; covering fires from Hill 412; "
            "CT effort to reinforce from N along Route GREEN with 2x additional technicals within 30 min."
        ),
        "enemy_mdcoa": (
            "Pre-emptive spoiling attack along Route GREEN at H-2 with mech section, supported by mortar "
            "fires onto AAs."
        ),
        "higher": (
            "B CO destroys enemy IVO OBJ BRAVO NLT 110600ZMAY26 to enable BN passage of lines along Route "
            "GREEN. CDR INTENT (BN): rapid penetration, isolate OBJ from N reinforcement, retain freedom "
            "of manoeuvre."
        ),
        "adjacent": (
            "Left: A CO seizes OBJ ALPHA (4 km W). Right: C CO screens E flank vic Hill 412. "
            "Front: SCOUT PL conducts R&S NLT H-3. Rear: BN TAC at PHASE LINE STEEL."
        ),
        "civil": (
            "Areas: 80 PAX village (OBJ vic) — non-combatants. Structures: 2x compounds (suspected EN). "
            "People: village elder pro-coalition. ROE annex applies; PID required prior to engagement."
        ),
        "attachments": "ENG TM, FO TM, MED TM effective H-12.",
        "assumptions": "EN composition unchanged at H-Hour; weather permits dawn assault.",
    },
    mission=(
        "B CO attacks at 110530ZMAY26 to seize OBJ BRAVO (vic NB 1234 5678) IOT enable BN passage of "
        "lines along Route GREEN."
    ),
    execution={
        "intent_purpose": (
            "Defeat enemy at OBJ BRAVO so the BN can pass through and continue the attack N."
        ),
        "intent_key_tasks": (
            "1) Isolate OBJ from N reinforcement.\n"
            "2) Suppress EN on Hill 412.\n"
            "3) Seize and consolidate OBJ BRAVO.\n"
            "4) Be prepared (BPT) to defend OBJ for follow-on forces."
        ),
        "intent_end_state": (
            "OBJ BRAVO secured; EN destroyed/captured; B CO consolidated and BPT to defend; civilians "
            "unharmed and accounted for; LOC GREEN open for BN passage."
        ),
        "conops_maneuver": (
            "Form of manoeuvre: envelopment (LEFT). Three phases: PREP, ASSAULT, CONSOLIDATION.\n"
            "PHASE I (H-2 to H-Hour): SE-1 occupies SBF-1 vic Hill 401; ME moves to ASLT POS DELTA via "
            "covered Route RED; SE-2 (RES) at ATK POS ECHO.\n"
            "PHASE II (H-Hour to H+45): SE-1 fires to suppress; ME breaches obstacle and assaults N "
            "compound, then S compound; SE-2 BPT to reinforce ME or block N.\n"
            "PHASE III (H+45 onward): Consolidate, reorganize (LACE), 360° security, EPW handling, "
            "casualty evacuation."
        ),
        "conops_fires": (
            "Priority of fires: ME. Targets: AB1001 (N compound) priority 1; AB1002 (Hill 412 covering "
            "position) priority 2; AB1003 (Route GREEN N approach, FPF) priority 3. Air: 1x CAS pair on "
            "30-min strip alert at H-30 to H+60. Smoke (60mm) IVO breach at H-2 min."
        ),
        "conops_main_effort": "1 PL (ME) — assault N compound then S compound.",
        "conops_phasing": "PHASE I PREP → PHASE II ASSAULT → PHASE III CONSOLIDATION.",
        "tasks": (
            "1 PL (ME): O/O assault N compound vic NB 1235 5680 to destroy EN — purpose: gain foothold.\n"
            "2 PL (SE-1): NLT H-30 occupy SBF-1 vic Hill 401; on ME signal suppress N compound and "
            "Hill 412 — purpose: enable ME assault.\n"
            "3 PL (RES/SE-2): ATK POS ECHO; BPT (1) reinforce ME, (2) block N approach along Route "
            "GREEN, (3) seize S compound.\n"
            "ENG TM: in support of ME — breach wadi obstacle.\n"
            "FO TM: with 1 PL HQ — execute fires plan.\n"
            "MED TM: CCP at ATK POS ECHO; CASEVAC IAW Annex F."
        ),
        "coord_timings": (
            "H-12: REHEARSALS (rock drill, then full-dress where possible).\n"
            "H-3: SP from AA TANGO.\n"
            "H-2: SE-1 SBF set; ME at ASLT POS DELTA.\n"
            "H-Hour (110530Z): assault.\n"
            "H+45 NLT: consolidation complete."
        ),
        "coord_ccir": (
            "PIR: 1) When/where will EN reinforce from N? 2) Confirm/deny ATGM IVO Hill 412.\n"
            "FFIR: 1) ME combat power <70% 2) ENG TM combat ineffective 3) CIV casualty event."
        ),
        "coord_roe": (
            "Standing ROE Annex E. PID required before engagement of personnel. CDE Cat-2 required "
            "for fires within 200m of village. WARNING SHOTS authorised IAW SOP."
        ),
        "coord_risk": (
            "Risk assessment: HIGH (fratricide on flanks during assault).\n"
            "Controls: limit of advance PL BLUE; positive ID handover SE-1 → ME prior to lift/shift; "
            "VS-17 panels orange-up on assault force; brief recognition signals at REHEARSAL."
        ),
        "coord_fscm": (
            "FSCL: PL BLUE. RFL: 100m N of OBJ. CFL: PL RED until H-Hour, then on order. "
            "NFA: village (centre vic NB 1232 5681)."
        ),
    },
    sustainment={
        "supply": (
            "I (subsistence): 2x MRE/PAX/24hr. III (POL): top off vehicles at AA TANGO H-6. "
            "V (ammo): basic load + 50% (see Annex F). VIII (medical): MED TM resupplied at H-6."
        ),
        "transport": "B CO organic vehicles. CASEVAC: 1x M113 dedicated (CASEVAC PRI), 1x M1078 BACKUP.",
        "maintenance": "UMCP at AA TANGO. Recovery vehicle TARGET-1 in trail of RES.",
        "personnel": "Strength reporting at H-1 and H+1. Replacements via BN.",
        "epw": (
            "5 S's & T applied: Search, Silence, Segregate, Safeguard, Speed to BN. Tag with "
            "EPW-1 form. Hold IVO OBJ until BN PSYOP team arrives."
        ),
        "casevac": (
            "CCP at ATK POS ECHO (vic NB 1226 5670). PRI evac via M113 to BAS at AA TANGO; "
            "9-Line via FM CMD net."
        ),
        "medevac": (
            "ROLE 1: BAS at AA TANGO (organic). ROLE 2: BN MED CO 6 km W. ROLE 3: FOB FALCON. "
            "MEDEVAC bird (DUSTOFF 36) on 30-min strip alert."
        ),
    },
    command_signal={
        "command": (
            "CDR with ME during PHASE II. XO at TAC CP vic AA TANGO with RES. 1SG at CCP."
        ),
        "succession": "CDR → XO → 1 PL LDR → 2 PL LDR → 3 PL LDR.",
        "control": "SITREP every 30 min on CMD net. Phase reports on phase complete.",
        "pace_primary": "VHF SINCGARS — CMD net 38.250 / FH-M",
        "pace_alternate": "HF — primary 4.825 / alt 6.775",
        "pace_contingency": "SATCOM TACSAT — CH 102",
        "pace_emergency": "Pyro: green star cluster = consolidate; red star = withdraw. Runner.",
        "callsigns": (
            "BLACK 6 (CDR), BLACK 5 (XO), BLACK 7 (1SG), RED (1 PL/ME), WHITE (2 PL/SE-1), "
            "BLUE (3 PL/RES), GUNNER 6 (FO TM), DUSTOFF 36 (MEDEVAC)."
        ),
        "password": "Challenge: THUNDER / Reply: STORM / Running: HAMMER",
    },
)

OPORD_DEFENSIVE = dict(
    title="Defend in Sector along PL IRON",
    opord_number="OPORD 26-002",
    dtg="120600ZMAY26",
    classification="UNCLASSIFIED//FOUO",
    references=(
        "a. Map: Series M745, Sheet 32A-NW, edition 4, scale 1:50,000\n"
        "b. BDE FRAGO 12 to OPORD 26-04\n"
        "c. Co/Tm Defensive SOP"
    ),
    task_organization=(
        "1 PL — defend BP-1 (RIGHT)\n"
        "2 PL — defend BP-2 (CENTRE) (ME)\n"
        "3 PL — defend BP-3 (LEFT)\n"
        "ATTACHMENTS: ENG TM (mine/wire), AT SEC (2x Javelin), MED TM\n"
        "DETACHMENTS: nil"
    ),
    situation={
        "terrain": (
            "OAKOC. Observation: ridgeline along PL IRON gives 4–6 km LOS S into EN avenues of approach. "
            "AAs: Wadi BLUE (most likely mech), Goat Trail YELLOW (light dismount). Key terrain: ridgeline "
            "saddle (BP-2) — controls both AAs. Obstacles: minefield + wire IVO BP-2 (EMPLACED H-12). "
            "Cover/concealment: rocky outcrops, dry vegetation."
        ),
        "weather": (
            "BMNT 0518 / Sunrise 0552 / Sunset 1928 / EENT 1954. Illum 24% set 0010. Temp 12–34°C. "
            "Wind variable <5 kt. Vis >10 km. Heat injuries probable past 1100Z."
        ),
        "enemy_cds": (
            "Reinforced mech inf company; 8x BMP, 2x T-72, 1x mortar section. Last reported 12 km S "
            "moving N along Wadi BLUE."
        ),
        "enemy_mlcoa": (
            "Hasty attack along Wadi BLUE NLT 120900Z; supporting effort along Goat Trail YELLOW; "
            "mortar prep 10 min."
        ),
        "enemy_mdcoa": (
            "Bypass S of PL IRON to envelop from W; deception attack on Wadi BLUE; CT exploitation "
            "with armour reserve."
        ),
        "higher": (
            "B CO defends in sector NLT 120900Z to retain PL IRON IOT preserve combat power for BN "
            "counter-attack. INTENT: defeat EN main effort forward of PL IRON, hand off to BN reserve."
        ),
        "adjacent": (
            "Left: A CO defends adjacent sector. Right: C CO screens E flank. Front: SCOUT PL screens "
            "fwd of PL TIN. Rear: BN reserve at AA SIERRA."
        ),
        "civil": (
            "Sparse herders in valley S of PL IRON; coordinate via BN CIMIC for evacuation by H-12. "
            "Two known wells near BP-1 — protect."
        ),
        "attachments": "ENG TM (3x squads), AT SEC, MED TM effective H-24.",
        "assumptions": "EN attack within 12 hr; reserve available within 30 min of commitment.",
    },
    mission=(
        "B CO defends in sector along PL IRON NLT 120900ZMAY26 IOT defeat EN attack and preserve "
        "combat power for BN counter-attack."
    ),
    execution={
        "intent_purpose": "Stop EN attack forward of PL IRON; preserve combat power.",
        "intent_key_tasks": (
            "1) Disrupt EN at obstacle belt.\n"
            "2) Mass fires on Wadi BLUE.\n"
            "3) Maintain mutual support across BPs.\n"
            "4) BPT counter-attack with 3 PL on order."
        ),
        "intent_end_state": (
            "EN attack defeated; PL IRON retained; B CO at >75% combat power; EN withdrawing or destroyed."
        ),
        "conops_maneuver": (
            "Defense in depth with engagement area development on Wadi BLUE.\n"
            "PHASE I (PREP, H-24 to H-Hour): emplace obstacles, register fires, rehearse trigger lines.\n"
            "PHASE II (DISRUPT, EN at TRP-1): long-range AT and indirect fires on Wadi BLUE.\n"
            "PHASE III (DEFEAT, EN at TRP-3): all weapons on EA TIGER; BP-2 holds.\n"
            "PHASE IV (REORGANIZE/CTR-ATK): 3 PL counter-attack on order."
        ),
        "conops_fires": (
            "Priority: BP-2 (ME). Targets: AB2001 (TRP-1) FPF, AB2002 (Wadi BLUE choke), AB2003 (EA TIGER). "
            "AT priority: ME during DEFEAT. CAS on call (THUNDER 21)."
        ),
        "conops_main_effort": "2 PL at BP-2 — controls EA TIGER.",
        "conops_phasing": "PREP → DISRUPT → DEFEAT → REORG/CTR-ATK.",
        "tasks": (
            "1 PL (BP-1, RIGHT): block AA YELLOW; tie-in with C CO. Trigger: EN at TRP-2.\n"
            "2 PL (BP-2, CENTRE) ME: defeat EN in EA TIGER. Establish primary, alt, supplemental.\n"
            "3 PL (BP-3, LEFT/RES): tie-in with A CO; BPT counter-attack EA TIGER from N flank.\n"
            "ENG TM: emplace minefield and wire NLT H-12; BPT recover lanes for counter-attack.\n"
            "AT SEC: GS to 2 PL; ME on Javelin engagements at TRP-1."
        ),
        "coord_timings": (
            "H-24: occupy and prep BPs.\n"
            "H-12: obstacles emplaced.\n"
            "H-6: rehearsal.\n"
            "H-3: 100% security; no movement fwd of PL IRON.\n"
            "H-Hour (120900Z): defend."
        ),
        "coord_ccir": (
            "PIR: 1) EN axis of advance & timing. 2) Presence of armour > section.\n"
            "FFIR: 1) BP-2 combat power <70%. 2) Obstacle bypass detected. 3) Loss of comms."
        ),
        "coord_roe": "Standing ROE; weapons hold until trigger lines reached or hostile act/intent.",
        "coord_risk": (
            "Risk: HIGH (heat). Controls: water resupply H-6, H-1; shade if static; medic checks "
            "every 2 hr."
        ),
        "coord_fscm": (
            "FSCL: PL TIN. CFL: PL TIN until obstacle engagement. NFA: well sites at BP-1. "
            "RFL between B CO and A CO along grid line 5680."
        ),
    },
    sustainment={
        "supply": "I/III/V topped at H-12. Class V cache 1x squad position behind BP-2.",
        "transport": "1x M1078 ammo runner attached to RES. CASEVAC dedicated 1x.",
        "maintenance": "UMCP at AA SIERRA; AT SEC weapons priority.",
        "personnel": "Strength every 2 hr starting H-Hour.",
        "epw": "5 S's & T; hold at CCP until BN MP arrives.",
        "casevac": "CCP at AA SIERRA; ground evac PRI; MEDEVAC alt.",
        "medevac": "ROLE 1 BN BAS 4 km N; ROLE 2 FSMC; DUSTOFF 36 on 30-min alert.",
    },
    command_signal={
        "command": "CDR at OP CHARLIE (vic BP-2). XO at TAC CP w/ RES. 1SG at CCP.",
        "succession": "CDR → XO → 2 PL LDR → 1 PL LDR → 3 PL LDR.",
        "control": "SITREP every 30 min; immediate report on enemy contact.",
        "pace_primary": "VHF SINCGARS — CMD 38.250 / FH-D",
        "pace_alternate": "HF 4.825",
        "pace_contingency": "SATCOM TACSAT CH 104",
        "pace_emergency": "Wire (TA-1) to each BP; pyro: red star = withdraw to PL TUNGSTEN.",
        "callsigns": "BLACK 6 (CDR), RED (1 PL), WHITE (2 PL/ME), BLUE (3 PL/RES), HAWK (FO).",
        "password": "Challenge: BARRICADE / Reply: SHIELD / Running: GRANITE",
    },
)

OPORD_STABILITY = dict(
    title="Cordon and Search of Village ZULU",
    opord_number="OPORD 26-003",
    dtg="130400ZMAY26",
    classification="UNCLASSIFIED//FOUO",
    references=(
        "a. Map: Series M745, Sheet 32B-SW, edition 4, scale 1:50,000\n"
        "b. BDE FRAGO 18 (Stability Operation TIDY GARDEN)\n"
        "c. SROE / RUF Cards"
    ),
    task_organization=(
        "1 PL — outer cordon (N + E)\n"
        "2 PL — outer cordon (S + W)\n"
        "3 PL — search element (ME)\n"
        "ATTACHMENTS: HCT (1x team), MWD TM, INTERP (2x), CIMIC TM, MED TM, EOD TM (on call)\n"
        "DETACHMENTS: nil"
    ),
    situation={
        "terrain": (
            "Village ZULU: 60 compounds, central market, mosque on N edge. Single ingress (Route AMBER) "
            "from W. Open desert N/S/E. Two key compounds (12 + 27) suspected weapons cache."
        ),
        "weather": (
            "BMNT 0518 / Sunrise 0552 / Sunset 1928 / EENT 1954. Illum 36% set 0204. "
            "Temp 11–35°C. Wind 5–8 kt SW. Visibility >10 km."
        ),
        "enemy_cds": (
            "Insurgent cell est 8–12 PAX, small arms + IED capability. HCT confirms 2x HVI present "
            "(JACKAL-1 and JACKAL-2) at Compound 12."
        ),
        "enemy_mlcoa": (
            "Concealment within population; no overt resistance; flight via Route AMBER or exfil "
            "S into desert during search."
        ),
        "enemy_mdcoa": (
            "Initiate complex attack: SAF + IED at outer cordon during search; SVBIED at choke point "
            "on Route AMBER."
        ),
        "higher": (
            "B CO conducts cordon and search of village ZULU NLT 130430ZMAY26 IOT capture HVIs "
            "JACKAL-1/2 and seize weapons cache. INTENT: minimise civilian harm; rapid execution."
        ),
        "adjacent": (
            "Left/right: nil. Rear: BN QRF at AA OSCAR (8 km W). Air: ROVER FFEED w/ ARC team "
            "30-min strip alert."
        ),
        "civil": (
            "ASCOPE: village ~600 PAX (mostly women/children); elder MULLA HASSAN pro-coalition; "
            "weekly market on FRIDAY. CIMIC team to engage elder pre-dawn. Mosque NOT to be entered "
            "without elder + INTERP."
        ),
        "attachments": "HCT, MWD, INTERP, CIMIC, MED, EOD as listed.",
        "assumptions": "HVIs present; civilians comply with movement instructions.",
    },
    mission=(
        "B CO conducts a cordon and search of village ZULU at 130430ZMAY26 IOT capture HVIs "
        "JACKAL-1 and JACKAL-2 and seize weapons cache, with minimum harm to civilians."
    ),
    execution={
        "intent_purpose": "Disrupt insurgent cell and remove HVIs from the operating area.",
        "intent_key_tasks": (
            "1) Establish tight outer cordon before BMNT.\n"
            "2) Engage village elder via CIMIC + INTERP prior to entry.\n"
            "3) Search Compounds 12 and 27 first.\n"
            "4) Detain HVIs IAW SROE; tag and evac under chain of custody.\n"
            "5) Restore village access NLT H+4."
        ),
        "intent_end_state": (
            "HVIs detained; weapons cache seized; civilians unharmed; B CO consolidated at AA OSCAR; "
            "village access restored; CIMIC follow-up scheduled."
        ),
        "conops_maneuver": (
            "PHASE I (CORDON, H-30 to H-Hour): silent infil; outer cordon set before BMNT.\n"
            "PHASE II (KNOCK & TALK): CIMIC + INTERP with elder at mosque.\n"
            "PHASE III (SEARCH): 3 PL searches Compound 12 (priority) then 27, then market stalls; "
            "MWD leads; HCT tactical questioning.\n"
            "PHASE IV (RESTORE): apologies (SOL-3 cards), claims process, withdraw."
        ),
        "conops_fires": (
            "No preplanned fires. Air ROVER on station for ISR only. Smoke (red) on call for "
            "recognition; no kinetic CAS without CDR approval."
        ),
        "conops_main_effort": "3 PL — search element.",
        "conops_phasing": "CORDON → KNOCK & TALK → SEARCH → RESTORE.",
        "tasks": (
            "1 PL: outer cordon N + E; ROE escalation cards; PID checkpoints; civilian movement only "
            "via designated lanes.\n"
            "2 PL: outer cordon S + W incl. choke point on Route AMBER; SVBIED standoff procedures.\n"
            "3 PL (ME): search element. Compound 12 first (HVI priority), then 27, then market.\n"
            "MWD: with 3 PL HQ.\n"
            "HCT: tactical questioning with 3 PL.\n"
            "EOD: on 5-min recall at AA OSCAR.\n"
            "CIMIC: knock & talk; manage claims at H+3."
        ),
        "coord_timings": (
            "H-2: SP from AA OSCAR.\n"
            "H-30 min: cordon set.\n"
            "H-Hour (130430Z): knock & talk.\n"
            "H+15: search begins.\n"
            "H+3: claims.\n"
            "H+4 NLT: cordon withdrawn."
        ),
        "coord_ccir": (
            "PIR: 1) PID of JACKAL-1/2. 2) IED indicators on Route AMBER.\n"
            "FFIR: 1) Civilian casualty event. 2) Detainee escape. 3) SAF on cordon."
        ),
        "coord_roe": (
            "RUF Card alpha-1 (graduated escalation: shout-show-shove-shoot). PID and hostile "
            "intent/act required. No engagement of the mosque."
        ),
        "coord_risk": (
            "Risk: MEDIUM. Controls: dismount discipline, EOD standoff, female searcher (MED TM "
            "augment) for women, photograph all detainees with detainee number."
        ),
        "coord_fscm": "NFA: village. RFA: market square. NO-STRIKE: mosque (grid registered).",
    },
    sustainment={
        "supply": "I/III topped at H-2. V minimal — non-lethal first; lethal on demand.",
        "transport": "Organic; 2x detainee vehicles staged at AA OSCAR.",
        "maintenance": "UMCP at AA OSCAR.",
        "personnel": "Strength reports H-1 / H+0 / H+2 / H+4.",
        "epw": (
            "Detainees handled IAW Detainee Ops SOP: separate by category, photograph, capture cards, "
            "biometric enrolment (HIIDE) at AA OSCAR."
        ),
        "casevac": "CCP at AA OSCAR; ground evac primary.",
        "medevac": "DUSTOFF 36 30-min strip alert. Civilian casualties evac to ROLE 2 IAW SROE.",
    },
    command_signal={
        "command": "CDR with 3 PL HQ during PHASE II–III. XO at TAC CP at AA OSCAR.",
        "succession": "CDR → XO → 3 PL LDR → 1 PL LDR → 2 PL LDR.",
        "control": "Phase reports on phase complete. Detainee report immediately.",
        "pace_primary": "VHF SINCGARS — CMD 38.450 / FH-S",
        "pace_alternate": "MBITR PRC-148 secondary 38.500",
        "pace_contingency": "SATCOM TACSAT CH 106",
        "pace_emergency": "Pyro: green smoke = collapse cordon; red smoke = QRF.",
        "callsigns": "BLACK 6 (CDR), RED/WHITE/BLUE (1/2/3 PL), KENNEL 1 (MWD), CIMIC 7, EOD 9.",
        "password": "Challenge: GARDEN / Reply: TIDY / Running: WILLOW",
    },
)


# Each OPORD includes a small AOI snapshot. Coords are illustrative — change to your AO.
SNAPSHOTS = {
    "OPORD 26-001": [
        (
            "OBJ BRAVO + Hill 412",
            [50.84, 4.30, 50.88, 4.40],
            13,
            "Assault axis along Route RED; SBF on Hill 401 ridgeline.",
        ),
    ],
    "OPORD 26-002": [
        (
            "EA TIGER along Wadi BLUE",
            [50.78, 4.20, 50.84, 4.32],
            13,
            "BP-2 controls saddle; obstacles emplaced 200m S of PL IRON.",
        ),
    ],
    "OPORD 26-003": [
        (
            "Village ZULU + Route AMBER",
            [50.86, 4.36, 50.89, 4.42],
            14,
            "Single ingress W; outer cordon 200m offset; mosque on N edge.",
        ),
    ],
}


def main() -> int:
    init_db()
    db = SessionLocal()
    try:
        author = (
            db.query(Operator)
            .filter(Operator.role.in_(("ADMIN", "BATTLE_CAPTAIN")))
            .first()
            or db.query(Operator).first()
        )
        if not author:
            print(
                "No operators in DB — seed first with: uv run arrow-seed",
                file=sys.stderr,
            )
            return 1
        print(f"Authoring 3 OPORDs as {author.callsign} ({author.role})")

        for tmpl in (OPORD_OFFENSIVE, OPORD_DEFENSIVE, OPORD_STABILITY):
            existing = (
                db.query(Opord)
                .filter(Opord.opord_number == tmpl["opord_number"])
                .first()
            )
            if existing:
                print(
                    f"  · skipping (already exists): {tmpl['opord_number']} — {tmpl['title']}"
                )
                continue
            o = Opord(
                title=tmpl["title"],
                opord_number=tmpl["opord_number"],
                dtg=tmpl["dtg"],
                time_zone="ZULU",
                classification=tmpl["classification"],
                references=tmpl["references"],
                task_organization=tmpl["task_organization"],
                situation=json.dumps(tmpl["situation"]),
                mission=tmpl["mission"],
                execution=json.dumps(tmpl["execution"]),
                sustainment=json.dumps(tmpl["sustainment"]),
                command_signal=json.dumps(tmpl["command_signal"]),
                map_snapshots="[]",
                status="PUBLISHED",
                author_id=author.id,
                recipient_ids="[]",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(o)
            db.commit()
            db.refresh(o)
            print(f"  ✓ created: id={o.id}  {tmpl['opord_number']} — {tmpl['title']}")

            for label, bbox, zoom, ann in SNAPSHOTS.get(tmpl["opord_number"], []):
                _attach_snapshot(db, o, label, bbox, zoom, ann, author.id)
                print(f"     + snapshot: {label}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
