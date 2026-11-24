<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

## Sending Platform Push Gotchas (Smartlead-specific, adapt for your platform)

1. **`.join('\n')` causes double spacing** - ALWAYS `.join('')` for HTML arrays
2. **Spintax doesn't resolve in custom fields** - pre-resolve before pushing
3. **`<div>{{body_var}}</div>` adds extra wrapping** - if the custom field already contains `<div>` tags, the template should be just `{{body_var}}` with no wrapping div
4. **Max 200 custom fields per lead** - Smartlead hard limit
5. **Empty custom fields render as blank** - `{{missing_field}}` becomes empty string, causing double spaces or trailing periods
6. **Bullet prefix** - if your template expects a bullet prefix, prepend it to every bullet field value before pushing
7. **NEVER put variables inside spintax braces** - `{Hello {{first_name}}|Hi {{first_name}}}` BREAKS Smartlead

## Sequence API Rules (if also loading sequences via Smartlead)

1. **`seq_variants` NOT `sequence_variants`** for POST - they use DIFFERENT field names for read vs write
2. **ALWAYS include `id` for existing sequences** - missing `id` = creates NEW records, orphaning analytics permanently
3. **Wrap delay**: `seq_delay_details: { delay_in_days: N }` - NOT flat `delay_in_days`
4. **Body wrapper**: `{ "sequences": [...] }` - bare array = 400 error
5. **For A/B variants**: BOTH must be in `seq_variants` array - putting A only in base `email_body` = B never sends
6. **Sequence IDs != variant IDs** - passing variant IDs as `id` deletes everything
