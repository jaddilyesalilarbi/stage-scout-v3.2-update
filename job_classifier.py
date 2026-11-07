"""Deterministic, evidence-based internship triage; no network or model calls.

``classify(job, profile=None)`` never mutates its arguments. PDM potential is
independent of mechanical relevance and applicant constraints. A high potential
is an inference about missions, never a promise of EPFL academic acceptance.

Optional profile keys: ``languages`` (list of names/codes or mapping to level),
``duration_months`` (number or [minimum, maximum]), ``start_date`` (ISO date),
``nationality`` and ``education``. Absent facts stay unknown. The default
education is an EPFL mechanical engineering master; the default area is Europe.
"""
from __future__ import annotations

import html
import re
import unicodedata
from datetime import date

from selection_filters import classify_location

RULES_VERSION = "missions-v1"
PDM_LABELS = {
    "explicit": "PDM / mémoire de master explicite",
    "high": "Fort potentiel PDM",
    "medium": "Potentiel PDM à préciser",
    "low": "Faible potentiel PDM",
    "uncertain": "Informations insuffisantes",
}
TECHNICAL_CATEGORIES = [
    "Mechanical Design", "R&D / Product Development", "Simulation / CAE",
    "Testing / Validation", "Manufacturing / Production", "Systems Integration",
    "Robotics / Mechatronics", "Automation / Control", "Materials / Processes",
    "Energy / Thermal", "Quality", "Supply Chain / Logistics",
    "Project Management", "Other",
]


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "–": "-", "—": "-", "‑": "-"}))
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


_MISSION_HEADING = (
    r"(?:(?:your|the|key|main)\s+)?(?:tasks?|responsibilit(?:y|ies)|missions?|"
    r"activities|duties)|(?:vos|les|tes|principales|votre)\s+(?:missions?|activites|role)|"
    r"what (?:you(?:'ll| will)? do|to expect)|(?:your|the) (?:role|impact)|"
    r"job (?:description|responsibilities)|description du poste|your new responsibilities|votre mission|responsabilites|aufgaben|ihre aufgaben"
)
_QUAL_HEADING = (
    r"(?:(?:your|the|minimum|basic|preferred|desired)\s+)?(?:qualifications?|"
    r"requirements?|profile|skills|experience)|(?:votre|ton|votre futur) profil|"
    r"profil(?: recherche)?|competences(?: requises)?|what you(?:'ll| will)? (?:bring|need)|"
    r"about you|who you are|who we are looking for|qui cherchons nous|desirable background|education|qualifikationen|ihr profil"
)
_COMPANY_HEADING = (
    r"about (?:us|the company)|who we are|our (?:company|benefits|offer)|"
    r"company (?:description|overview)|a propos(?: de nous)?|qui sommes.nous|"
    r"notre (?:entreprise|offre)|benefits|what we offer|additional information|"
    r"informations? (?:complementaires|supplementaires)|description de l'entreprise|das unternehmen|why join us|why us"
)
_HEADINGS = [(re.compile(r"^(?:" + p + r")\s*[:?\-]?\s*$"), kind)
             for p, kind in ((_MISSION_HEADING, "mission"), (_QUAL_HEADING, "qualification"),
                             (_COMPANY_HEADING, "company"))]


