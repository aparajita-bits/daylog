Analyze this week's daylog data and produce qualitative insights a template can't compute on its own — patterns, not totals (the totals are already computed by `dl week`).

Read the week's JSONL entries from `~/.daylog/data/` for the requested date range (default: the current ISO week, Monday–Sunday — today's date and weekday tell you which files to read).

Look for things like:

- Which days are meeting-heavy vs. which have real deep-work blocks
- What time of day focused coding tends to happen
- Whether firefighting/interruptions are trending up or down vs. a typical week
- Any ticket whose logged time is dragging on longer than expected
- Anything in the raw entry titles that hints at a recurring friction point (e.g. the same kind of interruption showing up daily)

Ground every observation in the actual entries — cite specific days or entries, don't speculate beyond what's in the data. If a week's entries include any `source` starting with `backfill-`, say so and note that conclusions about that week are less reliable. Keep it to a handful of sharp observations, not an essay.
