# Advanced search proposal — 14 October 2026

Requested: phonetic search inside Advanced Search, part-of-speech limits, and a
clearer interface. Preserve the approved dark blue palette and ?/* wildcards.
Approved by the user and implemented. See README.md and the test reports for coverage and limits.

## Recommended layout

Keep one main query field and a compact header instead of the large introductory
banner. Put an Advanced Search disclosure immediately below the field. The
expanded panel groups controls into Search method, Word properties, and Usage.
Search method offers headwords/patterns, definitions/ideas, quotations, exact
rhymes, near rhymes, and similar pronunciation. Only sound modes show sound
controls. Keep active filters visible as removable chips when Advanced is closed.
Keep results beside the selected entry on desktop and stacked on smaller screens.

Word properties include part of speech (any, noun, verb, adjective, adverb,
pronoun, preposition, conjunction, interjection, affix, phrase, or unlabelled),
plus optional syllable count and stress pattern for phonetic modes. Mixed
classes can match each explicitly recorded category. Unknown grammar must not
be guessed. Subentries use their own recorded grammar where available rather
than being classified only by their parent entry. Literary and obsolete/rare/
dialectal filters remain available and combine with the grammatical limits.

An always-visible filter sidebar makes intensive research faster but gives
simple lookup more visual complexity. A separate sound-search page offers more
space but interrupts movement between meanings and sounds. The collapsible
panel is recommended because all modes can share a query and persistent filters.

## Phonetic behavior and evidence

Enter a known word; show its recorded pronunciation alternatives and let the
user choose one. Also permit IPA input as an explicitly selected input type.
Exact rhymes compare the final stressed vowel and following phonemes where
stress is recorded; monosyllabic words can use their single vowel nucleus.
Multi-syllabic forms without sufficient stress evidence must not silently be
classified as exact rhymes. Near rhymes and similar pronunciation use separately
labelled approximate rankings. Every result shows the pronunciation used and
why it matched. Ordinary spelling is never substituted for missing pronunciation.

Index recorded pronunciation alternatives locally. Accept validated phoneme
sequences, preserving optional segments and unresolved notation as explicit
coverage limits. Do not convert phrases such as 'see below' into sounds. Use
vowel nuclei for approximate syllable counts and recorded stress for stress
patterns. Irregular or uncertain representations should be excluded from strict
filters and remain documented, rather than assigned fabricated properties.

The current database contains 291,588 entries, of which 130,769 have a nonempty
pronunciation field. Some fields contain notes or variants requiring further
validation. Part-of-speech headers are absent on 162,215 entries; coverage of
unlabelled grammar must remain visible. Pronunciations of linked variants may
be inherited only when a unique compatible reference can be established and
must be labelled as inherited; that extension is not required for the first
implementation.

## Implementation and verification

Add an independently built pronunciation and grammar index, leaving raw source
text intact. Integrate bounded sound queries and consistent part-of-speech
filters into the read-only API; bookmarks retain mode, chosen pronunciation,
and all active filters. Invalid IPA and unsupported stress patterns produce
clear errors. Ambiguous input words require pronunciation selection instead of
arbitrary selection.

Validate rhymes such as light/night, cat/bat, and nation/station; validate
read/red versus read/reed using recorded alternatives. Test non-rhymes,
polysyllabic stress, optional rhotic notation, missing pronunciation, uncertain
symbols, mixed grammar, subentry grammar and combined filters. Compare indexed
rhyming matches against a finite independent phoneme oracle, then load-test
sound and wildcard searches together. Verify the redesigned UI on desktop and
phone screens and retain a screenshot and results report.
