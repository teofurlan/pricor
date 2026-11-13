"""Build tiny real PDFs for the tests (no PDF-writing dependency is installed)."""


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")


def pdf_bytes(pages: list[list[list[str]] | list[str]]) -> bytes:
    """One page per item: a table (list of rows, drawn with ruled lines) or lines of plain text."""
    objects: list[bytes] = []
    page_ids = []
    font_id = 3 + 2 * len(pages)
    for number, content in enumerate(pages):
        stream = ["BT /F1 10 Tf 1 0 0 1 40 790 Tm 12 TL () Tj ET"]
        if content and isinstance(content[0], list):
            cell_w, cell_h = 120, 24
            columns = max(len(row) for row in content)
            left, top = 40, 760
            for r in range(len(content) + 1):
                y = top - r * cell_h
                stream.append(f"{left} {y} m {left + columns * cell_w} {y} l S")
            for c in range(columns + 1):
                x = left + c * cell_w
                stream.append(f"{x} {top} m {x} {top - len(content) * cell_h} l S")
            for r, row in enumerate(content):
                for c, text in enumerate(row):
                    stream.append(
                        f"BT /F1 10 Tf {left + c * cell_w + 4} {top - r * cell_h - 16} Td ({_escape(text)}) Tj ET"
                    )
        else:
            for line, text in enumerate(content):
                stream.append(f"BT /F1 10 Tf 40 {760 - 14 * line} Td ({_escape(text)}) Tj ET")
        data = "\n".join(stream).encode("latin-1")
        page_id, stream_id = 3 + 2 * number, 4 + 2 * number
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {stream_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    head = [b"<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()]
    body = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate([*head, *objects], start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(offsets) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(offsets) + 1, xref)
    return body
