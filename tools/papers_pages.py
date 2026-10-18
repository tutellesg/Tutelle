"""Writes Tutelle's static past-paper browse pages, so search engines can read the paper list.

  past-papers.html                      every level, subject and school, with links
  past-papers-<level>-<subject>.html    e.g. past-papers-p6-mathematics.html
  past-papers-school-<school>.html      e.g. past-papers-school-nanyang-primary-school.html
  sitemap.xml, robots.txt

The files themselves stay locked: every row links to papers.html, where parents sign up and open them.

Run from the website folder:
  python tools/papers_pages.py --live              reads the current paper list from Supabase
  python tools/papers_pages.py --data papers.json  reads a saved list instead
The website address comes from tools/site.json ("site_url"). Change it there when the domain is ready.
Uses the Python standard library only.
"""
import argparse, datetime, html, json, os, re, sys, urllib.parse, urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONF = json.load(open(os.path.join(HERE, "site.json")))
SITE = CONF["site_url"].rstrip("/")
LEVELS = ["P1", "P2", "P3", "P4", "P5", "P6", "Sec 1", "Sec 2", "Sec 3", "Sec 4", "Sec 5", "JC1", "JC2"]
TYPES = ["Exam papers", "Worksheets", "Quizzes"]
ALSO = {"Mathematics": "Math", "E-Math": "Elementary Mathematics (E Math)", "A-Math": "Additional Mathematics (A Math)",
        "H2 Math": "H2 Mathematics", "Higher Chinese": "HCL"}
G_NOTE = {"G1": "G1 (formerly N(T))", "G2": "G2 (formerly N(A))", "G3": "G3 (formerly Express)"}
STATIC_PAGES = ["index.html", "papers.html", "practice.html", "enrichment.html", "exam-dates.html", "tutors.html"]
e = html.escape


