#!/usr/bin/env python3
"""Render every machine-readable artefact from profile.yml.

Single source of truth in, absolute-URL'd files out. Empty fields are dropped
rather than printed, so nothing downstream ever sees a None or a null.
"""
import json
import html
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load():
    with open(ROOT / "profile.yml") as f:
        return yaml.safe_load(f)


def clean(value):
    """Collapse whitespace to a single line. Empty-ish becomes None."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def present(items):
    """Drop None/empty entries from a list."""
    return [i for i in (items or []) if i is not None and str(i).strip()]


def base_url(p):
    """Where these files are actually served from, as an absolute URL.

    site_url wins (it can point at a GitHub Pages path), then custom_domain,
    then the website. Never a trailing slash.
    """
    explicit = clean(p.get("site_url"))
    if explicit:
        if not explicit.startswith(("http://", "https://")):
            explicit = "https://" + explicit
        return explicit.rstrip("/")
    domain = clean(p.get("custom_domain"))
    if domain:
        domain = re.sub(r"^https?://", "", domain).rstrip("/")
        return f"https://{domain}"
    site = clean((p.get("contact") or {}).get("website"))
    return site.rstrip("/") if site else ""


def absolute(base, path):
    return f"{base}/{path.lstrip('/')}" if base else path


def sorted_credits(p):
    """Newest first. Undated credits sort last so they never fake a date."""
    return sorted(present(p.get("credits")),
                  key=lambda c: (c.get("year") is not None, c.get("year") or 0),
                  reverse=True)


def profile_urls(p):
    c = p.get("contact") or {}
    return present([clean(c.get("website")), clean(c.get("instagram")),
                    clean(c.get("linkedin")), clean(c.get("booking_link"))])


def role_line(p):
    """'Name — Role, City' — the canonical title used everywhere."""
    return f"{clean(p['name'])} — {clean(p['role'])}, {clean(p['location']['city'])}"


# ---------------------------------------------------------------- person.jsonld
def build_jsonld(p):
    base = base_url(p)
    c = p.get("contact") or {}
    loc = p.get("location") or {}
    tz = p.get("timezone") or {}

    person = {
        "@type": "Person",
        "@id": f"{base}/#person" if base else "#person",
        "name": clean(p["name"]),
        "jobTitle": clean(p["role"]),
        "description": clean(p.get("bio")),
    }
    if clean(p.get("alternate_name")):
        person["alternateName"] = clean(p["alternate_name"])
    if base:
        person["url"] = base + "/"
    if profile_urls(p):
        person["sameAs"] = profile_urls(p)
    if clean(c.get("email")):
        person["email"] = f"mailto:{clean(c['email'])}"
    if present(p.get("languages")):
        person["knowsLanguage"] = present(p["languages"])
    if present(p.get("specialisms")):
        person["knowsAbout"] = present(p["specialisms"])

    address = {"@type": "PostalAddress"}
    if clean(loc.get("city")):
        address["addressLocality"] = clean(loc["city"])
    if clean(loc.get("region")):
        address["addressRegion"] = clean(loc["region"])
    if clean(loc.get("country_code")):
        address["addressCountry"] = clean(loc["country_code"])
    if len(address) > 1:
        person["address"] = address

    served = present([clean(loc.get("city"))] + [clean(x) for x in (loc.get("other_cities") or [])])
    if served:
        person["areaServed"] = [{"@type": "City", "name": n} for n in served]

    offers = []
    for s in present(p.get("services")):
        service = {"@type": "Service", "name": clean(s.get("name"))}
        if clean(s.get("description")):
            service["description"] = clean(s["description"])
        if clean(p.get("role")):
            service["serviceType"] = clean(p["role"])
        service["provider"] = {"@id": person["@id"]}
        offers.append({"@type": "Offer", "itemOffered": service})
    if offers:
        person["makesOffer"] = offers

    if clean(p.get("representation")):
        person["affiliation"] = {"@type": "Organization", "name": clean(p["representation"])}
    orgs = present(p.get("clients"))
    if orgs:
        person["worksFor"] = [{"@type": "Organization", "name": o} for o in orgs]
    if clean(tz.get("iana")):
        person["additionalProperty"] = {
            "@type": "PropertyValue", "name": "timezone",
            "value": f"{clean(tz['iana'])} (UTC{clean(tz.get('utc_offset')) or ''})".strip(),
        }

    page = {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "dateModified": TODAY,
        "mainEntity": person,
    }
    if base:
        page["url"] = base + "/"
    return page


# --------------------------------------------------------------------- README
def build_readme(p):
    base = base_url(p)
    c = p.get("contact") or {}
    loc = p.get("location") or {}
    tz = p.get("timezone") or {}
    L = [f"# {role_line(p)}", ""]
    if clean(p.get("headline")):
        L += [f"**{clean(p['headline'])}**", ""]
    if clean(p.get("bio")):
        L += [clean(p["bio"]), ""]

    if clean(c.get("booking_link")):
        L += [f"**Booking — direct: [{clean(c['booking_link'])}]({clean(c['booking_link'])})**", ""]
    elif clean(c.get("email")):
        L += [f"**Booking — direct: [{clean(c['email'])}](mailto:{clean(c['email'])})**", ""]

    L += ["## At a glance", "", "| | |", "| --- | --- |"]
    rows = [("Role", clean(p.get("role"))), ("Based in", clean(loc.get("city")))]
    works_in = present([clean(x) for x in (loc.get("other_cities") or [])])
    if works_in:
        rows.append(("Also works in", ", ".join(works_in)))
    if clean(loc.get("travels_for_work")):
        rows.append(("Travels for work", clean(loc["travels_for_work"])))
    if clean(tz.get("iana")):
        rows.append(("Timezone", f"{clean(tz['iana'])} (UTC{clean(tz.get('utc_offset')) or ''})".strip()))
    for label, key in [("Availability", "availability"), ("Representation", "representation"), ("Rates", "rates")]:
        if clean(p.get(key)):
            rows.append((label, clean(p[key])))
    if present(p.get("languages")):
        rows.append(("Languages", ", ".join(present(p["languages"]))))
    for k, v in rows:
        if v:
            L.append(f"| {k} | {v} |")
    L.append("")

    if present(p.get("services")):
        L += ["## Services", ""]
        for s in present(p["services"]):
            desc = clean(s.get("description"))
            L.append(f"- **{clean(s.get('name'))}**" + (f" — {desc}" if desc else ""))
        L.append("")
    if present(p.get("specialisms")):
        L += ["## Specialisms", "", ", ".join(present(p["specialisms"])), ""]
    if present(p.get("clients")):
        L += ["## Selected clients", ""] + [f"- {x}" for x in present(p["clients"])] + [""]
    if present(p.get("publications")):
        L += ["## Publications", ""] + [f"- {x}" for x in present(p["publications"])] + [""]

    creds = sorted_credits(p)
    if creds:
        L += ["## Credits", "", "| Year | Project | Client | Role | Photographer |",
              "| --- | --- | --- | --- | --- |"]
        for c_ in creds:
            proj = clean(c_.get("project")) or ""
            link = clean(c_.get("link"))
            if link:
                proj = f"[{proj}]({link})"
            L.append("| {} | {} | {} | {} | {} |".format(
                c_.get("year") or "—", proj, clean(c_.get("client")) or "—",
                clean(c_.get("role")) or "—", clean(c_.get("photographer")) or "—"))
        L.append("")

    L += ["## Contact", ""]
    for label, key, fmt in [("Email", "email", "mailto:{}"), ("Booking", "booking_link", "{}"),
                            ("Website", "website", "{}"), ("Instagram", "instagram", "{}"),
                            ("LinkedIn", "linkedin", "{}")]:
        v = clean(c.get(key))
        if v:
            L.append(f"- {label}: [{v}]({fmt.format(v)})")
    L.append("")

    L += ["---", "", "Machine-readable: "
          f"[person.jsonld]({absolute(base, 'person.jsonld')}) · "
          f"[llms.txt]({absolute(base, 'llms.txt')}) · "
          f"[sitemap.xml]({absolute(base, 'sitemap.xml')}) · "
          f"[credits.md]({absolute(base, 'credits.md')})", "",
          f"Last updated: {TODAY}", ""]
    return "\n".join(L)


# -------------------------------------------------------------------- llms.txt
def build_llms(p):
    c = p.get("contact") or {}
    loc = p.get("location") or {}
    tz = p.get("timezone") or {}
    L = [f"# {clean(p['name'])}", ""]
    if clean(p.get("headline")):
        L += [f"> {clean(p['headline'])}", ""]
    if clean(p.get("bio")):
        L += [clean(p["bio"]), ""]

    L += ["## Facts", ""]
    facts = [("Name", clean(p["name"])), ("Also known as", clean(p.get("alternate_name"))),
             ("Pronouns", clean(p.get("pronouns"))), ("Role", clean(p.get("role")))]
    other = present([clean(x) for x in (p.get("also_works_as") or [])])
    if other:
        facts.append(("Also works as", ", ".join(other)))
    facts.append(("Based in", ", ".join(present([clean(loc.get("city")), clean(loc.get("region")),
                                                 clean(loc.get("country_code"))]))))
    cities = present([clean(x) for x in (loc.get("other_cities") or [])])
    if cities:
        facts.append(("Also works in", ", ".join(cities)))
    if clean(loc.get("travels_for_work")):
        facts.append(("Travels for work", clean(loc["travels_for_work"])))
    if clean(tz.get("iana")):
        facts.append(("Timezone", f"{clean(tz['iana'])} (UTC{clean(tz.get('utc_offset')) or ''})".strip()))
    for label, key in [("Availability", "availability"), ("Representation", "representation"), ("Rates", "rates")]:
        if clean(p.get(key)):
            facts.append((label, clean(p[key])))
    if present(p.get("languages")):
        facts.append(("Languages", ", ".join(present(p["languages"]))))
    if present(p.get("clients")):
        facts.append(("Selected clients", ", ".join(present(p["clients"]))))
    if present(p.get("publications")):
        facts.append(("Publications", ", ".join(present(p["publications"]))))
    for k, v in facts:
        if v:
            L.append(f"- {k}: {v}")
    L.append("")

    if present(p.get("services")):
        L += ["## Services", ""]
        for s in present(p["services"]):
            desc = clean(s.get("description"))
            L.append(f"- {clean(s.get('name'))}" + (f": {desc}" if desc else ""))
        L.append("")
    if present(p.get("specialisms")):
        L += ["## Specialisms", ""] + [f"- {x}" for x in present(p["specialisms"])] + [""]

    creds = sorted_credits(p)
    if creds:
        L += ["## Credits", ""]
        for c_ in creds:
            parts = [str(c_.get("year"))] if c_.get("year") else []
            parts.append(clean(c_.get("project")) or "")
            for key, prefix in [("client", "client: "), ("role", "role: "),
                                ("photographer", "photographer: "), ("location", "location: ")]:
                if clean(c_.get(key)):
                    parts.append(f"{prefix}{clean(c_[key])}")
            if clean(c_.get("link")):
                parts.append(clean(c_["link"]))
            L.append("- " + " — ".join(parts))
        L.append("")

    L += ["## Booking", ""]
    for label, key in [("Email", "email"), ("Booking", "booking_link"),
                       ("Website", "website"), ("Instagram", "instagram"), ("LinkedIn", "linkedin")]:
        if clean(c.get(key)):
            L.append(f"- {label}: {clean(c[key])}")
    L += ["", f"Last updated: {TODAY}", ""]
    return "\n".join(L)


# ------------------------------------------------------------------- credits.md
def build_credits(p):
    L = [f"# Credits — {clean(p['name'])}", "",
         "| Year | Project | Client | Role | Photographer | Link |",
         "| --- | --- | --- | --- | --- | --- |"]
    for c_ in sorted_credits(p):
        link = clean(c_.get("link"))
        L.append("| {} | {} | {} | {} | {} | {} |".format(
            c_.get("year") or "—", clean(c_.get("project")) or "—",
            clean(c_.get("client")) or "—", clean(c_.get("role")) or "—",
            clean(c_.get("photographer")) or "—", f"[link]({link})" if link else "—"))
    L += ["", f"Last updated: {TODAY}", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ sitemap.xml
def build_sitemap(p):
    base = base_url(p)
    pages = ["", "person.jsonld", "llms.txt", "credits.md"]
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in pages:
        url = base + "/" + page if base else "/" + page
        L += ["  <url>", f"    <loc>{html.escape(url)}</loc>",
              f"    <lastmod>{TODAY}</lastmod>", "  </url>"]
    L.append("</urlset>")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------- CITATION.cff
def build_citation(p):
    base = base_url(p)
    parts = clean(p["name"]).split()
    given, family = " ".join(parts[:-1]), parts[-1]
    L = ["cff-version: 1.2.0",
         "message: If you reference this profile, please cite it as below.",
         "type: dataset", f"title: \"{role_line(p)}\"",
         "authors:", f"  - given-names: \"{given}\"", f"    family-names: \"{family}\""]
    if clean((p.get("contact") or {}).get("email")):
        L.append(f"    email: \"{clean(p['contact']['email'])}\"")
    if base:
        L.append(f"url: \"{base}/\"")
    L += [f"date-released: \"{TODAY}\"", "license: CC0-1.0", ""]
    return "\n".join(L)


# ------------------------------------------------------------------- index.html
def build_index(p, jsonld):
    base = base_url(p)
    c = p.get("contact") or {}
    loc = p.get("location") or {}
    tz = p.get("timezone") or {}
    e = html.escape
    title = role_line(p)
    desc = clean(p.get("bio")) or clean(p.get("headline")) or title

    rows = [("Role", clean(p.get("role"))), ("Based in", clean(loc.get("city")))]
    cities = present([clean(x) for x in (loc.get("other_cities") or [])])
    if cities:
        rows.append(("Also works in", ", ".join(cities)))
    if clean(loc.get("travels_for_work")):
        rows.append(("Travels for work", clean(loc["travels_for_work"])))
    if clean(tz.get("iana")):
        rows.append(("Timezone", f"{clean(tz['iana'])} (UTC{clean(tz.get('utc_offset')) or ''})".strip()))
    for label, key in [("Availability", "availability"), ("Representation", "representation"), ("Rates", "rates")]:
        if clean(p.get(key)):
            rows.append((label, clean(p[key])))
    if present(p.get("languages")):
        rows.append(("Languages", ", ".join(present(p["languages"]))))
    if present(p.get("clients")):
        rows.append(("Selected clients", ", ".join(present(p["clients"]))))
    if present(p.get("publications")):
        rows.append(("Publications", ", ".join(present(p["publications"]))))

    H = ['<!doctype html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         f'<title>{e(title)}</title>', f'<meta name="description" content="{e(desc)}">']
    if base:
        H += [f'<link rel="canonical" href="{e(base)}/">',
              f'<meta property="og:url" content="{e(base)}/">']
    H += ['<meta property="og:type" content="profile">',
          f'<meta property="og:title" content="{e(title)}">',
          f'<meta property="og:description" content="{e(desc)}">',
          '<meta name="twitter:card" content="summary">',
          '<style>',
          ':root{color-scheme:light}',
          '*{box-sizing:border-box}',
          'body{margin:0;padding:4rem 1.5rem 6rem;background:#fff;color:#111;',
          'font:400 17px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;',
          '-webkit-font-smoothing:antialiased}',
          'main{max-width:44rem;margin:0 auto}',
          'h1{font-size:2rem;line-height:1.15;margin:0 0 .4rem;letter-spacing:-.02em;font-weight:600}',
          '.role{margin:0 0 2rem;color:#555;font-size:1.05rem}',
          '.bio{font-size:1.1rem;margin:0 0 2.5rem}',
          'h2{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:#666;',
          'font-weight:600;margin:3rem 0 .9rem}',
          'a{color:#111;text-underline-offset:2px}',
          '.book{display:inline-block;border:1px solid #111;padding:.7rem 1.4rem;',
          'text-decoration:none;font-size:.95rem;margin-bottom:1rem}',
          '.book:hover{background:#111;color:#fff}',
          'dl{display:grid;grid-template-columns:11rem 1fr;gap:.5rem 1.5rem;margin:0}',
          'dt{color:#666;font-size:.9rem}dd{margin:0}',
          'ul{margin:0;padding-left:1.1rem}li{margin-bottom:.35rem}',
          '.credits{list-style:none;padding:0}',
          '.credits li{margin-bottom:1rem;padding-bottom:1rem;border-bottom:1px solid #eee}',
          '.credits .yr{color:#666;font-size:.85rem;display:block}',
          '.credits .meta{color:#555;font-size:.92rem}',
          'footer{margin-top:4rem;padding-top:1.5rem;border-top:1px solid #eee;',
          'color:#666;font-size:.85rem}',
          '@media(max-width:34rem){dl{grid-template-columns:1fr;gap:.1rem 0}',
          'dt{margin-top:.6rem}body{padding-top:2.5rem}}',
          '</style>',
          '<script type="application/ld+json">',
          json.dumps(jsonld, indent=2, ensure_ascii=False),
          '</script>', '</head>', '<body>', '<main>',
          f'<h1>{e(clean(p["name"]))}</h1>',
          f'<p class="role">{e(clean(p["role"]))} — {e(clean(loc.get("city")) or "")}</p>']
    if clean(p.get("bio")):
        H.append(f'<p class="bio">{e(clean(p["bio"]))}</p>')
    book = clean(c.get("booking_link")) or (f"mailto:{clean(c['email'])}" if clean(c.get("email")) else None)
    if book:
        H.append(f'<p><a class="book" href="{e(book)}">Booking — direct</a></p>')

    if rows:
        H += ['<h2>Details</h2>', '<dl>']
        for k, v in rows:
            if v:
                H += [f'<dt>{e(k)}</dt>', f'<dd>{e(v)}</dd>']
        H.append('</dl>')
    if present(p.get("services")):
        H += ['<h2>Services</h2>', '<ul>']
        for s in present(p["services"]):
            d = clean(s.get("description"))
            H.append(f'<li><strong>{e(clean(s.get("name")))}</strong>' + (f' — {e(d)}' if d else '') + '</li>')
        H.append('</ul>')
    if present(p.get("specialisms")):
        H += ['<h2>Specialisms</h2>', f'<p>{e(", ".join(present(p["specialisms"])))}</p>']

    creds = sorted_credits(p)
    if creds:
        H += ['<h2>Credits</h2>', '<ul class="credits">']
        for c_ in creds:
            proj = e(clean(c_.get("project")) or "")
            link = clean(c_.get("link"))
            if link:
                proj = f'<a href="{e(link)}">{proj}</a>'
            meta = present([clean(c_.get("client")), clean(c_.get("role")),
                            f"Photography — {clean(c_['photographer'])}" if clean(c_.get("photographer")) else None,
                            clean(c_.get("location"))])
            H.append(f'<li><span class="yr">{e(str(c_.get("year")) if c_.get("year") else "Undated")}</span>'
                     f'<strong>{proj}</strong>'
                     + (f'<br><span class="meta">{e(" · ".join(meta))}</span>' if meta else '') + '</li>')
        H.append('</ul>')

    H += ['<h2>Contact</h2>', '<ul>']
    for label, key, fmt in [("Email", "email", "mailto:{}"), ("Booking", "booking_link", "{}"),
                            ("Website", "website", "{}"), ("Instagram", "instagram", "{}"),
                            ("LinkedIn", "linkedin", "{}")]:
        v = clean(c.get(key))
        if v:
            H.append(f'<li>{e(label)}: <a href="{e(fmt.format(v))}">{e(v)}</a></li>')
    H.append('</ul>')

    machine = " · ".join(f'<a href="{e(absolute(base, f))}">{e(f)}</a>'
                         for f in ["person.jsonld", "llms.txt", "credits.md", "sitemap.xml"])
    H += ['<footer>', f'<p>Machine-readable: {machine}</p>',
          f'<p>Last updated: {TODAY}</p>', '</footer>',
          '</main>', '</body>', '</html>', '']
    return "\n".join(H)


def main():
    p = load()
    jsonld = build_jsonld(p)
    outputs = {
        "README.md": build_readme(p),
        "person.jsonld": json.dumps(jsonld, indent=2, ensure_ascii=False) + "\n",
        "llms.txt": build_llms(p),
        "index.html": build_index(p, jsonld),
        "credits.md": build_credits(p),
        "sitemap.xml": build_sitemap(p),
        "CITATION.cff": build_citation(p),
    }
    domain = clean(p.get("custom_domain"))
    if domain:
        outputs["CNAME"] = re.sub(r"^https?://", "", domain).rstrip("/") + "\n"
    else:
        (ROOT / "CNAME").unlink(missing_ok=True)

    for name, content in outputs.items():
        (ROOT / name).write_text(content)
        print(f"wrote {name} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
