# Host contract: inputs, context and permissions

This skill is stateless. The host owns memory, identity, data sources, record keeping and approval. This file describes only what the skill consumes. It does not prescribe how the host stores or retrieves anything.

## Accepted input

Any reasonable form: plain text, chat history, readable images, Markdown, JSON, search snippets, or a list of facts with source quotes.

Try to identify the following. Use whatever is present, and mark what is missing.

- `job`: the posting's original text, publish or capture date, source, how much of it is covered, and any uncertainty.
- `candidate`: experience and results the user provided or confirmed, with the subject, responsibility, dates, metric definitions, what may be disclosed, and corrections.
- `communication`: language, channel, what is actually known about the recipient, and length or format limits.
- `preferences`: the personal style rules the host **selected for this request**, and where they apply. Preferences are never a source of facts.
- `revision`: the user's specific feedback on this draft, or the rewrite goal.

These are semantic labels, not required field names, APIs, folders or back ends. A sample payload is in the repo at `examples/host-context.example.json`.

## Source strength

File type does not decide which fact wins. Follow the confirmation status the host gives, the user's latest corrections and how credible each source is. When values or employment records conflict, first drop fields already marked invalid; do not simply prefer whatever appeared last. Unconfirmed material can only be stated cautiously or marked `unverified`; never mark it `confirmed`.

Every specific, checkable claim about experience or results should point to a piece of the supplied material. If a source has no formal ID, use the document name, a quote from the user's message or a short internal label. Never invent database-style IDs.

**Summaries are not sources.** If the JD reached you through another agent's or tool's paraphrase, treat it as a summary: `jd_coverage` is `partial` or `unknown`, and any anchor you quote must be verbatim text you can actually see.

## Incomplete material

- The JD lacks responsibilities and goals → `need_jd`. Do not guess the whole job from its title.
- Part of the JD is visible and the core duties are clear → a `provisional` draft is allowed, stating clearly that the full requirements were not checked.
- The candidate has no credible experience on file → `need_evidence`. Ask only for the facts you need. Do not write a fictional bio.
- Nothing supplied supports the core need → `low_fit`, with one line on why. The user decides whether to draft anyway.
- Important evidence conflicts → avoid the conflicting claim. If it is the only key evidence, mark `blocked`.
- A platform character limit is unconfirmed → do not present any number as the platform's rule.

## What stays with the host

This skill does not read or write long-term memory, generate search keyword lists, scrape job sites, edit the candidate's records, store feedback, poll, apply for jobs or approve on the user's behalf. If the host exposes tools, whether to call them is governed by the host's task permissions; this skill grants no authority for external actions.

## Output

In conversation, lead with a complete message ready to copy. For machine integration, optionally add: JD analysis, facts cited, review status, warnings, and input version identifiers (if the host supplies them). Never output hidden chain-of-thought, and never claim to have run a model, script or independent reviewer that was not actually run.