def slug(s):
    s = s.lower().replace("&", " and ").replace("'", "").replace(".", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def course(p):
    if not p["level"].startswith("Sec "):
        return ""
    m = re.search(r"\bG([123])\b", p["exam"])
    if m:
        return "G" + m.group(1)
    if "N(T)" in p["exam"]:
        return "G1"
    if "N(A)" in p["exam"]:
        return "G2"
    return "G3"


def clean_title(t):
    out = re.sub(r"\s*(?:\bN\([AT]\)|\bG[123]\b)\s*", " ", t)
    return re.sub(r"\s+", " ", out).strip() or t


def open_url(**q):
    return "papers.html?" + urllib.parse.urlencode({k: v for k, v in q.items() if v not in (None, "")})


def years(ps):
    ys = sorted({p["year"] for p in ps})
    return str(ys[0]) if len(ys) == 1 else f"{ys[0]}–{ys[-1]}"


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def load(args):
    if args.data:
        rows = json.load(open(args.data))
    else:
        url = CONF["supabase_url"].rstrip("/") + "/rest/v1/papers?select=level,subject,year,exam,school,has_answers,category&active=eq.true&limit=10000"
        req = urllib.request.Request(url, headers={"apikey": CONF["supabase_key"], "Authorization": "Bearer " + CONF["supabase_key"]})
        rows = json.load(urllib.request.urlopen(req, timeout=30))
    for p in rows:
        p["category"] = p.get("category") or "Exam papers"
        p["course"] = course(p)
        p["title"] = clean_title(p["exam"])
    return [p for p in rows if p["level"] in LEVELS]


def table(ps, show_school, link_args):
    rows = []
    for p in sorted(ps, key=lambda p: (-p["year"], p["title"], p["school"])):
        g = f' <span class="g">{e(G_NOTE[p["course"]].split(" ")[0])}</span>' if p["course"] else ""
        school = f'<span class="s">{e(p["school"])}</span>' if show_school else ""
        ans = '<span class="ans yes">✓ With answers</span>' if p.get("has_answers") else ('<span class="ans">Paper only</span>' if p.get("has_answers") is False else "")
        href = open_url(**link_args(p))
        label = f'Open {p["year"]} {p["level"]} {p["subject"]} {p["title"]}, {p["school"]}'
        rows.append(f'<tr><td>{p["year"]}</td><th scope="row">{e(p["title"])}{g}{school}</th><td>{ans}</td>'
                    f'<td class="o"><a href="{e(href)}" aria-label="{e(label)}">Open</a></td></tr>')
    return ('<table class="plist"><colgroup><col class="y"><col><col class="a"><col class="o"></colgroup>'
            '<thead><tr><th scope="col">Year</th><th scope="col">Paper</th><th scope="col">Answers</th><th scope="col"><span class="sr">Open</span></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def facts(ps):
    schools = len({p["school"] for p in ps})
    ans = sum(1 for p in ps if p.get("has_answers"))
    return (f'<p class="pstats"><span><b>{len(ps)}</b> {"paper" if len(ps) == 1 else "papers"}</span>'
            f'<span><b>{schools}</b> {"school" if schools == 1 else "schools"}</span>'
            f'<span><b>{ans}</b> with answers</span><span>{years(ps)}</span></p>')


def jsonld(name, desc, url, crumbs, items):
    data = [
        {"@context": "https://schema.org", "@type": "CollectionPage", "name": name, "description": desc, "url": url,
         "isPartOf": {"@type": "WebSite", "name": "Tutelle", "url": SITE + "/"},
         "mainEntity": {"@type": "ItemList", "numberOfItems": len(items),
                        "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n} for i, n in enumerate(items[:100])]}},
        {"@context": "https://schema.org", "@type": "BreadcrumbList",
         "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + "/" + h} for i, (n, h) in enumerate(crumbs)]},
    ]
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


# Clean addresses: GitHub Pages serves papers.html at /papers, so links leave out ".html" and the home page is "./".
OWN = r"(?:index|practice|papers|enrichment|tutors|exam-dates|shortlist|past-papers[a-z0-9-]*)"
def clean_urls(html):
    html = re.sub(r"""(["'`(/])index\.html(?=[#?"'`)])""", lambda m: m.group(1) + ("" if m.group(1) == "/" else "./"), html)
    return re.sub(r"\b(" + OWN + r")\.html\b(?![-\w])", r"\1", html)


def page(tpl, *, file, title, desc, h1, lede, crumbs, content, side, open_link, items, fact_html=""):
    url = f"{SITE}/{file}"
    crumb_html = " › ".join(f'<a href="{e(h)}">{e(n)}</a>' for n, h in crumbs[:-1]) + f" › {e(crumbs[-1][0])}"
    out = tpl
    for k, v in {"{{TITLE}}": e(title), "{{DESC}}": e(desc), "{{CANONICAL}}": e(url), "{{JSONLD}}": jsonld(h1, desc, url, crumbs, items),
                 "{{CRUMBS}}": crumb_html, "{{H1}}": e(h1), "{{LEDE}}": e(lede), "{{FACTS}}": fact_html,
                 "{{CONTENT}}": content, "{{SIDE}}": side, "{{OPEN_URL}}": e(open_link)}.items():
        out = out.replace(k, v)
    open(os.path.join(ROOT, file), "w").write(clean_urls(out))
    return file


def side_links(title, links):
    if not links:
        return ""
    lis = "".join(f'<a href="{e(h)}">{e(n)}</a>' for n, h in links)
    return f'<div class="card"><div class="card-body"><h3>{e(title)}</h3><div class="links">{lis}</div></div></div>'


def subject_file(level, subject):
    return f"past-papers-{slug(level)}-{slug(subject)}.html"


def school_file(school):
    return f"past-papers-school-{slug(school)}.html"


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--live", action="store_true")
    g.add_argument("--data")
    args = ap.parse_args()
    papers = load(args)
    tpl = open(os.path.join(HERE, "browse-template.html")).read()
    home = ("Home", "index.html"); browse = ("Past year papers", "past-papers.html")
    written = []

    by_ls = defaultdict(list); by_school = defaultdict(list)
    for p in papers:
        by_ls[(p["level"], p["subject"])].append(p)
        by_school[p["school"]].append(p)
    ls_keys = sorted(by_ls, key=lambda k: (LEVELS.index(k[0]), k[1]))

    # one page per level and subject
    for level, subject in ls_keys:
        ps = by_ls[(level, subject)]
        schools = len({p["school"] for p in ps}); ans = sum(1 for p in ps if p.get("has_answers"))
        name = f"{level} {subject}"
        also = f" Also known as {level} {ALSO[subject]}." if subject in ALSO else ""
        gs = sorted({p["course"] for p in ps if p["course"]})
        g_line = f" Includes {', '.join(G_NOTE[x] for x in gs)} papers." if gs else ""
        types = [t for t in TYPES if any(p["category"] == t for p in ps)]
        content = ""
        for t in types:
            tp = [p for p in ps if p["category"] == t]
            content += f'<div class="group"><h2>{e(t)}</h2>{table(tp, True, lambda p: dict(level=p["level"], subject=p["subject"], type=p["category"], year=p["year"], school=p["school"]))}</div>'
        same_level = [(f"{l} {s}", subject_file(l, s)) for l, s in ls_keys if l == level and s != subject]
        school_links = [(s, school_file(s)) for s in sorted({p["school"] for p in ps})][:30]
        written.append(page(tpl, file=subject_file(level, subject),
            title=f"{name} Past Year Papers ({years(ps)}) | Tutelle",
            desc=f"{plural(len(ps), 'free ' + name + ' paper')} from {plural(schools, 'school')}, {years(ps)}: {', '.join(t.lower() for t in types)}. {ans} with answers.",
            h1=f"{name} past year papers",
            lede=f"School {', '.join(t.lower() for t in types)} for {name}, for revision at home. Free for parents.{also}{g_line}",
            crumbs=[home, browse, (name, subject_file(level, subject))], content=content,
            side=side_links(f"Other {level} subjects", same_level) + side_links(f"Schools with {name} papers", school_links),
            open_link=open_url(level=level, subject=subject), items=[f'{p["year"]} {name} {p["title"]} – {p["school"]}' for p in ps], fact_html=facts(ps)))

    # one page per school
    for school in sorted(by_school):
        ps = by_school[school]
        ans = sum(1 for p in ps if p.get("has_answers"))
        keys = sorted({(p["level"], p["subject"]) for p in ps}, key=lambda k: (LEVELS.index(k[0]), k[1]))
        content = ""
        for level, subject in keys:
            sp = [p for p in ps if (p["level"], p["subject"]) == (level, subject)]
            content += (f'<div class="group"><h2>{e(level)} {e(subject)}</h2>'
                        f'{table(sp, False, lambda p: dict(level=p["level"], subject=p["subject"], type=p["category"], year=p["year"], school=p["school"]))}</div>')
        listing = ", ".join(f"{l} {s}" for l, s in keys[:6]) + ("…" if len(keys) > 6 else "")
        written.append(page(tpl, file=school_file(school),
            title=f"{school} Past Year Papers | Tutelle",
            desc=f"{plural(len(ps), 'free past year paper')} from {school}, {years(ps)}: {listing}. {ans} with answers.",
            h1=f"{school} past year papers",
            lede=f"Papers from {school}, sorted by level and subject. Free for parents.",
            crumbs=[home, browse, (school, school_file(school))], content=content,
            side=side_links("Same subjects, other schools", [(f"{l} {s}", subject_file(l, s)) for l, s in keys]),
            open_link=open_url(school=school), items=[f'{p["year"]} {p["level"]} {p["subject"]} {p["title"]}' for p in ps], fact_html=facts(ps)))

    # the index of everything
    content = '<div class="group"><h2>By level and subject</h2>'
    for grp, lv in (("Primary", LEVELS[:6]), ("Secondary", LEVELS[6:11]), ("Junior college", LEVELS[11:])):
        rows = [k for k in ls_keys if k[0] in lv]
        if not rows:
            continue
        content += f'<h3 style="font-size:16px;margin:16px 0 6px">{grp}</h3><div class="cols3">'
        content += "".join(f'<a href="{subject_file(l, s)}">{e(l)} {e(s)} <span class="muted">({len(by_ls[(l, s)])})</span></a>' for l, s in rows)
        content += "</div>"
    content += '</div><div class="group"><h2>By school</h2><div class="cols3">'
    content += "".join(f'<a href="{school_file(s)}">{e(s)} <span class="muted">({len(by_school[s])})</span></a>' for s in sorted(by_school))
    content += "</div></div>"
    written.append(page(tpl, file="past-papers.html",
        title="Free Past Year Exam Papers by School, Level and Subject | Tutelle",
        desc=f"{len(papers)} free past year papers from {len(by_school)} Singapore schools, Primary to JC: exam papers, worksheets and quizzes, most with answers.",
        h1="Past year papers by level, subject and school",
        lede="Browse the library, then open any paper free after a one-time sign-up. Secondary papers are labelled G1, G2 or G3, the subject levels that replaced N(T), N(A) and Express from 2024.",
        crumbs=[home, browse], content=content, side="", open_link="papers.html",
        items=[f"{l} {s}" for l, s in ls_keys], fact_html=facts(papers)))

    # remove pages for subjects or schools that no longer have papers
    keep = set(written)
    for f in os.listdir(ROOT):
        if f.startswith("past-papers") and f.endswith(".html") and f not in keep:
            os.remove(os.path.join(ROOT, f))

    today = datetime.date.today().isoformat()
    urls = [p for p in STATIC_PAGES if os.path.exists(os.path.join(ROOT, p))] + sorted(keep)
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"  <url><loc>{e(SITE + '/' + (u[:-5] if u != 'index.html' else ''))}</loc><lastmod>{today}</lastmod></url>" for u in urls]
    sm.append("</urlset>")
    open(os.path.join(ROOT, "sitemap.xml"), "w").write("\n".join(sm) + "\n")
    open(os.path.join(ROOT, "robots.txt"), "w").write(f"User-agent: *\nDisallow: /tools/\nSitemap: {SITE}/sitemap.xml\n")
    print(f"wrote {len(written)} browse pages from {len(papers)} papers")


if __name__ == "__main__":
    sys.exit(main())
