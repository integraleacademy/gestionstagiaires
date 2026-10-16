# Annales integration contract

Each source is JSON at elearning_native/vtc/annales/<source-id>.json:
{ "id":"annales-2020", "title":"Annales VTC 2020", "year":2020, "source_filename":"...pdf", "source_sha256":"...", "sections":[ ... ] }

Section: {"id":"annales-2020-a", "module":"A", "title":"...", "minutes":45, "questions":[...]}

Question required keys:
- id: unique stable string e.g. annales-2020-a-01
- number: original number
- page: 1-based PDF page containing question
- prompt: original question, accurately transcribed (omit identifying candidate/header data)
- original_kind: qcm or qrc
- kind: single or multiple (QRC must be adapted to choices, no free-writing)
- options: [{"id":"a", "text":"..."},...] (original for QCM; pedagogical adaptation for QRC)
- answers: ["a",...] (historical source keys when available; distinguish inferred corrections)
- correction_origin: source or pedagogical (NEVER call inferred answer official)
- explanation: concrete worked correction, not generic boilerplate
- lesson_refs: ["A.01",...] existing lesson IDs. Check actual course coverage.
- learning_points: [specific teaching paragraphs needed to answer this question]; these will be inserted into mapped lessons and reference-linked from corrections.
- status: active or historical (historical for obsolete/ambiguous/no applicable current correction)
- update_note: nonempty for historical, explaining exact reason/change and current rule if verified
- sources: [{"title":"...","url":"https://official..."}] for verified time-sensitive rules; other topics can use source PDF reference handled centrally.
Optional: original_answer (QRC source answer), adaptation_note (required for QRC), context (French passage or table needed), image (image under media/vtc/annales/...), points (original score), topic.

QRC adaptations retain original prompt and official answer provenance; options must be plausible, explanatory and labelled pedagogical adaptations. Keep wrong options professional, not absurd. Source content can be historical while supplements explain current rule; never silently change an original choice. Historical items remain visible for study but excluded from scored evaluation. If uncertain do not fabricate correction: use historical and a precise pending-review reason. Every question must map to at least one lesson and have useful learning_points.

Do not commit originals containing candidate names/identifiers. Preserve filenames + SHA and page references. Do not print personal headers. Any needed diagram crop must not expose correction symbols or irrelevant identifiers.

Agents own only their source JSON/assets/helper extraction scripts, not manifest/course files. Root builds new immutable course version and web experience.
