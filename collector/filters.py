"""Location, role-type and discipline classification for raw listings."""
import re

AU_STATES = {
    "NSW": "NSW", "New South Wales": "NSW", "VIC": "VIC", "Victoria": "VIC", "QLD": "QLD", "Queensland": "QLD",
    "WA": "WA", "Western Australia": "WA", "SA": "SA", "South Australia": "SA", "TAS": "TAS", "Tasmania": "TAS",
    "ACT": "ACT", "Australian Capital Territory": "ACT", "NT": "NT", "Northern Territory": "NT",
}
AU_CITIES = {
    "Sydney": "NSW", "Newcastle": "NSW", "Wollongong": "NSW", "Parramatta": "NSW", "Macquarie Park": "NSW",
    "North Ryde": "NSW", "Lucas Heights": "NSW", "Kemps Creek": "NSW", "Albury": "NSW", "Orange": "NSW",
    "Parkes": "NSW", "Bathurst": "NSW", "Penrith": "NSW", "Liverpool": "NSW", "Nowra": "NSW", "Williamtown": "NSW",
    "Melbourne": "VIC", "Geelong": "VIC", "Ballarat": "VIC", "Bendigo": "VIC", "Clayton": "VIC", "Port Melbourne": "VIC",
    "Fishermans Bend": "VIC", "Mulgrave": "VIC", "Notting Hill": "VIC", "Southbank": "VIC", "Docklands": "VIC",
    "Traralgon": "VIC", "Morwell": "VIC", "Latrobe Valley": "VIC", "Mount Waverley": "VIC", "Dandenong": "VIC",
    "Avalon": "VIC", "Laverton": "VIC", "Keilor East": "VIC", "Richmond, VIC": "VIC", "Box Hill": "VIC",
    "Brisbane": "QLD", "Gold Coast": "QLD", "Sunshine Coast": "QLD", "Toowoomba": "QLD", "Townsville": "QLD",
    "Cairns": "QLD", "Mackay": "QLD", "Rockhampton": "QLD", "Gladstone": "QLD", "Ipswich": "QLD", "Amberley": "QLD",
    "Yatala": "QLD", "Calamvale": "QLD", "Bundaberg": "QLD", "Mount Isa": "QLD", "Gladstone": "QLD",
    "Perth": "WA", "Fremantle": "WA", "Henderson": "WA", "Kalgoorlie": "WA", "Karratha": "WA", "Port Hedland": "WA",
    "Geraldton": "WA", "Kensington, WA": "WA", "Bunbury": "WA", "Kwinana": "WA", "Pilbara": "WA",
    "Adelaide": "SA", "Osborne": "SA", "Edinburgh, SA": "SA", "Mawson Lakes": "SA", "Whyalla": "SA", "Lot Fourteen": "SA",
    "Canberra": "ACT", "Tidbinbilla": "ACT", "Hobart": "TAS", "Launceston": "TAS", "Burnie": "TAS",
    "Darwin": "NT", "Alice Springs": "NT",
}
FOREIGN_GUARDS = re.compile(
    r"Melbourne,\s*(FL|Florida)|Brisbane,\s*(CA|California)|Perth,\s*(Scotland|ON|Ontario|UK)|Perth Amboy|"
    r"Newcastle(?: upon Tyne|,\s*(UK|England|DE|Delaware))|Sydney,\s*(NS|Nova Scotia)|Darwin,\s*(MN|Minnesota)|"
    r"Adelaide,\s*(CO|Colorado)|Richmond,\s*(VA|CA|BC|Virginia)|Victoria,\s*(BC|British Columbia|TX|Texas|Seychelles)|"
    r"Orange,\s*(CA|County)|Liverpool,\s*(UK|England|NY)|Kensington,\s*(London|MD|UK)|Edinburgh(?!,\s*SA)",
    re.I)
NON_AU_ONLY = re.compile(r"\b(USA|United States|United Kingdom|Singapore|India|New Zealand|Canada|Germany|Japan|China|"
                         r"Hong Kong|Philippines|Malaysia|Indonesia|Vietnam|Ireland|Netherlands|France|Israel|Taiwan|Korea|"
                         r"Remote - US|US Remote)\b", re.I)


