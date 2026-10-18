import io
import zipfile

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from datamind.uploads.manager import UploadError, UploadManager


@pytest.fixture
def manager(tmp_path):
    return UploadManager(base_dir=tmp_path / "uploads", enabled=True)


@pytest.mark.parametrize("filename,data", [
    ("data.json", b'[{"id":1,"amount":12.5},{"id":2,"amount":20}]'),
    ("data.jsonl", b'{"id":1,"amount":12.5}\n{"id":2,"amount":20}\n'),
    ("data.tsv", b'id\tamount\n1\t12.5\n2\t20\n'),
])
def test_structured_formats_load_real_rows(manager, filename, data):
    meta = manager.ingest_file(manager.create_session(), filename, data)
    assert meta["total_rows"] == 2
    assert meta["original_filename"] == filename
    assert meta["preview"]["columns"] == ["id", "amount"]


def test_xlsx_uses_saved_values_and_rejects_multiple_sheets(manager):
    workbook = Workbook()
    workbook.active.append(["id", "amount"])
    workbook.active.append([1, 12.5])
    buffer = io.BytesIO()
    workbook.save(buffer)
    session = manager.create_session()
    assert manager.ingest_file(session, "data.xlsx", buffer.getvalue())["total_rows"] == 1
    assert any("formulas are not executed" in n for n in session.encoding_notices)
    workbook.create_sheet("Another")
    buffer = io.BytesIO()
    workbook.save(buffer)
    with pytest.raises(UploadError, match="one worksheet"):
        manager.ingest_file(session, "multi.xlsx", buffer.getvalue())


@pytest.mark.parametrize("extension", ["txt", "md", "docx", "pdf"])
def test_documents_preserve_text_and_source_locations(manager, extension):
    content = "Customer reports a delayed delivery."
    data = content.encode()
    if extension == "docx":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{content}</w:t></w:r></w:p></w:body></w:document>')
        data = buffer.getvalue()
    if extension == "pdf":
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 40 700 Td ({content}) Tj ET".encode())
        page[NameObject("/Contents")] = stream
        buffer = io.BytesIO()
        writer.write(buffer)
        data = buffer.getvalue()
    session = manager.create_session()
    meta = manager.ingest_file(session, f"report.{extension}", data)
    assert meta["total_rows"] == 1
    assert meta["preview"]["columns"] == ["chunk_id", "source_name", "source_location", "body"]
    assert content in str(meta["preview"]["rows"])
    assert f"report.{extension}" in str(meta["preview"]["rows"])


def test_empty_pdf_and_executable_uploads_fail_clearly(manager):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    for filename, data, match in (("scan.pdf", buffer.getvalue(), "OCR"), ("code.exe", b"MZ", "Unsupported")):
        with pytest.raises(UploadError, match=match):
            manager.ingest_file(manager.create_session(), filename, data)
