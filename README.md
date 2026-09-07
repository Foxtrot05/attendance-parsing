# HR Attendance Timesheet — PDF to CSV Parser

A Streamlit web app that parses HR Attendance Timesheet PDF reports and exports them as CSV files.

---

## Project Structure

```
HR/
├── app.py              # Main Streamlit application
├── requirements.txt    # Python dependencies
├── README.md           # This documentation
└── venv/               # Virtual environment (do not commit to git)
```

---

## Setup & Installation

### 1. Create a virtual environment
```bash
python -m venv venv
```

### 2. Activate the virtual environment
```bash
# Windows
venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the app
```bash
streamlit run app.py
```

The app will automatically open in your browser at `http://localhost:8501`.

---

## How to Use

1. Open the app in your browser
2. Upload an Attendance Timesheet PDF file
3. The app will parse and display a preview of the data in a table
4. Click **Download CSV** to export the result

---

## How the Pipeline Works

### Overall Flow

```
PDF Upload → pdfplumber extract tables → normalize_row() → filter & merge rows → DataFrame → CSV Download
```

### Step-by-step

#### Step 1 — Extract Tables from PDF
```python
# app.py: parse_pdf()
table_settings = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 3,
    "join_tolerance": 3,
}
```
- Uses `pdfplumber` to detect tables inside the PDF
- **Primary strategy**: uses actual ruled lines in the PDF (`lines`)
- **Fallback**: if no ruled lines are found, falls back to `extract_tables()` with auto-detection

---

#### Step 2 — Dynamic Column Mapping & Normalization (`build_col_map_from_header` & `normalize_row_with_map`)
```python
# streamlit_app.py: build_col_map_from_header() & normalize_row_with_map()
```

> **Dynamic Table Parsing**: `pdfplumber` may extract tables with varying column counts (e.g. 10 or 14 columns) when merged cells or split borders are present.

The parser automatically detects header titles (`NO`, `SHIFT`, `DATETIME IN`, `LOCATION IN`, `DATETIME OUT`, `LOCATION OUT`, etc.) and maps all raw sub-columns to the 10 target fields:
- **Merged sub-columns**: Text spanning multiple raw sub-columns under a single header field is concatenated rather than dropped.
- **Fallback**: Pre-configured sub-column mappings apply if table header rows are omitted across page breaks.
- **Semantic post-processing (`post_process_row`)**: Corrects edge cases where clock-in location text or status labels span across multiline row overflow.

---

#### Step 3 — Filter & Merge Rows
```python
# app.py: parse_pdf() — merged_rows section
```

| Row Type | Action |
|----------|--------|
| Header row (`NO` in first column) | Skip |
| Summary row (contains `OVERALL`, `ATTENDANCE`, `NAME`, `Employee`, `Department`) | Skip |
| Data row (first column is a whole number) | Append as a new record |
| Continuation row (first column is empty, previous row exists) | Merge into the previous row (page-break overflow handling) |

> **Page-break overflow**: When a data row spans two pages, pdfplumber splits the last row of page 1, and the remaining text appears as an empty-numbered row at the top of page 2. The code merges them back together.

---

#### Step 4 — Output
- A DataFrame with 10 standardised columns
- Live preview via `st.dataframe()`
- Download as `.csv` with `utf-8-sig` encoding (ensures Excel reads special characters correctly)

---

## Output Columns

| Column | Example Data |
|--------|-------------|
| `NO` | `1`, `2`, `3` … |
| `SHIFT` | `Default Shift` |
| `DATETIME IN` | `01/07/2026 09:20 AM (Late)` |
| `LOCATION IN` | `Bandar Baru Nilai, Nilai, Seremban…` |
| `DATETIME OUT` | `01/07/2026 06:34 PM (Look Good)` |
| `LOCATION OUT` | `Jalan Bucida Hijauan 1/1, Seremban…` |
| `BREAK HOUR` | *(empty or break duration)* |
| `TOTAL BREAK` | `00:00:00` |
| `TOTAL HOUR` | `09:13:51` |
| `ACTUAL WORKING HOUR` | `09:13:51` |

---

## Maintenance Guide

### If a new PDF suddenly fails to parse

**1. Check how many columns pdfplumber is extracting:**
```python
import pdfplumber
with pdfplumber.open("YOUR_FILE.pdf") as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        for t, table in enumerate(tables):
            if table:
                print(f"Page {i+1}, Table {t+1}: {len(table[0])} cols")
```

**2. If a new page has a different column layout (not 10 or 14):**
- Add a new case inside `normalize_row()` in `app.py`
- Identify which column indices contain meaningful data and add a new mapping

```python
# Example — if a 12-column layout is encountered
elif n == 12:
    COL_MAP_12_TO_10 = [0, 1, 2, 3, 4, 6, 8, 9, 10, 11]  # adjust indices as needed
    cols = [row[i] for i in COL_MAP_12_TO_10]
```

**3. If there are new row types that need to be skipped:**
- Add the new keyword to the filter list inside `parse_pdf()`:
```python
if no_val == "NO" or any(kw in no_val for kw in (
    "OVERALL", "ATTENDANCE", "NAME", "Employee", "Department",
    "NEW_KEYWORD_HERE"   # <-- add here
)):
    continue
```

---

### Adding a new export format (Excel, JSON)

Add the following inside the `if uploaded_file:` block, below the existing download button:

```python
# Excel export
import io as _io
excel_buf = _io.BytesIO()
df.to_excel(excel_buf, index=False)
st.download_button("Download Excel", excel_buf.getvalue(),
                   file_name=uploaded_file.name.replace(".pdf", ".xlsx"))
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `streamlit` | Web UI framework |
| `pdfplumber` | Extracts tables from PDF files |
| `pandas` | Data manipulation and DataFrame handling |
| `openpyxl` | Excel format support (for optional Excel export) |

---

## Known Limitations

- The PDF **must** follow the Attendance Timesheet Report format from the same HR system (table structure must be consistent)
- **Scanned PDFs (images) are not supported** — pdfplumber can only read PDFs with selectable/copyable text
- If the PDF is generated from a different version of the HR system and the table structure changes, `normalize_row()` will need to be updated accordingly
#