FOREIGN_MARK = re.compile(
    r"\b(USA|U\.S\.A?\.?|United States|America|UK|U\.K\.|United Kingdom|England|Scotland|Wales|Canada|Ireland|India|"
    r"Singapore|China|Hong Kong|Japan|Germany|France|Netherlands|New Zealand|Israel|Mexico|Brazil|Philippines|Malaysia|"
    r"Indonesia|Korea|Taiwan|Vietnam|Thailand|Poland|Spain|Italy|Sweden|Switzerland|Norway|Denmark|Finland|Belgium|"
    r"Austria|Czech|Romania|Hungary|Portugal|Turkey|UAE|Dubai|Saudi|Qatar|South Africa|Chile|Argentina|Colombia|"
    r"Florida|Texas|California|Washington|Georgia|Massachusetts|Virginia|Colorado|Arizona|Ohio|Michigan|Illinois|"
    r"Pennsylvania|New York|New Jersey|Oregon|Utah|Alabama|Maryland|Minnesota|Missouri|North Carolina|South Carolina|"
    r"Tennessee|Kentucky|Indiana|Wisconsin|Connecticut|Nevada|Kansas|Oklahoma|Louisiana|Iowa|Idaho|Hawaii|Alaska|"
    r"Remote - US|US Remote|Remote US|NYC|SF|Bay Area|Seattle|Redmond|Bellevue|Austin|Boston|Chicago|Atlanta|Denver|"
    r"Houston|Dallas|San Francisco|San Jose|Palo Alto|Mountain View|Sunnyvale|Santa Clara|Los Angeles|San Diego|"
    r"Costa Mesa|Irvine|Arlington|Huntsville|Everett|Tukwila|London|Aberdeen|Manchester|Cambridge|Oxford|Bristol|"
    r"Edinburgh|Glasgow|Dublin|Toronto|Vancouver|Montreal|Ottawa|Paris|Munich|Berlin|Hamburg|Amsterdam|Zurich|"
    r"Stockholm|Bangalore|Bengaluru|Hyderabad|Mumbai|Pune|Chennai|Delhi|Gurgaon|Shanghai|Beijing|Shenzhen|Tokyo|"
    r"Seoul|Taipei|Kuala Lumpur|Jakarta|Manila|Ho Chi Minh|Bangkok|Auckland|Wellington|Christchurch|Tel Aviv|Haifa)\b"
    r"|,\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|"
    r"OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WV|WI|WY|DC)\b|\bUS,\s*[A-Z]{2}\b|^US\b|\bUS\s*[-–]")
STRONG_ABBR = {"NSW", "VIC", "QLD", "TAS", "ACT", "NT"}


def _segment_states(seg):
    t = FOREIGN_GUARDS.sub(" ", seg)
    has_au_word = bool(re.search(r"\bAustralia\b|\bAustralian\b", t))
    if FOREIGN_MARK.search(t) and not has_au_word:
        return set()
    states = set()
    for name, code in AU_CITIES.items():
        if re.search(r"\b" + re.escape(name) + r"\b", t):
            states.add(code)
    for name, code in AU_STATES.items():
        if len(name) <= 3:
            ctx = re.search(r"(?:,\s*|\(|\b-\s*|\s)" + name + r"\b|\b" + name + r"\s+\d{4}\b|^" + name + r"\b", t)
            if not ctx:
                continue
            if name in STRONG_ABBR or states or has_au_word or re.search(r"\b\d{4}\b", t):
                states.add(code)
        elif re.search(r"\b" + name + r"\b", t):
            if name == "Victoria" and re.search(r"Victoria\s+(Station|Street|Park|Road|Island)", t):
                continue
            if name == "Western Australia" or name == "South Australia" or name not in ("Victoria", "Queensland", "Tasmania") or has_au_word or not FOREIGN_MARK.search(t):
                states.add(code)
    if not states and (has_au_word or re.search(r"\bAUS\b|,\s*AU\b|\bAU$", t)):
        states.add("AU")
    return states


def au_states(loc_text):
    """Return sorted AU state codes mentioned, [] if none, or ['AU'] for country-level match.
    Evaluates each location segment separately so 'Seattle, WA | Sydney, NSW' still counts Sydney only."""
    if not loc_text:
        return []
    states = set()
    for seg in re.split(r"\s*[|;/]\s*|\s{2,}|\n", loc_text):
        if seg.strip():
            states |= _segment_states(seg)
    if "AU" in states and len(states) > 1:
        states.discard("AU")
    return sorted(states)


FOREIGN_TITLE = re.compile(
    r"[-–(,]\s*(NYC|New York|London|Aberdeen|Singapore|Hong Kong|Chicago|Amsterdam|Seattle|Austin|Boston|Houston|"
    r"Toronto|Dublin|Paris|Munich|Mumbai|Bangalore|Bengaluru|Shanghai|Beijing|Tokyo|Seoul|Taipei|Auckland|"
    r"US|USA|UK|EMEA|Americas|India|China|Japan|Canada|Europe|Ireland|Germany|Netherlands|NZ|New Zealand|"
    r"Malaysia|Philippines|Indonesia|Vietnam|Thailand)\b", re.I)


