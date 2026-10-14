# Private OED research server

Approved 14 October 2026. Audience: the owner, on localhost or a private network.

Recover and validate the disc corpus; keep original SGML and block/source offsets.
Import entries, nested senses, variants, quotations and explicit references into
SQLite. Preserve unfamiliar entities explicitly. Serve a local browser interface
and HTTP API using Python's standard library. No cloud publication or external AI.

Explore connections by selected sense: explicit references first, then inferred
shared definition terms with explanations. Offer reverse-definition, literary,
and obscure-word discovery. Labels come from the corpus; similarity is not a
claim of synonymy. Etymological connections are offered only when a reference in
an etymology can be identified. No inferred antonyms or fabricated dates.

Implementation sequence:
1. Decode every block with bounds checks; retain raw SGML and block manifest.
2. Inventory markup/entities and implement a tolerant structure parser.
3. Import entries/senses/references and separate definition full-text indexes.
4. Implement bounded searches, related-sense ranking and local HTTP service.
5. Build readable, responsive UI with source evidence and sense selection.
6. Validate extraction continuity, parsing, headwords, references, discovery,
   API errors, and browser interactions; document launching and private access.
