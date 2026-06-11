---
name: structured-extraction
description: >
  Extract structured data from unstructured text documents. Produces JSON,
  tables, or key-value pairs from free-form text, emails, reports, or
  transcripts. Use when transforming unstructured content into structured formats.
metadata:
  author: hiveflow
  version: "1.0"
---

# Structured Extraction

## When to use this skill

Activate when you need to extract specific data fields, entities, relationships,
or structured records from unstructured or semi-structured text.

## Extraction process

1. **Define the schema**: Determine what fields need to be extracted. If the
   user has not specified a schema, infer one from the document type and content,
   then confirm it before proceeding. Each field should have a name, expected
   type, and whether it is required or optional.

2. **Pre-scan the document**: Read the full document to understand its structure,
   sections, and where relevant data appears. Identify recurring patterns
   (tables, lists, form fields, headers) that map to schema fields.

3. **Extract systematically**: Process the document section by section. For each
   field in the schema:
   - Locate the relevant text passage.
   - Extract and normalize the value (consistent date formats, number formats,
     proper casing for names, trimmed whitespace).
   - Note confidence level: **high** (unambiguous, clearly stated),
     **medium** (requires interpretation or inference), **low** (uncertain,
     partial match).

4. **Handle ambiguity**: When a value is unclear or could match multiple fields:
   - Flag it with the confidence annotation.
   - Provide the raw source text alongside the extracted value.
   - Prefer precision over recall — skip uncertain extractions rather than
     guessing.

5. **Validate completeness**: Check that all required fields have values. Report
   missing fields explicitly. For optional fields, distinguish between "not
   found" and "not applicable."

## Output format

Return a JSON object with these top-level keys:

```json
{
  "extracted": { ... },
  "confidence": { "field_name": "high|medium|low", ... },
  "missing": ["field_a", "field_b"],
  "notes": ["Any extraction caveats or ambiguities"]
}
```

- ``extracted``: The structured data matching the requested schema.
- ``confidence``: Per-field confidence scores.
- ``missing``: Fields that could not be extracted.
- ``notes``: Extraction caveats, ambiguities, or alternative interpretations.