def is_australian(loc_text, default_au=False):
    st = au_states(loc_text)
    if st:
        return True
    if not loc_text or not loc_text.strip():
        return default_au
    if default_au and not NON_AU_ONLY.search(loc_text) and re.search(r"remote|multiple|various|\d+ locations", loc_text, re.I):
        return True
    return False


STUDENT_RE = re.compile(
    r"\bintern(?:ship)?s?\b|\binterns?hip\b|\bvacation(?:er|al)?\b|\bvacationers?\b|\bsummer\s+(?:student|program|"
    r"internship|vacation|research|scholar|clerk|engineer|intake|placement)|\bwinter\s+(?:program|internship|vacation|"
    r"school|intake|student)|\bcadet(?:ship)?s?\b|\bstudent\b|\bundergrad(?:uate)?\b|\bindustry\s+placement|"
    r"\bplacement\s+(?:program|student|year)|\bco-?op\b|\bindustry[- ]based learning\b|\byear in industry\b|"
    r"\bstudentships?\b|\bwork experience\b|\bresearch scholarship|\bscholarship program|\btaste of research\b|"
    r"\bpenultimate\b|\bwork integrated learning\b|\bWIL\b|\bearly careers?\b|\bfuture talent\b|\bfutures program",
    re.I)
GRAD_RE = re.compile(r"\bgraduate\s+(?:program|programme|engineer|role|position|intake|scheme|analyst|developer|"
                     r"scientist|researcher|software|electrical|hardware)|\bgrad(?:uate)? program\b|\bnew grad|"
                     r"\b20(?:2[6-9])\s+graduate|\bgraduates?\b(?!\s+(?:degree|qualification))", re.I)
EXCLUDE_TITLE = re.compile(
    r"\bapprentice|\bpre-apprentice|\bstudent (?:services|support|advis|recruit|administration|experience officer|"
    r"engagement|counsel|wellbeing|accommodation)|\bteacher|\btutor\b|\blecturer|\bnurs(?:e|ing)\b|\bpharmac|"
    r"\bphysiotherap|\bpsycholog|\bdental\b|\bveterinar|\bchef\b|\bbarista|\bretail assistant|\bsales associate|"
    r"\baccount(?:ant|ing)\b|\baudit|\btax\b|\blegal\b|\blawyer|\bparalegal|\bpaid placement|\bplacement fee|"
    r"\bvirtual (?:experience|internship)|\bjob simulation|\bforage\b|\bpostdoc|\bphd scholarship|\bphd candidate|"
    r"\bprofessor|\bsenior\b|\bprincipal\b|\blead\b|\bmanager\b|\bdirector\b|\bhead of\b|\bchief\b|\bstaff engineer",
    re.I)
TECH_RE = re.compile(
    r"engineer|engineering|electrical|electronic|embedded|firmware|hardware|software|fpga|asic|rtl|vlsi|silicon|"
    r"semiconductor|\brf\b|radio|antenna|microwave|signal|\bdsp\b|control|automation|robot|mechatron|autonom|"
    r"systems?\b|power|energy|grid|substation|protection|renewable|battery|\bev\b|vehicle|aerospace|avionic|space|"
    r"satellite|quantum|photonic|optic|laser|machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|"
    r"data|computer|computing|research|science|scientist|physics|math|verification|validation|reliability|"
    r"manufactur|process|mechanical|technical|technology|telecom|network|cyber|instrument|sensor|lidar|radar|nuclear|"
    r"defen[cs]e|biomedical|medical device|\bpcb\b|product development|r&d|stem\b|developer|programming|quant|trading|"
    r"analyst|infrastructure|civil|structural|chemical|mining|geotech|environmental|water|transport|rail|construction",
    re.I)

