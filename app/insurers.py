"""Maps a payer name as written in the files ("AETNA LIFE INSURANCE COMPANY", "UHC Empire Plan") to a standard company
("Aetna (CVS Health)", "UnitedHealth Group"). Used by the dashboard's insurer filter and by the insurer list in drafts\\.
Parent-company groupings use well-known ownership only; uncertain affiliations stay as their own company."""
import re

INS, BLUE, NET, PLAN, EMP, GOV, PROV, IDR, OUT, IND = (
    "Insurer", "Blue Cross Blue Shield plan", "Network / TPA / repricer", "Self-funded, union or federal plan",
    "Employer (plan sponsor)", "Government", "Provider or provider-side company", "IDR entity or IDR vendor",
    "Not a payer (out-of-scope case)", "Individual")

# (pattern, standard company, kind, note). First match wins, so specific names come before general ones.
# A blank company means "keep the name as written".
RULES = [
    (r"empire plan", "UnitedHealth Group", INS, "NY State Empire Plan; medical benefits administered by UnitedHealthcare"),
    (r"united ?health|unitedhealthcare|\buhc\b|united health|oxford|\bumr\b|golden rule|optimum choice", "UnitedHealth Group", INS, ""),
    (r"meritain", "Aetna (CVS Health)", INS, "Meritain Health is Aetna's third-party administrator"),
    (r"aetna", "Aetna (CVS Health)", INS, ""),
    (r"cigna|connecticut general", "Cigna", INS, ""),
    (r"horizon", "Horizon Blue Cross Blue Shield of New Jersey", BLUE, ""),
    (r"health care services? corp|blue ?cross blue ?shield of (illinois|texas|new mexico|oklahoma|montana)|bcbs (illinois|texas)"
     r"|bluecross blueshield of illinois", "Health Care Service Corp. (HCSC)", BLUE, "Operates BCBS of IL, TX, NM, OK and MT"),
    (r"blue cross blue shield of wisconsin|empire blue|anthem|antehm|elevance|healthy alliance|rightchoice|rocky mountain hospital",
     "Elevance Health (Anthem)", BLUE, ""),
    (r"blue cross blue shield (healthcare plan )?of georgia", "Elevance Health (Anthem)", BLUE, "Anthem's Georgia plan"),
    (r"florida blue|blue ?cross (and )?blue ?shield of florida|bcbs of florida", "Florida Blue", BLUE, ""),
    (r"independence blue", "Independence Blue Cross", BLUE, ""),
    (r"highmark", "Highmark", BLUE, ""),
    (r"blue cross (and )?blue shield of massachusetts", "Blue Cross Blue Shield of Massachusetts", BLUE, ""),
    (r"blue cross and blue shield of north carolina", "Blue Cross and Blue Shield of North Carolina", BLUE, ""),
    (r"blue cross and blue shield of south carolina", "Blue Cross and Blue Shield of South Carolina", BLUE, ""),
    (r"bcbs of alabama|blue cross (and )?blue shield of alabama", "Blue Cross and Blue Shield of Alabama", BLUE, ""),
    (r"blue cross and blue shield of arizona", "Blue Cross Blue Shield of Arizona", BLUE, ""),
    (r"blue cross blue shield of oklahoma", "Health Care Service Corp. (HCSC)", BLUE, ""),
    (r"blue cross blue shield association", "Blue Cross Blue Shield Association", BLUE, "The national association, not a plan"),
    (r"^blue cross blue shield( entities)?$", "Blue Cross Blue Shield (unspecified)", BLUE, "Check the case for the specific plan"),
    (r"wellmark", "Wellmark", BLUE, ""),
    (r"premera", "Premera Blue Cross", BLUE, ""),
    (r"carefirst", "CareFirst", BLUE, ""),
    (r"california physicians", "Blue Shield of California", BLUE, "California Physicians' Service is Blue Shield of California"),
    (r"geoblue|worldwide insurance services", "GeoBlue (Worldwide Insurance Services)", INS, ""),
    (r"kaiser", "Kaiser Permanente", INS, ""),
    (r"centene|ambetter|fidelis", "Centene", INS, ""),
    (r"humana", "Humana", INS, ""),
    (r"oscar", "Oscar Health", INS, ""),
    (r"emblem|\bghi\b", "EmblemHealth", INS, ""),
    (r"medical mutual", "Medical Mutual of Ohio", INS, ""),
    (r"providence health plan", "Providence Health Plan", INS, ""),
    (r"sentara", "Sentara Health", INS, ""),
    (r"summacare", "SummaCare", INS, ""),
    (r"priority health", "Priority Health", INS, ""),
    (r"health alliance plan", "Health Alliance Plan of Michigan", INS, ""),
    (r"adventist health plan", "Adventist Health Plan", INS, ""),
    (r"allegiance", "Allegiance Life & Health", INS, ""),
    (r"avmed", "AvMed", INS, ""),
    (r"capital health plan", "Capital Health Plan", INS, ""),
    (r"freedom life", "Freedom Life (USHEALTH Group)", INS, ""),
    (r"multiplan|claritev", "MultiPlan (Claritev)", NET, "Out-of-network repricer"),
    (r"magnacare", "MagnaCare", NET, ""),
    (r"healthcomp", "HealthComp", NET, ""),
    (r"boon-chapman", "Boon-Chapman", NET, ""),
    (r"marpai", "Marpai Health", NET, ""),
    (r"leading edge", "Leading Edge Administrators", NET, ""),
    (r"medcost", "MedCost", NET, ""),
    (r"phoenix administrators|performance health", "Phoenix Administrators (Performance Health)", NET, ""),
    (r"web tpa", "WEB TPA", NET, ""),
    (r"qualcare", "QualCare", NET, ""),
    (r"entrust", "Entrust", NET, ""),
    (r"1199seiu", "1199SEIU National Benefit Fund", PLAN, ""),
    (r"local 272", "Local 272 Welfare Fund", PLAN, ""),
    (r"samba", "SAMBA Health Benefit Plan", PLAN, "Federal employee plan"),
    (r"letter carriers|nalc", "NALC Health Benefit Plan", PLAN, "Federal employee plan"),
    (r"keating", "Keating Auto Group Employee Benefit Plan", PLAN, ""),
    (r"custom design benefits|sumeral", "Custom Design Benefits", PLAN, ""),
    (r"microsoft", "Microsoft Corp.", EMP, ""),
    (r"daugherty", "Daugherty Systems", EMP, ""),
    (r"whiteriver", "Whiteriver Unified School District", EMP, ""),
    (r"magnum services", "Magnum Services", EMP, ""),
    (r"health (and|&) human|\bhhs\b|department of|secretary|^united states$|dep't of", "U.S. Government (HHS and others)", GOV,
     "Rule challenges"),
    (r"med evaluators", "Medical Evaluators of Texas", IDR, "Certified IDR entity"),
    (r"halomd", "HaloMD", IDR, "Provider-side IDR vendor (insurer-filed cases)"),
    (r"radiology partners|northstar anesthesia|vituity|sood medical|maui memorial|neuromonitoring|nutex|zotec|m&d capital|ags health|"
     r"laredo regional|prime healthcare|multicare|premier health|concord company|bromedicon|transform weight|ascension|strategic limited",
     "", PROV, "Provider side; the insurer is the plaintiff or the case is out of scope"),
    (r"irhythm|transworld|u\.s\. anesthesia|schwartz sladkus|daniel h\. cook|scott nago", "", OUT, "Not an IDR payment case"),
    (r"do not docket", "", OUT, "Placeholder entry on a consolidated court docket, not a party"),
    (r"^(duarte|poonia|rowe, m\.d\.)$", "", IND, "Individual defendant"),
]
_COMPILED = [(re.compile(p, re.I), c, k, n) for p, c, k, n in RULES]


def classify(name):
    """(standard company, kind, note) for one payer name; unrecognised names keep their own name, kind "Check"."""
    n = " ".join(str(name or "").split())
    for pat, company, kind, note in _COMPILED:
        if pat.search(n):
            return company or n, kind, note
    return n, "Check", "Not recognised; needs a person to classify"


def split(payer):
    """'Aetna Health / Aetna Life / Cigna entities' -> ['Aetna Health', 'Aetna Life', 'Cigna entities']."""
    return [p.strip(" .") for p in re.split(r"\s/\s|;", str(payer or "")) if p.strip(" .")]


def companies(payer):
    """Standard companies named in one payer cell, without repeats, in order."""
    out = []
    for p in split(payer):
        c = classify(p)[0]
        if c not in out:
            out.append(c)
    return out


if __name__ == "__main__":
    assert companies("Aetna Health / Aetna Life / Cigna entities") == ["Aetna (CVS Health)", "Cigna"]
    assert companies("UHC Empire Plan") == ["UnitedHealth Group"]
    assert companies("Health Care Service Corporation d/b/a Blue Cross Blue Shield of Texas") == ["Health Care Service Corp. (HCSC)"]
    assert classify("Some New Plan Inc.")[1] == "Check"
    print("ok")
