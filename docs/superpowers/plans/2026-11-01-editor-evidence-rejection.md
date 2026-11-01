# Editor evidence rejection fix

Use Superpowers systematic-debugging, TDD and inline execution, with one final independent review. The user's failed edit is continuation of the authorised Firecrawl editor implementation.

## Evidence and scope

The original failure saved only a generic message; the generated response/tool results were discarded. The user's exact request was replayed through the real Codex/Firecrawl transport on a temporary copy. Six calls found/read Tesco, Arriva and LNER pages. The response passed validation, but contained three supported `property.nearby_places` rows; the existing gap deduplication silently retained only the first (shops), losing both transport findings. This is demonstrated; the original rejection's exact cause remains unknown.

Captured replay: `/tmp/property-editor-live-repro/research.json`. Baseline: `/tmp/property-editor-rejection-baseline-2026-11-01`.

## Minimal changes

- [x] Validate locality entries individually, then combine their text/source IDs into the existing single nearby-places field. Preserve per-source support and the 65-word presentation budget. Conflicting duplicate non-locality findings must fail clearly.
- [x] Return specific validation feedback. Allow one tools-disabled correction using only the already-read pages and existing comparison candidates; revalidate identically. No new research loop/search, fallback facts or relaxed citation checks. Limit correction to 60 seconds.
- [x] Save the last failed edit's request, response/tool results and validation diagnostics separately from report history. Preserve prior inputs, evidence, revision and all PDFs on failure.
- [x] Test the captured multi-source behavior, correction success/failure, bounded attempts, failure audit and full suite. Replay captured live evidence through the corrected application and render a temporary ten-page PDF. Do not change the user's saved report or restart their server.

## Review focus

- Every merged locality clause retains its own actually-read source and quote; invalid fragments must not sneak through aggregation.
- Repair uses only captured evidence, cannot change explicit inputs/presentation, and stops after one attempt.
- Empty/failed repairs must not claim success or damage the prior report.
- Sources and merged text fit existing PDF constraints; the original validation rules for other fields remain intact.
- Failure diagnostics remain local and preserve the true final failed response.

## Ledger

- Original error cannot be precisely attributed because diagnostics were discarded. Live replay established successful Firecrawl access and the duplicate-topic loss described above. No claim that a quota or missing webpage caused the user's first failure.
- Seven initial regressions reproduced all three gaps: silent duplicate-topic loss, absent correction handling and discarded failed-edit diagnostics. After implementation, focused editor suites passed 21 tests. A further RED→GREEN regression ensures a malformed correction preserves its actual final response rather than the original one.
- Captured live evidence replay now retains all three independently quoted clauses (43 words, three source references). A temporary PDF generated under `/tmp/property-editor-live-repro/preview` remains ten pages and contains Tesco, Arriva and LNER. No saved report files modified; no second live search performed.
- Initial full suite: 124 tests passed in 33.127s; Node dashboard checks, compile and whitespace checks passed. Companion Sources PDF includes all three websites. Saved-data hashes and protected generation/calculation/provider/template files unchanged.
- Final independent review (`editor_rejection_review`, GPT-6 Astra high): two important findings, no critical/minor findings. One TDD fix pass:
  - Empty corrected JSON without any original tool calls previously reached the ordinary no-op success branch. Added regression RED→GREEN requiring corrected edits to establish supported evidence; otherwise reject and preserve the final empty response.
  - Planner refusal/invalid output could occur before the route received research results. Added a capture callback immediately after the planner response, before validation/refusal; route regression RED→GREEN preserves the actual planner output and page results on failure.
- Final: Ruling: exact cause of the user's original error remains unknown — the old code discarded that response; the fix addresses demonstrated aggregation loss and brittle rejection handling, not a claimed reconstruction of the missing result.
- Final: Ruling: existing semantic limits of quote validation remain unchanged — individual quoted sources are checked using the existing validators; analyst review is still required for meaning and locality relevance.
- Final: Ruling: live provider reliability and arbitrary citation-list layout stress were not exhaustively tested — the real replay succeeded and its three-source merged paragraph rendered in the unchanged ten-page layout; future searches may return different evidence or reach provider limits.
- Final verification: 24 focused editor tests passed; full suite 126/126 passed in 33.566s (`/tmp/property-editor-rejection-final.log`), Node dashboard tests passed, changed Python files compile and whitespace checks pass. Final saved-data hashes and protected main-research/provider/calculation/template comparison passed. No saved report regenerated, server restarted or branch/commit changed.
