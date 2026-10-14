"""Tolerant parser for the supplied OED's SGML, preserving unknown entities."""
from dataclasses import dataclass, field
import json
import re
import unicodedata
from pathlib import Path

ENTITIES = json.loads(Path(__file__).with_name('entities.json').read_text())
ENTITY = re.compile(r'&([A-Za-z0-9]+)\.')
TAG = re.compile(r'<(/?)([A-Za-z][A-Za-z0-9]*)([^>]*)>')
SENSE = re.compile(r'^(?:s(?:[0-6]|7a|7n|n|gk)|sub)$')
ATTR = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))')
PHONETIC = str.maketrans({'"':'ˈ','%':'ˌ','&':'æ','3':'ɜ','9':'ø',':':'ː',
                          '@':'ə','A':'ɑ','D':'ð','E':'ɛ','I':'ɪ','N':'ŋ','O':'ɔ',
                          'Q':'ɒ','S':'ʃ','T':'θ','U':'ʊ','V':'ʌ','Z':'ʒ'})
GREEK = str.maketrans(dict(zip('ABGDEZHQIKLMNXOPRSTUFCYWabgdezhqiklmnxoprstufcyw',
                                'ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρστυφχψω')))

@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    offset: int = 0

    def walk(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk(tag)


def parse(raw):
    root = Node('root')
    stack = [root]
    cursor = 0
    issues = []
    for match in TAG.finditer(raw):
        stack[-1].children.append(raw[cursor:match.start()])
        closing, name, attrs = match.groups()
        if closing:
            found = next((i for i in range(len(stack)-1, 0, -1) if stack[i].tag == name), None)
            if found is None:
                issues.append(f'unmatched closing {name} at {match.start()}')
            else:
                if found != len(stack)-1:
                    issues.append(f'implicit closing before {name} at {match.start()}')
                del stack[found:]
        else:
            node = Node(name, {m[0]: next((x for x in m[1:] if x != ''), '') for m in ATTR.findall(attrs)}, offset=match.start())
            stack[-1].children.append(node)
            stack.append(node)
        cursor = match.end()
    stack[-1].children.append(raw[cursor:])
    if len(stack) > 1:
        issues.append('unclosed tags: ' + ', '.join(n.tag for n in stack[1:]))
    return root, issues


def entities(text):
    return ENTITY.sub(lambda m: ENTITIES.get(m[1], f'⟦&{m[1]}.⟧'), text)


def text(node, exclude=frozenset(), exclude_senses=False, phonetic=False, greek=False):
    if isinstance(node, str):
        if phonetic:
            parts = []
            cursor = 0
            for match in ENTITY.finditer(node):
                parts.append(node[cursor:match.start()].translate(PHONETIC))
                parts.append(entities(match.group()))
                cursor = match.end()
            parts.append(node[cursor:].translate(PHONETIC))
            return ''.join(parts)
        mapped = entities(node)
        return mapped.translate(GREEK) if greek else mapped
    if node.tag in exclude or (exclude_senses and SENSE.match(node.tag)):
        return ''
    content = ''.join(text(c, exclude, exclude_senses, phonetic or node.tag == 'ph', greek or node.tag == 'gk') for c in node.children)
    if node.tag in {'p', 'par', 'l', 'q'}:
        return content + '\n'
    return content


def clean(node, **kwargs):
    return re.sub(r'\s+', ' ', text(node, **kwargs)).strip()


def normalize(value, pattern=False):
    value = unicodedata.normalize('NFKD', value.casefold())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[ˈˌ†‡\s]+' if pattern else r'[ˈˌ†‡*\s]+', '', value).strip()


def headword_text(node):
    # Superscript homonym markers are metadata, not lookup characters.
    # Ordinary digits (as in A1) remain part of a headword.
    return clean(node, exclude={'su','hm'})


def words(value):
    return re.findall(r"[a-z]{3,}", value.lower())

LABELS = {'obs':'Obsolete', 'rare':'Rare', 'arch':'Archaic'}
OBSCURE = re.compile(r'\b(?:obsolete|obs\.|rare|archaic|arch\.|dialect|dial\.|sc\. |scottish|provincial|prov\.)', re.I)
LITERARY = re.compile(r'\b(?:rhetoric(?:al)?|prosody|poet(?:ic|ical|ry)?|literary|literature|poem|verse|stanza|metre|meter|trope|figurative)\b|\b(?:rhet|poet|pros|fig)\.|figure of speech', re.I)


def own_labels(node):
    result = []
    if status := node.attrs.get('st'):
        result.append(LABELS.get(status, 'Status: '+status))
    # Usage labels in nested quotations must not label the definition.
    def visit(n):
        if isinstance(n, str) or n.tag in {'q','qp','pqp','et','etym','vfl'}:
            return
        if n is not node and SENSE.match(n.tag):
            return
        if n.tag == 'la':
            result.append(clean(n))
        for c in n.children:
            visit(c)
    if node.tag in {'e','ve'}:
        # Labels on historical spelling variants or later editorial blocks
        # must not classify every sense of the main word.
        for child in node.children:
            if isinstance(child, Node) and (SENSE.match(child.tag) or child.tag in {'q','qp','pqp','db','cb'}):
                break
            visit(child)
    else:
        visit(node)
    return list(dict.fromkeys(x for x in result if x))


def entry_data(raw, source_offset):
    tree, issues = parse(raw)
    entry = next(n for n in tree.children if isinstance(n, Node))
    group = next(entry.walk('hg'), entry)
    head = next(group.walk('hw'), None)
    if head is None:
        raise ValueError(f'No headword at {source_offset}')
    headword = headword_text(head)
    headwords = list(dict.fromkeys(headword_text(n) for n in group.walk('hw')))
    # Header grammar must not inherit the part of speech of an etymological
    # cross-reference or a subentry.
    pos = [clean(n, exclude={'hm'}) for n in group.walk('ps')]
    for child in entry.children:
        if isinstance(child, Node):
            if child.tag in {'et','etym','vfl','qp','q'} or SENSE.match(child.tag):
                break
            if child.tag=='ps':
                pos.append(clean(child, exclude={'hm'}))
    pos = list(dict.fromkeys(pos))
    homonym = list(dict.fromkeys([clean(n) for n in group.walk('hm')] +
                                [clean(n) for n in head.walk('su') if clean(n).isdigit()]))
    pronunciation = [clean(n) for n in group.walk('pr')]
    base_labels = own_labels(entry)
    senses = []
    def collect(n, parent=None, inherited=None):
        labels = list(dict.fromkeys((inherited or []) + own_labels(n)))
        if SENSE.match(n.tag):
            definition = clean(Node('definition', children=n.children),
                               exclude={'qp','pqp','q','et','etym','hg','pr','vfl'}, exclude_senses=True)
            sid = f'{source_offset}:{n.offset}'
            if definition:
                senses.append({'id': sid, 'parent_id': parent, 'tag': n.tag,
                               'number': n.attrs.get('num', ''), 'definition': definition,
                               'labels': labels, 'offset': n.offset,
                               'headword': headword_text(next(n.walk('bl'), head)) if n.tag == 'sub' else headword})
                parent = sid
        for child in n.children:
            if isinstance(child, Node) and child.tag not in {'q','qp','pqp','et','etym'}:
                collect(child, parent, labels)
    collect(entry, inherited=base_labels)
    if not senses:
        definition = clean(entry, exclude={'hg','et','etym','qp','pqp','q','pr','vfl'})
        senses.append({'id': f'{source_offset}:0', 'parent_id': None, 'tag':'entry',
                       'number':'', 'definition':definition, 'labels':base_labels, 'offset':0})
    refs = []
    def references(n, context='entry', sid=None):
        if n.tag in {'et','etym'}:
            context='etymology'
        if n.tag in {'q','qp','pqp'}:
            context='quotation'
        if SENSE.match(n.tag):
            sid = f'{source_offset}:{n.offset}'
        if n.tag == 'xr':
            for target in n.walk('x'):
                refs.append({'target':headword_text(target), 'text':clean(n), 'context':context,
                             'sense_id':sid, 'pos':' '.join(clean(x) for x in n.walk('ps')),
                             'homonym':' '.join(clean(x) for x in n.walk('hm')) or ' '.join(clean(x) for x in target.walk('su')),
                             'target_sense':' '.join(clean(x) for x in n.walk('xs'))})
        for child in n.children:
            if isinstance(child, Node):
                references(child,context,sid)
    references(entry)
    return {'headword':headword, 'headwords':headwords, 'norm':normalize(headword), 'kind':entry.tag,
            'pos':' '.join(pos), 'homonym':' '.join(homonym),
            'pronunciation':' / '.join(pronunciation), 'labels':base_labels,
            'senses':senses, 'references':refs, 'issues':issues, 'tree':entry}
