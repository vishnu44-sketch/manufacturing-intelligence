"""Cut the Markdown files in docs/ into chunks for the vector store.

One chunk = one '## ' section: its heading + its body, up to the next '## '.
The text before the first '## ' (the file title and intro) is not a chunk.
Each chunk text starts with the kind of document and the heading, so the
embedding knows where the text comes from.

Every chunk has two texts:
- text:       the whole section - stored and given to the AI.
- embed_text: the same without ``` code blocks - this is what becomes the vector.
  SQL is not plain English and would drown the question of an example.
"""
import re
from pathlib import Path

# the kind of each docs file (search results report it)
KIND_BY_FILE = {
    "data_dictionary.md": "table",
    "business_rules.md": "rule",
    "sql_examples.md": "example",
}
# a readable label for each kind, written in front of every chunk text
KIND_LABEL = {
    "table": "Data dictionary (ai_gold table and columns)",
    "rule": "NOP business rule",
    "example": "Example question with its SQL",
}


def split_sections(markdown):
    """Return [(heading, body), ...] for every '## ' heading of a Markdown text."""
    sections = []
    heading = None
    lines = []
    in_code = False  # a '## ' inside a ``` code block is not a heading
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if line.startswith("## ") and not in_code:
            if heading is not None:
                sections.append((heading, "\n".join(lines).strip()))
            heading = line[3:].strip()
            lines = []
        elif heading is not None:
            lines.append(line)
    if heading is not None:
        sections.append((heading, "\n".join(lines).strip()))
    return sections


def without_code(text):
    """The text with every ``` code block taken out (and the blank lines it leaves)."""
    text = re.sub(r"^```.*?^```[ \t]*$", "", text, flags=re.S | re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_markdown(markdown, source):
    """Chunks of one docs file. source = the file name, e.g. 'business_rules.md'."""
    kind = KIND_BY_FILE.get(source, "rule")  # any other docs file counts as rules text
    chunks = []
    for number, (heading, body) in enumerate(split_sections(markdown), start=1):
        text = f"{KIND_LABEL[kind]}: {heading}\n\n{body}"
        chunks.append({
            "id": f"{Path(source).stem}-{number:03d}",  # e.g. 'sql_examples-007'
            "text": text,
            "embed_text": without_code(text),
            "source": source,
            "heading": heading,
            "kind": kind,
        })
    return chunks


def load_docs(docs_dir):
    """Chunks of every docs/*.md, files in name order (so the result is always the same)."""
    chunks = []
    for path in sorted(Path(docs_dir).glob("*.md")):
        chunks.extend(chunk_markdown(path.read_text(encoding="utf-8"), path.name))
    return chunks
