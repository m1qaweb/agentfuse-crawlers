# Live pricing correction: DeepSeek transposed token matrix

The November 25–26 historical pricing export (job 883514/3/18) contains
12 numeric model-rate cells at expanded table rows 14–19, columns 3–4.
All 12 originally had model_or_service equal to the generic PRICING row
label, without a resolved billing unit or rate dimension. The retained
header excerpt and flattened text identify two model columns and three
token directions, each with explicit peak and off-peak rows. The raw
HTML body is unavailable and the raw retained table excerpt is clipped;
these facts support a narrow correction, not proof of current live DOM.

The new helper checks the exact manifest source and URL, Model Details
heading, literal model header, six contiguous labeled rows, shared
rowspan origins, and single dollar amounts. Duplicate models, changed
units, clipping, missing or ambiguous cells, and other sources fail
closed to the existing generic extractor. No guessed currency, hours,
model versions, applicability or discount math. The normal live table
pipeline retains model header, rate row and billing-time-band candidates,
keeps review-only status and blocks comparison and quote normalization.
Raw model footnote markers remain in column evidence. Other sources and
pricing table families retain their existing behavior.

Pricing parser revision is advanced to evidence_quote_v7_deepseek_transposed_context.
The existing assembly and same-snapshot replay paths use the same revision;
older windows require a fresh baseline. No source access, manifest,
containment, publisher-rights or deployment change. No current prices or
facts approved and no new requests made.

16 focused standalone helper tests passed locally. The integrated synthetic
HTML tests and existing regression suite are included for normal CI.
Full local checkout could not be obtained (GitHub DNS unavailable in
execution environment). Original HTML and live targeted validation are
still required before claiming live extraction coverage or precision.