def _sections(text: str) -> list[tuple[str, str]]:
    """Preserve verbatim sentence snippets while remembering heading scope."""
    # ATS HTML is usually already normalized; this also accepts raw HTML safely.
    text = html.unescape(text)
    text = re.sub(r"(?i)<(?:br\s*/?|/?(?:p|div|li|h[1-6]|ul|ol))[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    # Flattened ATS exports retain capitalized headings and bullets but lose
    # line breaks. Restore boundaries without changing source snippet text.
    inline_headers = ("Your new responsibilities", "Who we are looking for", "Responsibilities", "Responsabilités",
                      "Your Impact", "Your Profile", "Profil recherché", "Votre mission", "Education", "Profil")
    for heading in inline_headers:
        text = re.sub(r"(?<!\w)" + re.escape(heading) + r"(?=\s)", "\n" + heading + "\n", text)
    text = re.sub(r"[•·]\s*", "\n", text)
    text = re.sub(r"\s+(?=(?:Elaborer|Réaliser|Rechercher|Concevoir|Suivre|Tester|Développer|Analyser|Documenter|Soutenir)\s)", "\n", text)
    section, result = "unknown", []
    for line in text.splitlines():
        line = line.strip().lstrip("•*-– ").strip()
        if not line:
            continue
        # A heading followed by body on the same line is common in ATS exports.
        lead, sep, tail = line.partition(":")
        heading = _norm(lead if sep else line)
        kind = next((kind for rx, kind in _HEADINGS if rx.fullmatch(heading)), None)
        if kind:
            section = kind
            if not sep or not tail.strip():
                continue
            line = tail.strip()
        for sentence in re.split(r"(?<=[.!?;])\s+(?=[A-ZÀ-Ÿa-z])", line):
            if sentence.strip():
                if section == "company" and _has(r"\b(?:you (?:will|'ll)|vous (?:serez|aurez|allez)|vos missions)\b", _norm(sentence)):
                    section = "mission"
                result.append((sentence.strip(), section))
    return result


_ACTION = (
    r"\b(?:design\w*|concevoir|concev\w*|conception|develop\w*|developp\w*|"
    r"build\w*|constru\w*|prototyp\w*|dimensionn\w*|simulat\w*|model\w*|"
    r"optimis\w*|optimiz\w*|investigat\w*|research\w*|etud\w*|explor\w*|"
    r"analy[sz]\w*|analys\w*|compar\w*|evalu\w*|valid\w*|characteri[sz]\w*|"
    r"caracteris\w*|integr\w*|implement\w*|test\w*|essai\w*|mesur\w*|"
    r"execut\w*|perform\w*|realis\w*|effectuer|conduct\w*|etabli\w*|quantifi\w*|lead|run|running|"
    r"support\w*|assist\w*|contribu\w*|particip\w*|maintain\w*|maintenir|"
    r"update\w*|mettre a jour|track\w*|suiv\w*|document\w*|coordin\w*|"
    r"organis\w*|organiz\w*|prepar\w*|manage\w*|gerer|plan\w*|defini\w*|affectation|automatisation|automation|"
    r"instrument\w*|control\w*|collect\w*|ensure|improve|programm\w*|"
    r"entwerf\w*|entwick\w*|untersuch\w*|durchfuhr\w*)\b"
)
_DESIGN = r"\b(?:design\w*|concevoir|concev\w*|conception|dimensionn\w*|entwerf\w*)\b"
_DEVELOP = r"\b(?:develop\w*|developp\w*|build\w*|constru\w*|prototyp\w*|entwick\w*)\b"
_INVESTIGATE = r"\b(?:investigat\w*|research\w*|etud\w*|explor\w*|compar\w*|evalu\w*|characteri[sz]\w*|caracteris\w*|untersuch\w*)\b"
_SIMULATE = r"\b(?:simulat\w*|model\w*|optimis\w*|optimiz\w*|analys\w*|analy[sz]\w*)\b"
_VALIDATE = r"\b(?:valid\w*|test\w*|essai\w*|mesur\w*|experiment\w*)\b"
_MECH_OBJECT = (
    r"\b(?:mechanic\w*|mecani\w*|mechatron\w*|mecatron\w*|robot\w*|"
    r"gripper\w*|bracket\w*|fixture\w*|outillage\w*|banc\w*|test (?:rig|bench|stand)|"
    r"component\w*|composant\w*|assembly|assemblies|assemblage\w*|actuator\w*|"
    r"actionneur\w*|motor\w*|moteur\w*|gear\w*|bearing\w*|structures?|"
    r"structural\w*|stiffness|rigidite|fatigue|vibration\w*|stress\w*|contrainte\w*|"
    r"composite\w*|material\w*|materia\w*|polymer\w*|metal\w*|alloy\w*|"
    r"therm\w*|energy|energi\w*|battery|batteries|batterie\w*|fluid\w*|"
    r"aerodynam\w*|hydrogen\w*|hydrogene|turbine\w*|heat\w*|chaleur|"
    r"manufactur\w*|fabricat\w*|machin\w*|usinage|weld\w*|soud\w*|"
    r"additive|production|product\w*|produit\w*|sensor\w*|capteur\w*|"
    r"control\w*|commande\w*|system\w*|hardware|handling|DUT|compressor\w*|refrigeration|instrumentation|"
    r"CAD|CAO|CFD|FEA|FEM|elements? finis|finite element|engineering calculations|prototype\w*)\b"
)
_STRONG_MECH = (
    r"\b(?:mechanic\w*|mecani\w*|mechatron\w*|mecatron\w*|robot\w*|gripper\w*|"
    r"bracket\w*|fixture\w*|banc\w*|test (?:rig|bench|stand)|CAD|CAO|CREO|CATIA|Solidworks|FEA|FEM|CFD|"
    r"elements? finis|structural\w*|acier|steel|stiffness|rigidite|composite\w*|material\w*|materia\w*|"
    r"therm\w*|fluid\w*|heat\w*|manufactur\w*|fabricat\w*|actuator\w*|"
    r"motor\w*|moteur\w*|battery|batteries|batterie\w*|turbine\w*|vibration\w*|"
    r"hardware|handling|DUT|compressor\w*|refrigeration|finite element|outillage\w*|prototype\w*)\b"
)
_ROUTINE = (
    r"\b(?:routine|standard|existing|established|predefined|repetitiv\w*|"
    r"quotidien\w*|existant\w*|procedur\w*|inventory|inventaire|"
    r"report\w*|rapport\w*|dashboard\w*|tableau\w*|database|base de donnees|"
    r"maintenance|maintain\w*|mettre a jour|update\w*|delivery|deliveries|livraison\w*)\b"
)
_QUAL_SENTENCE = (
    r"\b(?:experience (?:in|with|of)|knowledge of|familiarity with|"
    r"knowledge and experience|skills in|competences en|connaissances? (?:en|de)|"
    r"experience (?:en|de|dans)|is (?:required|preferred|desirable|a plus)|passion for|interest in|"
    r"you (?:have|are|hold|possess)|vous (?:avez|etes|maitrisez)|"
    r"candidate\w* (?:must|should)|applicants? (?:must|should))\b"
)

_CATEGORY_PATTERNS = {
    "Mechanical Design": r"\b(?:CAD|CAO|catia|solidworks|creo|nx|design\w*|concevoir|conception|dimensionn\w*)\b",
    "Simulation / CAE": r"\b(?:FEA|FEM|CFD|CAE|simulat\w*|elements? finis|finite element|ansys|abaqus|model\w*)\b",
    "Testing / Validation": _VALIDATE + r"|\b(?:verification|measurement\w*|device under test|caracterisation|characterization)\b",
    "Manufacturing / Production": r"\b(?:manufactur\w*|production|fabricat\w*|assembly|assemblage|usinage|machining|industrialisa\w*)\b",
    "Systems Integration": r"\b(?:integr\w*|interface\w*|system architecture|architecture systeme)\b",
    "Robotics / Mechatronics": r"\b(?:robot\w*|mechatron\w*|mecatron\w*|gripper\w*|actuator\w*)\b",
    "Automation / Control": r"\b(?:automat\w*|control\w*|commande\w*|PLC|PID|regulat\w*|system identification|signal\w*|microcontroller\w*|data acquisition)\b",
    "Materials / Processes": r"\b(?:material\w*|materia\w*|composite\w*|polymer\w*|metal\w*|alloy\w*|process\w*|procede\w*)\b",
    "Energy / Thermal": r"\b(?:energi\w*|energy|therm\w*|heat\w*|battery|batteries|batterie\w*|hydrogen\w*|turbine\w*|chaleur|refrigeration|compressor\w*|temperature\w*)\b",
    "Quality": r"\b(?:qualit\w*|inspection\w*|non.conform\w*|metrolog\w*|acceptance)\b",
    "Supply Chain / Logistics": r"\b(?:supply chain|logisti\w*|purchas\w*|procurement|achat\w*|deliveries|delivery|livraison\w*|inventory|inventaire|approvisionnement|simulation de flux|stockage|cargaison)\b",
    "Project Management": r"\b(?:project management|gestion de projet|project plann\w*|coordin\w*|planning|budget\w*)\b",
}


def _mission_analysis(parts: list[tuple[str, str]]) -> list[dict]:
    result, seen = [], set()
    for snippet, section in parts:
        text = _norm(snippet)
        if text in seen or section in {"qualification", "company"}:
            continue
        seen.add(text)
        if _has(_QUAL_SENTENCE, text) or not _has(_ACTION, text):
            continue
        if _has(r"^(?:looking for an opportunity|curious about|interested in|want to join)\b", text):
            continue
        if _has(r"\b(?:recherch\w* .{0,30}(?:talents|stagiaire)|looking for .{0,30}(?:intern|talent)|recrut\w*|join our team)\b", text):
            continue
        if _has(r"\b(?:we (?:are|design|develop|manufacture|offer)|our company|our (?:r&d|research) department|notre entreprise|nous sommes)\b", text):
            continue
        if _has(r"\b(?:not|never|no need to|ne .{0,25} pas|sans)\s+(?:\w+\s+){0,2}(?:design|develop|concevoir|conception|developp)", text):
            continue
        mechanical = _has(_MECH_OBJECT, text)
        anchor = _has(_STRONG_MECH, text)
        research_object = mechanical or _has(r"\b(?:jumeau numerique|digital twin|supply chain|stockage|model\w*|simulation de flux|scenarios?|pilot\w* terrain)\b", text)
        design = mechanical and _has(_DESIGN, text)
        develop = research_object and _has(_DEVELOP, text)
        research = research_object and _has(_INVESTIGATE, text)
        simulation = research_object and (_has(_SIMULATE, text) or _has(r"\b(?:finite element analysis|calcul\w*|FEA|FEM|CFD)\b", text))
        validation = mechanical and _has(_VALIDATE, text)
        if _has(r"\b(?:cahier des charges|design maturity|design principles|design process|design engineering team)\b", text):
            design = False
        routine = _has(_ROUTINE, text)
        administrative = _has(r"\b(?:reports?|rapports?|dashboards?|database|tableaux? de bord|project management|production plan|business analysis|functional design workshops|design decisions|build phase)\b", text) and not anchor
        if administrative:
            design = develop = research = simulation = False
        # "Develop reports" is administration; "design an experimental rig" is
        # engineering even when the rig will execute standard tests afterwards.
        strong = design or develop or research or simulation
        if routine and not (design or develop or research or simulation):
            strong = False
        categories = {cat for cat, pattern in _CATEGORY_PATTERNS.items() if _has(pattern, text)}
        if "Mechanical Design" in categories and not anchor:
            categories.remove("Mechanical Design")
        abstract_model = _has(r"\b(?:supply chain|logisti\w*|cost\w*|cout\w*|language model|semantic|semantique|database|base de donnees)\b", text)
        if "Simulation / CAE" in categories and not (anchor or (mechanical and not abstract_model)):
            categories.remove("Simulation / CAE")
        if "Materials / Processes" in categories and not anchor and not _has(r"\b(?:material\w*|materia\w*|composite\w*|polymer\w*|metal\w*|alloy\w*|procede\w*)\b", text):
            categories.remove("Materials / Processes")
        if "Testing / Validation" in categories and not (mechanical or routine or _has(r"\b(?:validation|test|measurement|prototype)\w*\b", text)):
            categories.remove("Testing / Validation")
        if _has(r"\b(?:automated|automation)\b", text) and _has(r"\b(?:handling|DUT|transfer|positioning)\b", text):
            categories.add("Robotics / Mechatronics")
        if strong:
            categories.add("R&D / Product Development")
        novelty = _has(r"\b(?:new|novel|nouve\w*|experiment\w*|prototype\w*|hypothes\w*|hypothese\w*|proof.of.concept)\b", text)
        families = {name for name, found in (("design", design or develop), ("investigation", research),
                                           ("simulation", simulation), ("validation", validation and not routine)) if found}
        result.append(dict(snippet=snippet, categories=categories, strong=strong,
                           mechanical=mechanical, anchor=anchor, routine=routine,
                           support=_has(r"\b(?:support\w*|assist\w*|aider)\b", text),
                           novelty=novelty, families=families))
    return result


_THESIS = r"\b(?:master(?:'s|s)?[ -]?(?:thesis|project)|masterarbeit|master these|memoire de master|projet de master|PDM|PFE|projet de fin d.etudes|travail de master)\b"


def _explicit_thesis(title: str, parts: list[tuple[str, str]]) -> bool:
    if _has(_THESIS, _norm(title)):
        return True
    for snippet, section in parts:
        text = _norm(snippet)
        if section in {"qualification", "company"} or not _has(_THESIS, text):
            continue
        if _has(r"\b(?:previous|past|experience|completed|not available|not possible|pas de|aucun|no thesis)\b", text):
            continue
        if _has(r"\b(?:offer\w*|opportunit\w*|possib\w*|can|could|may|peut|cadre|sujet|propos\w*|realise\w*|thesis (?:student|intern|topic)|masterarbeit)\b", text) or _has(r"^(?:this|the|ce|cet|cette)\s+" + _THESIS, text):
            return True
    return False


def _constraint(status="unknown", value="", evidence=None, reason="Information non précisée dans l'offre."):
    return dict(status=status, value=value, evidence=evidence or [], reason=reason)


def _location_text(value: object) -> str:
    """Read ATS strings, SmartRecruiters cities and JSON-LD PostalAddress."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " / ".join(filter(None, (_location_text(item) for item in value)))
    if isinstance(value, dict):
        if value.get("address"):
            return _location_text(value["address"])
        fields = [value.get("addressLocality") or value.get("city"),
                  value.get("addressRegion") or value.get("region"),
                  value.get("addressCountry") or value.get("country") or value.get("countryCode")]
        return ", ".join(str(field.get("name") or "") if isinstance(field, dict) else str(field)
                         for field in fields if field)
    return ""


def _constraints(job: dict, profile: dict, parts: list[tuple[str, str]]) -> dict:
    # Company marketing is not a restriction on the candidate.
    lines = [(s, _norm(s)) for s, kind in parts if kind != "company"]
    structured = job.get("structured") if isinstance(job.get("structured"), dict) else {}
    # Never feed metadata into mission classification. Generic ATS startDate
    # often means publication; only jobStartDate names the employment start.
    for key in ("duration", "jobDuration", "educationRequirements"):
        value = structured.get(key)
        if isinstance(value, str) and value.strip():
            lines.append((value, _norm(value)))
    c = {key: _constraint() for key in ("duration", "start_date", "languages", "location", "education", "eligibility")}
    location = str(job.get("location") or "")
    if not location:
        location = next((_location_text(structured[key]) for key in ("jobLocation", "location", "PrimaryLocation", "locations")
                         if structured.get(key) and _location_text(structured[key])), "")
        if not location and structured.get("country"):
            location = _location_text(structured)
    loc = classify_location(location)
    if location:
        c["location"] = _constraint({"europe": "compatible", "outside": "incompatible"}.get(loc, "unknown"),
                                    location, [location], {"europe": "Localisation en Europe.", "outside": "Localisation explicitement hors d'Europe."}.get(loc, "Localisation ambiguë ou non reconnue."))
    duration_pattern = r"\b(\d{1,2})(?:\s*(?:[-–aà]|to)\s*(\d{1,2}))?\s*(?:months?|mois|monate)\b"
    duration = next(((s, re.search(duration_pattern, t)) for s, t in lines
                     if re.search(duration_pattern, t) and not _has(r"\b(?:experience|anciennete|previous|prior|ago|auparavant)\b", t)), None)
    if duration:
        snippet, match = duration
        low, high = int(match[1]), int(match[2] or match[1])
        if _has(r"\b(?:at least|minimum|au moins)\b", _norm(snippet)):
            high = 120
        elif _has(r"\b(?:at most|maximum|up to|au plus|jusqu.a)\b", _norm(snippet)):
            low = 0
        wanted = profile.get("duration_months")
        status, reason = "unknown", "Durée publiée ; disponibilité du candidat à confirmer."
        if isinstance(wanted, (int, float)):
            status = "compatible" if low <= wanted <= high else "incompatible"
            reason = "Durée comparée à la durée souhaitée fournie dans le profil ; ce n'est pas une restriction administrative."
        elif isinstance(wanted, (list, tuple)) and len(wanted) == 2:
            status = "compatible" if low <= max(wanted) and high >= min(wanted) else "incompatible"
            reason = "Durée comparée à l'intervalle souhaité fourni dans le profil ; ce n'est pas une restriction administrative."
        c["duration"] = _constraint(status, match[0], [snippet], reason)
    elif job.get("duration"):
        c["duration"] = _constraint(value=str(job["duration"]), evidence=[str(job["duration"])], reason="Durée structurée publiée ; comparaison à confirmer.")

    months = r"(?:january|february|march|april|may|june|july|august|september|october|november|december|janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)"
    start = next((s for s, t in lines if _has(r"\b(?:start(?:ing)?(?: date)?|commenc\w*|debut|demarrage|available from|a partir de)\b", t)
                  and _has(r"\b(?:\d{4}-\d{2}-\d{2}|" + months + r"|immediate\w*|asap|des que possible)\b", t)), None)
    explicit_start = job.get("start_date") or structured.get("jobStartDate")
    if start or explicit_start:
        snippet = start or str(explicit_start)
        c["start_date"] = _constraint(value=snippet, evidence=[snippet], reason="Début publié ; disponibilité du candidat à confirmer.")
        published = re.search(r"\b\d{4}-\d{2}-\d{2}\b", snippet)
        if published and profile.get("start_date"):
            try:
                offered, available = date.fromisoformat(published[0]), date.fromisoformat(str(profile["start_date"]))
                c["start_date"].update(status="compatible" if available <= offered else "incompatible", reason="Date ISO publiée comparée à la disponibilité fournie.")
            except ValueError:
                pass

    language_names = {"en": r"\b(?:english|anglais)\b", "fr": r"\b(?:french|francais)\b",
                      "de": r"\b(?:german|allemand|deutsch)\b", "it": r"\b(?:italian|italien)\b",
                      "es": r"\b(?:spanish|espagnol)\b", "nl": r"\b(?:dutch|neerlandais)\b"}
    required, language_lines, language_groups = set(), [], []
    for s, text in lines:
        names = {key for key, pattern in language_names.items() if _has(pattern, text)}
        optional = r"(?:a plus|an advantage|preferred|desirable|beneficial|nice to have|optional|not required|not mandatory|un atout|apprecie\w*|souhaite\w*|non obligatoire|pas exige\w*)"
        for key, pattern in language_names.items():
            if _has(pattern + r"\s+(?:(?:is|are|would|be|est|sont|serait|kenntnisse|skills)\s+){0,3}" + optional, text) or _has(optional + r"\s+(?:knowledge of\s+)?" + pattern, text):
                names.discard(key)
        if not names:
            continue
        if _has(r"\b(?:required|must|mandatory|essential|fluent|fluency|proficien\w*|excellent|courant\w*|exige\w*|obligatoire|maitrise)\b", text):
            required |= names
            language_lines.append(s)
            language_groups.append((names, bool(_has(r"\b(?:or|ou|oder)\b", text)), text))
    if required:
        status, reason = "unknown", "Langues exigées publiées ; compétences linguistiques du candidat inconnues."
        known = profile.get("languages")
        if isinstance(known, (list, tuple, set, dict)):
            known_names = " ".join(str(x) for x in known)
            skills = {key for key, pattern in language_names.items() if key in known or _has(pattern, _norm(known_names))}
            if isinstance(known, dict):
                for language, level in known.items():
                    if _norm(level) in {"a0", "a1", "a2", "b1", "beginner", "basic", "debutant"}:
                        skills -= {key for key, pattern in language_names.items() if language == key or _has(pattern, _norm(language))}
            status = "compatible" if all(bool(names & skills) if alternative else names <= skills for names, alternative, _ in language_groups) else "incompatible"
            reason = "Langues exigées comparées aux langues explicitement déclarées ; niveau à vérifier."
        excluded = set(profile.get("excluded_languages") or [])
        if profile.get("exclude_required_german"):
            excluded.add("de")
        if any(names <= excluded if alternative else bool(names & excluded) for names, alternative, _ in language_groups):
            status, reason = "incompatible", "Langue explicitement obligatoire exclue par le filtre de recherche configuré ; aucune compétence du candidat n'est supposée."
        c["languages"] = _constraint(status, ", ".join(sorted(required)), language_lines, reason)

    education = [(s, t) for s, t in lines if _has(r"\b(?:master\w*|MSc|M\.Sc|bac\s*\+\s*5|ingenieur|PhD|Ph\.D|doctor\w*)\b", t)]
    phd_only = [(s, t) for s, t in education if _has(r"\b(?:phd|ph\.d|doctor\w*)\b", t)
                and _has(r"\b(?:must|only|required|mandatory|exclusiv\w*|uniquement|exige\w*|obligatoire)\b", t)
                and not _has(r"\b(?:master\w*|msc|or|ou|preferred|preferable|not required)\b", t)]
    if phd_only:
        c["education"] = _constraint("incompatible", "PhD obligatoire", [s for s, _ in phd_only], "Doctorat explicitement obligatoire ; profil par défaut en master.")
    elif education:
        masters = [(s, t) for s, t in education if _has(r"\b(?:master\w*|msc|bac\s*\+\s*5|ingenieur)\b", t)]
        if masters:
            unrelated = any(_has(r"\b(?:marketing|finance|accounting|commerce|business administration|law|droit|human resources|computer science only|informatique uniquement)\b", t) for _, t in masters)
            c["education"] = _constraint("unknown" if unrelated else "compatible", "Master / ingénieur", [s for s, _ in masters], "Discipline exigée à vérifier avec le master mécanique EPFL." if unrelated else "Niveau master / ingénieur compatible avec le master EPFL du profil.")
        else:
            c["education"] = _constraint(value="Doctorat mentionné", evidence=[s for s, _ in education], reason="Mention de doctorat sans obligation exclusive établie.")

    eligible = [(s, t) for s, t in lines if _has(r"\b(?:citizenship|citizens?|nationality|nationalite|ressortissant\w*|work (?:permit|authori[sz]ation)|right to work|visa|security clearance|habilitation|convention de stage)\b", t)
                and not _has(r"\b(?:regardless|irrespective|without regard|equal opportunit\w*|sans distinction)\b", t)]
    if eligible:
        c["eligibility"] = _constraint(value=" ; ".join(s for s, _ in eligible), evidence=[s for s, _ in eligible], reason="Condition d'éligibilité publiée ; nationalité, autorisation ou convention du candidat à vérifier.")
    return c


def classify(job: dict, profile: dict | None = None) -> dict:
    """Classify a posting from its full description, conservatively and purely."""
    profile = profile if isinstance(profile, dict) else {}
    title = str(job.get("title") or "")
    full = str(job.get("description") or "").strip()
    excerpt = str(job.get("description_excerpt") or "").strip()
    text = full or excerpt
    parts = _sections(text)
    missions = _mission_analysis(parts)
    explicit = _explicit_thesis(title, parts)
    missing = []
    partial = not full or str(job.get("description_status") or "").lower() in {"partial", "legacy_excerpt", "missing", "failed", "unavailable"}
    if not text:
        missing.append("Description de l'offre manquante.")
    elif partial:
        missing.append("Description complète non disponible ; classement fondé sur un texte partiel.")
    if not missions:
        missing.append("Missions concrètes non identifiées.")
    substantive = [m for m in missions if m["strong"]]
    families = set().union(*(m["families"] for m in substantive)) if substantive else set()
    novelty = any(m["novelty"] for m in substantive)
    if explicit:
        potential, reason = "explicit", "L'intitulé ou le texte de l'offre propose explicitement un mémoire / projet de master."
    elif len(families) >= 2 and (len(substantive) >= 2 or novelty) and not all(m["support"] for m in substantive):
        potential, reason = "high", "Les missions associent conception ou investigation à une démarche de modélisation, comparaison ou validation technique."
    elif substantive:
        potential, reason = "medium", "Une mission technique de conception ou d'étude est identifiée ; autonomie, question de recherche et livrable académique restent à préciser."
    elif missions:
        potential, reason = "low", "Les missions décrites relèvent surtout de l'exécution, du suivi ou du support, sans démarche de conception / investigation établie."
    else:
        potential, reason = "uncertain", "Le contenu disponible ne permet pas d'identifier une démarche de projet de master."
    if potential in {"high", "medium"}:
        missing.append("Accord académique EPFL et encadrement du PDM à confirmer.")
    categories = set().union(*(m["categories"] for m in missions)) if missions else set()
    contributions = []
    for m in missions:
        if m["anchor"]:
            points = 38 if m["strong"] else 18
        elif m["mechanical"]:
            points = 22 if m["strong"] else 10
        else:
            points = 4
        contributions.append(points)
    # Bound evidence contributions, rather than counting repeated buzzwords.
    score = min(100, sum(sorted(contributions, reverse=True)[:3]))
    if not any(m["anchor"] for m in missions):
        score = min(score, 30)
    tech_reasons = []
    for m in sorted(missions, key=lambda m: (m["anchor"], m["strong"]), reverse=True)[:3]:
        label = "Mission technique mécanique" if m["anchor"] else "Mission à pertinence mécanique limitée"
        tech_reasons.append(label + " : " + m["snippet"])
    if not tech_reasons:
        tech_reasons = ["Aucune mission technique exploitable dans le texte disponible."]
    if not categories:
        categories.add("Other")
    constraints = _constraints(job, profile, parts)
    names = {"duration": "Durée", "start_date": "Date de début", "languages": "Langues",
             "location": "Localisation", "education": "Formation", "eligibility": "Éligibilité"}
    missing.extend(names[key] + " : " + constraint["reason"] for key, constraint in constraints.items()
                   if constraint["status"] == "unknown")
    statuses = {c["status"] for c in constraints.values()}
    overall = "incompatible" if "incompatible" in statuses else "unknown" if "unknown" in statuses else "compatible"
    confidence = "low" if partial or potential == "uncertain" else "high" if explicit or len(missions) >= 2 else "medium"
    return {
        "rules_version": RULES_VERSION, "pdm_potential": potential,
        "pdm_label": PDM_LABELS[potential], "pdm_explicit": explicit,
        "pdm_reason": reason, "pdm_confidence": confidence,
        "missing_information": missing,
        "technical_categories": [cat for cat in TECHNICAL_CATEGORIES if cat in categories],
        "technical_score": score, "technical_reasons": tech_reasons,
        "mission_evidence": [m["snippet"] for m in missions][:8],
        "constraints": constraints, "constraint_status": overall,
        "needs_human_review": confidence != "high" or overall == "unknown" or potential in {"high", "medium", "uncertain"},
    }
