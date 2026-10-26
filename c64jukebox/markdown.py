"""The manual docs/HANDBUCH.md as HTML for the "Hilfe" tab - a small Markdown subset, as in the Pico projects:
headings (## / ###), paragraphs, lists (- / 1.), tables, ``` code blocks, `code`, **bold**, *italic*, [links](#x).
Heading ids are "h-" + slug; a link to an unknown section is an error (the tests check the manual with it)."""
import html as htmlmod
import re


def slug(t):
    t = re.sub(r"`|\*", "", t).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def inline(t):
    codes = []

    def keep(m):
        codes.append("<code>%s</code>" % htmlmod.escape(m.group(1), quote=False))
        return "\0%d\0" % (len(codes) - 1)
    t = re.sub(r"`([^`]+)`", keep, t)
    t = htmlmod.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<i>\1</i>", t)

    def link(m):
        href = m.group(2)
        if href.startswith("#"):
            return '<a href="#h-%s" data-h="%s">%s</a>' % (href[1:], href[1:], m.group(1))
        return '<a href="%s" target=_blank rel=noopener>%s</a>' % (href, m.group(1))
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
    return re.sub("\0(\\d+)\0", lambda m: codes[int(m.group(1))], t)


def to_html(md):
    """-> (html, set of section ids)"""
    out, toc, ids = [], [], set()
    lines = md.split("\n")
    i, title = 0, ""

    def cells(line):
        return [c.strip() for c in line.strip().strip("|").split("|")]
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>%s</pre>" % htmlmod.escape("\n".join(lines[i + 1:j]), quote=False))
            i = j + 1
            continue
        m = re.match(r"(#{1,3}) (.*)", line)
        if m:
            lvl, text = len(m.group(1)), m.group(2).strip()
            i += 1
            if lvl == 1:
                title = text
                continue
            hid = slug(text)
            if hid in ids:
                raise ValueError("duplicate heading id " + hid)
            ids.add(hid)
            out.append('<h%d id="h-%s">%s</h%d>' % (lvl, hid, inline(text), lvl))
            if lvl == 2:
                toc.append((hid, text))
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r) for r in rows[2:])
            out.append("<div class=tw><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>"
                       % ("".join("<th>%s</th>" % inline(c) for c in rows[0]), body))
            continue
        m = re.match(r"(- |\d+\. )", line)
        if m:
            tag = "ul" if line.startswith("- ") else "ol"
            first = int(m.group(1)[:-2]) if tag == "ol" else 1
            items = []
            while i < len(lines) and re.match(r"(- |\d+\. )", lines[i]):
                item = re.sub(r"^(- |\d+\. )", "", lines[i])
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
                    item += " " + lines[i].strip()
                    i += 1
                items.append("<li>%s</li>" % inline(item))
            out.append("<%s%s>%s</%s>" % (tag, " start=%d" % first if first > 1 else "", "".join(items), tag))
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"(#|\||```|- |\d+\. )", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(para)))
    body = "".join(out)
    for h in re.findall(r'data-h="([^"]+)"', body):
        if h not in ids:
            raise ValueError("manual: link to unknown section #" + h)
    nav = "<nav class=htoc><b>Inhalt</b><ol>%s</ol></nav>" % "".join(
        '<li><a href="#h-%s" data-h="%s">%s</a></li>' % (h, h, inline(t)) for h, t in toc)
    k = body.find("<h2 id=")
    if k < 0:
        k = len(body)
    return "<h2 class=htitle>%s</h2>%s%s%s" % (inline(title), body[:k], nav, body[k:]), ids
