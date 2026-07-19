# Resource Conversion

Prefer `resource.convert_with_markitdown` for ordinary PDF or DOCX documents when the goal is structured Markdown. Prefer `resource.convert_with_pypdf` for PDF-specific page-level extraction, embedded resources, image-heavy pages, or stronger page traceability. Both actions create a Markdown target and bounded sibling asset resources; inspect the returned status and links before using generated images as later references.
