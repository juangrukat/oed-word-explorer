"""Source context for subentries, without manufacturing missing definitions."""
import re
from .markup import Node, clean, normalize


def contexts(tree, senses):
    parents={}
    for parent in tree.walk():
        for child in parent.children:
            if isinstance(child,Node):parents[id(child)]=parent
    result={}
    for sense in senses:
        if sense['tag']!='sub':continue
        node=next((n for n in tree.walk('sub') if n.offset==sense['offset']),None)
        if node is None:continue
        word=normalize(sense['headword'])
        quotes=list(node.walk('q'))
        container=node
        # Check only immediately following quotation groups, through the
        # derivative block wrapper. Require an exact word mention in each quote.
        while id(container) in parents:
            parent=parents[id(container)]
            siblings=[n for n in parent.children if isinstance(n,Node)]
            index=next(i for i,n in enumerate(siblings) if n is container)
            for following in siblings[index+1:]:
                if following.tag not in {'qp','pqp','q'}:break
                for q in following.walk('q'):
                    qt=' '.join(clean(n) for n in q.walk('qt'))
                    if word in {normalize(w) for w in re.findall(r"[\wˈˌ'-]+",qt)}:quotes.append(q)
            if parent.tag!='db':break
            container=parent
        deduplicated={q.offset:clean(q) for q in quotes}
        parent_sense=next((s for s in senses if s['id']==sense['parent_id']),None)
        if parent_sense is None:parent_sense=next((s for s in senses if s['tag']!='sub'),None)
        result[sense['id']]={
            'definition_missing':normalize(sense['definition'].strip(' .,:;'))==word,
            'parent_definition':parent_sense['definition'] if parent_sense else '',
            'quotations':list(deduplicated.values()),
            'note':'This word is listed within the parent entry, rather than as a separate full entry.'}
    return result