DISCIPLINES = [
    ("Electrical", r"electrical|\bee\b|power engineer|high voltage|\bhv\b|protection|substation|switchgear"),
    ("Electronics/Hardware", r"electronic|hardware|\bpcb\b|circuit|analog|analogue|mixed[- ]signal|board design"),
    ("Embedded/Firmware", r"embedded|firmware|microcontroller|\bmcu\b|rtos|stm32|esp32|device driver|bsp"),
    ("Semiconductors/FPGA", r"fpga|asic|rtl|vlsi|silicon|semiconductor|verilog|vhdl|chip|soc\b|tape-?out"),
    ("RF/Comms", r"\brf\b|radio|antenna|microwave|wireless|telecom|5g|satcom|spectrum|signal processing|\bdsp\b|sdr"),
    ("Power/Energy", r"power system|energy|grid|renewable|solar|wind|battery|storage|hydrogen|transmission|distribution|"
                     r"network planning|generation|electricity"),
    ("Controls/Automation", r"control|automation|plc|scada|instrumentation|process control|\bot\b"),
    ("Robotics/Autonomy", r"robot|autonom|perception|slam|navigation|guidance|gnc|drone|uav|uas|unmanned"),
    ("Mechatronics", r"mechatron"),
    ("ML/AI/Data", r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|computer vision|data scien|"
                   r"data engineer|\bllm|neural|analytics"),
    ("Software", r"software|developer|programming|full[- ]stack|backend|back-end|frontend|front-end|devops|cloud|sre"),
    ("Quantum/Photonics", r"quantum|photonic|optic|laser|cryogenic|qubit"),
    ("Aerospace/Space", r"aerospace|aircraft|aviation|avionic|space|satellite|launch|rocket|propulsion|flight"),
    ("Defence", r"defen[cs]e|military|naval|submarine|weapon|security clearance|nv1|baseline clearance"),
    ("Systems/Integration", r"systems engineer|integration|systems integration|mbse|requirements|verification|"
                            r"validation|test engineer|v&v"),
    ("Mechanical", r"mechanical|thermal|structur|cad\b|fea\b|cfd"),
    ("Civil/Construction", r"civil|construction|geotech|structural engineer|transport planning|road"),
    ("Chemical/Process", r"chemical|process engineer|metallurg"),
    ("Biomedical", r"biomedical|medical device|medtech|clinical|neuro|implant|hearing"),
    ("Research", r"research|scientist|studentship|scholarship|laboratory|\blab\b"),
    ("Manufacturing/Quality", r"manufactur|quality|production|lean|reliability"),
    ("Networks/Cyber", r"network engineer|cyber|security engineer|infosec"),
    ("Quant/Trading", r"\bquant\b|quantitative|trading|trader|market maker"),
    ("Mining/Resources", r"mining|mine\b|mineral|resources|oil|gas|lng"),
]
_DISC = [(n, re.compile(p, re.I)) for n, p in DISCIPLINES]


def disciplines(text):
    return [n for n, rx in _DISC if rx.search(text or "")]


def role_type(title, text=""):
    t = f"{title} || {text[:3000]}"
    tl = title.lower()
    if re.search(r"cadet", tl):
        return "cadetship"
    if re.search(r"taste of research|research (?:scholarship|internship|placement)|vacation research|summer research|"
                 r"studentship|vacation scholar|research experience", t, re.I):
        return "vacation-research"
    if re.search(r"winter", tl):
        return "winter"
    if re.search(r"summer|vacation|vacationer|nov(?:ember)?\s*20\d\d\s*[-–]\s*feb|december.{0,30}february", t[:600], re.I):
        return "summer"
    if re.search(r"part[- ]time|casual|during (?:the )?semester|\b1-3 days|\b2-3 days|days per week", t, re.I) and \
            re.search(r"intern|student|undergrad", t, re.I):
        return "part-time"
    if re.search(r"12[- ]month|year[- ]long|year in industry|industry placement|6[- ]12 months|six[- ]month|6[- ]month|"
                 r"industry based learning|co-?op", t, re.I):
        return "year-long"
    if GRAD_RE.search(title) and not re.search(r"intern|undergrad|student", tl):
        return "graduate"
    if STUDENT_RE.search(title):
        return "intern-other"
    if GRAD_RE.search(t[:400]):
        return "graduate"
    return "intern-other"


def is_student_or_grad(title, text=""):
    if EXCLUDE_TITLE.search(title or ""):
        # still allow "Senior"/"Lead" etc? no - those are experienced roles
        return False
    if STUDENT_RE.search(title or "") or GRAD_RE.search(title or ""):
        return True
    # generic titles like "Summer Program" or "Early Careers" handled above; also check first part of text
    head = (text or "")[:500]
    return bool(re.search(r"\b(internship|vacation program|summer program|cadetship|graduate program)\b", head, re.I)) \
        and bool(re.search(r"program|intake|student", title or "", re.I))


def is_technical(title, text=""):
    return bool(TECH_RE.search(title or "") or TECH_RE.search((text or "")[:2500]))


# Student-pays placement providers: kept but flagged, never ranked as real openings.
PLACEMENT_AGENCIES = re.compile(r"readygrad|premium graduate placements|careerdc|gradability|the intern group|"
                                r"australian internships|intern options|global experiences|"
                                r"internship placement fee", re.I)
