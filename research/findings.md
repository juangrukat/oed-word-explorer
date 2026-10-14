# OED Second Edition disc investigation — 14 October 2026

Purpose: recover this specific disc for a standalone server used locally or on
the owner's private network, with improved related-word exploration.

## Observed evidence

- Source: `Oxford English Dictionary (Second Edition).iso`.
  ISO SHA-256: `da5204dfae2f6edababedbeb0a67dc70e13eb40d347cf7ee6345f3a75c3d3cc1`.
- Read-only ISO9660 mount has volume label `OED2` and two files:
  `SETUP.EXE` (991,265 bytes) and `OED2.DAT` (635,400,192 bytes).
- Installer is an NE executable for Windows 3.x. Its DOS message asks for
  Windows 3.1 or higher; strings identify Wise installation components.
  Nothing from the installer was executed.
- REA `open_binary` rejected the installer as an unsupported NE image.
  No REA native decompilation or Evidence ID was produced. Further evidence
  comes from direct byte inspection and the bounded local probe.
- Database SHA-1: `626fab18cc9a25feafcf4080901c834e3ca05af7`, exactly matching
  the database documented by the historical Plan 9 decoder.
- Big-endian pointers at database offsets 0 and 0x40 identify the entry region:
  first pointer plus 0x8000 = 0x16709000; end = 0x25bb1000 (exclusive).
  It contains 7,829 blocks of 32,768 bytes.
- Every block passes the probe's basic header bounds checks. These checks do
  not establish that every compressed payload is valid.
- Six sampled blocks (0, 1, 1957, 3914, 5871, 7828) decode successfully using
  the published dictionary-symbol/prefix-code algorithm. The local probe
  validates bounds rather than reproducing the historical C memory behavior.
  Each sample and its SHA-256 are retained in `samples/probe.json`.
- Decoded content includes SGML-like headwords, pronunciation, grammatical
  tags, numbered sense hierarchies, quotations, dates, etymologies, and
  cross-references. Examples include `<hw>`, `<ps>`, `<s1>`, `<qt>`, `<qd>`,
  `<etym>`, and `<xr>`. Some entry openings have unquoted attributes such as
  `<e st=obs>`. This is not directly parseable as ordinary XML.
- Special entities use legacy forms such as `&th.` and `&sm.`. Pronunciation
  text also uses a legacy representation. Preserve raw content until mappings
  are verified. Entry fragments cross compression block boundaries.

Sources consulted:

- https://9p.io/sources/contrib/tristan/oed/README
- https://9p.io/sources/contrib/tristan/oed/decompress.c

Reproduce the bounded probe while the disc is mounted:

```sh
python3 research/probe_database.py /Volumes/OED2/OED2.DAT --output research/samples
```

## Inferences and unresolved questions

The successful samples and exact checksum match strongly support recoverability
without running Windows. Complete extraction has not yet been validated, and
the heuristic six-zero block terminator needs corpus-wide checks. The exact
meaning of every header field, entity, and SGML tag remains unverified.

There is no established evidence yet of a separate thesaurus dataset on this
disc. A cross-reference is not necessarily a synonym. Other database regions,
the installer payload, and the original application's search behavior have not
been fully examined. No claims about original runtime equivalence are made.

## Proposed server design for review

Recommended approach: extract and validate the corpus once, preserve the raw
SGML, and import structured entries and senses into SQLite with full-text
indexes. Serve a browser interface and HTTP API from a modern native process,
with no CD or legacy Windows dependency after import. Package application code
separately from locally imported dictionary content. Bind to localhost by
default; private-network access should be an explicit configuration.

Alternative 1: decode database blocks on demand. This preserves the original
database layout but makes full-text and sense-level search harder.

Alternative 2: emulate Windows and wrap the original reader. This may help
establish original behavior, but retains a large runtime dependency and limits
new search features. It is less suitable as the final server.

First milestone: decode all blocks, reconstruct entry boundaries including
attributes, inventory markup/entities, report every decoding or parsing error,
and compare representative reconstructed entries against retained raw data.
Stable entry/sense identifiers should derive from source positions, with
provenance back to database blocks. Retain unfamiliar tags and unresolved
entities explicitly instead of silently discarding them.

Second milestone: headword, spelling-variant, wildcard, and full-text search;
readable sense hierarchy; quotations; and resolved cross-reference navigation.
Full-text indexing should separate definitions from quotations so historical
examples do not dominate meaning-based queries. Verify entry counts, corpus
boundaries, entity handling, cross-reference ambiguity, and searches for known
entries before declaring import complete.

Third milestone: sense-level related-word exploration. Start with reverse
definition search and explicit references. Add optional semantic ranking after
the importer is sound, using locally computed embeddings if desired. Show why
each suggestion appeared and distinguish inferred similarity from an explicit
relationship. Support grammatical and obsolete-word filters, and date filters
only where their meaning is supported by the source. Do not equate quotation
dates with the full lifespan of a sense, or invent synonym/antonym relations.

This proposal was approved in the subsequent conversation. The initial
investigation above predates implementation.

## Completed implementation

The private server is implemented in `oed/`, with its browser interface in
`web/`. See `../README.md` for launching, migration and API instructions.

All 7,829 blocks decoded with bounds checks and continuous logical positions.
The recovered corpus contains 545,293,803 bytes and has SHA-256
`4795d7a91c8e9096514c5d15df0aa5150c5b3007efe1d9494c34bd65dd1df817`.
The production decoder also handles full physical blocks ending at a complete
code or an all-zero prefix, without reading outside their allocation. Regression
tests cover the three observed physical-end cases.

Import produced 291,588 entries (231,155 main and 60,433 variant entries),
458,800 searchable headwords/subentry forms, 777,030 senses/subentries,
476,587 named references, and 2,435,558 quotations. All opening/closing entry
counts match; no content remains outside entry records; no structural parsing
issues were reported. Both full-text indexes and SQLite integrity checks passed.

The reader distinguishes header usage labels from spelling-variant labels,
retains superscript homonym numbers separately from canonical headwords, and
excludes quotation and etymology text from definition similarity. Multiword
idea search can expand concepts using cited dictionary definitions, with
supporting senses shown explicitly when a match spans senses.

Eleven automated tests pass. Corpus-backed acceptance checks verify 22 entry
digests, A-to-Z lookup, literary discovery, obscure-word discovery from a
selected meaning, and the usage-label regression. Desktop and phone browser
checks passed with no console errors. `../docs/validation.json` retains results.

465,193 of 476,587 named references have exact canonical headword matches;
homonym and sense ambiguity still requires inspection. Relative references are
preserved in source text. Unknown specialist character entities remain visibly
marked, and original markup is available per entry. No independent comparison
with the original Windows application's execution was performed.

The original ISO was ejected after import. The server continues to serve the
local imported corpus independently. No public or cloud deployment was made.
