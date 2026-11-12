"""LangChain step H: the Markdown files in docs/ cut into chunks for the vector store (manage.py ingest_docs).

One chunk = one '## ' section: its heading + its body, up to the next '## '. LangChain's
MarkdownHeaderTextSplitter finds the sections (a '## ' inside a ``` code block is not a heading).
The text before the first '## ' (the file title and intro) is not a chunk.
Each chunk text starts with the kind of document and the heading, so the embedding knows where
the text comes from.

Every chunk has two texts:
- text:       the whole section - stored and given to the AI.
- embed_text: the same without ``` code blocks - this is what becomes the vector.
  SQL is not plain English and would drown the question of an example.

The splitter trims every line and drops the blank ones: that would take the indentation out of the
example SQL and change the stored text (and so the vectors). So every line is first tagged with its
line number, and a section's text is taken back from the file's own lines - exactly as written.
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

# the line-number tag: printable (the splitter drops other characters), at the end of the line (so a
# heading or a ``` fence still starts the line) and never empty (so no line counts as blank)
_TAG = " \u27e6L{}\u27e7"
_TAG_FOUND = re.compile(r"\u27e6L(\d+)\u27e7")


def split_sections(markdown):
    """Return [(heading, body), ...] for every '## ' heading of a Markdown text."""
    from langchain_text_splitters import MarkdownHeaderTextSplitter  # imported here: only ingest needs it

    lines = markdown.splitlines()
    tagged = "\n".join(line + _TAG.format(number) for number, line in enumerate(lines))
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("##", "heading")], strip_headers=False)
    sections = []
    for doc in splitter.split_text(tagged):
        if "heading" not in doc.metadata:  # the file title and intro before the first '## '
            continue
        heading_line = int(_TAG_FOUND.search(doc.metadata["heading"]).group(1))
        numbers = [int(n) for n in _TAG_FOUND.findall(doc.page_content) if int(n) > heading_line]
        heading = _TAG_FOUND.sub("", doc.metadata["heading"]).strip()
        sections.append((heading, "\n".join(lines[n] for n in numbers).strip()))
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
