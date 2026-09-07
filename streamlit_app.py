import io
import re
import pandas as pd
import pdfplumber
import streamlit as st

st.set_page_config(page_title="PDF to CSV Parser", page_icon="📄", layout="wide")
st.title("📄 Attendance Timesheet PDF to CSV Converter")

uploaded_files = st.file_uploader(
    "Upload one or more Attendance Timesheet PDF files",
    type=["pdf"],
    accept_multiple_files=True,
)

EXPECTED_COLS = [
    "NO", "SHIFT", "DATETIME IN", "LOCATION IN",
    "DATETIME OUT", "LOCATION OUT", "BREAK HOUR",
    "TOTAL BREAK", "TOTAL HOUR", "ACTUAL WORKING HOUR",
]

# Page 3 becomes 14 columns because pdfplumber inserts None spacer columns
# when merged cells or layout changes are detected.
# Header page 3: NO,SHIFT,DATETIME IN,LOCATION IN,None,DATETIME OUT,None,
#                LOCATION OUT,None,BREAK HOUR,TOTAL BREAK,None,TOTAL HOUR,ACTUAL WORKING HOUR
COL_MAP_14_TO_10 = [0, 1, 2, 3, 5, 7, 9, 10, 12, 13]


def normalize_row(row):
    """Normalize a row to exactly 10 columns.

    Returns:
        (list | None, str | None): cleaned row and an optional warning message
        if an unexpected column count was encountered.
    """
    if row is None:
        return None, None
    n = len(row)
    if n == 10:
        cols = row
        warning = None
    elif n == 14:
        cols = [row[i] for i in COL_MAP_14_TO_10]
        warning = None
    else:
        return None, f"Skipped row with unexpected column count ({n} columns)."
    return [" ".join(cell.split()) if cell else "" for cell in cols], warning


@st.cache_data(show_spinner="Parsing PDF…")
def parse_pdf(file_bytes):
    """Parse a PDF and return (DataFrame, list_of_warnings)."""
    raw_rows = []
    warnings = []

    table_settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
    }

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables(table_settings)
            if not tables:
                tables = page.extract_tables()

            for table in tables:
                for row in table:
                    cleaned, warn = normalize_row(row)
                    if warn:
                        warnings.append(f"Page {page_num}: {warn}")
                    if cleaned is not None:
                        raw_rows.append(cleaned)

    merged_rows = []
    for r in raw_rows:
        no_val = r[0].strip()

        # Skip header rows and summary rows
        if no_val == "NO" or any(kw in no_val for kw in (
            "OVERALL", "ATTENDANCE", "NAME", "Employee", "Department"
        )):
            continue

        if re.match(r"^\d+$", no_val):
            merged_rows.append(r)
        elif merged_rows and no_val == "":
            # Continuation row — merge with previous row (page-break overflow)
            for col_idx in range(len(r)):
                if r[col_idx]:
                    merged_rows[-1][col_idx] = (
                        merged_rows[-1][col_idx] + " " + r[col_idx]
                    ).strip()

    return pd.DataFrame(merged_rows, columns=EXPECTED_COLS), warnings


# ── Main processing ────────────────────────────────────────────────────────────

if uploaded_files:
    all_dfs = []       # list of (filename, DataFrame)
    all_warnings = []  # list of warning strings
    parse_errors = []  # list of error strings

    for uploaded_file in uploaded_files:
        try:
            file_bytes = uploaded_file.read()
            df, file_warnings = parse_pdf(file_bytes)

            for w in file_warnings:
                all_warnings.append(f"**{uploaded_file.name}** — {w}")

            if df.empty:
                all_warnings.append(
                    f"**{uploaded_file.name}** — No attendance records found. "
                    "Ensure this is a valid, non-scanned Attendance Timesheet PDF."
                )
            else:
                all_dfs.append((uploaded_file.name, df))

        except Exception as e:
            parse_errors.append(f"**{uploaded_file.name}**: {e}")

    # Show parse errors
    for err in parse_errors:
        st.error(
            f"❌ Failed to parse {err}\n\n"
            "Please check that the file is a valid, non-scanned Attendance Timesheet PDF."
        )

    # Show warnings in a collapsible expander
    if all_warnings:
        with st.expander(f"⚠️ {len(all_warnings)} warning(s) — click to expand", expanded=False):
            for w in all_warnings:
                st.warning(w)

    if all_dfs:
        # Combine all parsed DataFrames; add SOURCE_FILE column when batch
        if len(all_dfs) > 1:
            combined_df = pd.concat(
                [df.assign(SOURCE_FILE=name) for name, df in all_dfs],
                ignore_index=True,
            )
            combined_df = combined_df[["SOURCE_FILE"] + EXPECTED_COLS]
        else:
            combined_df = all_dfs[0][1]

        st.success(
            f"✅ Parsed **{len(combined_df)} attendance records** "
            f"from **{len(all_dfs)} file(s)**."
        )

        # Per-file breakdown (only shown when more than one file uploaded)
        if len(all_dfs) > 1:
            with st.expander("📂 Per-file breakdown", expanded=True):
                breakdown = pd.DataFrame(
                    [(name, len(df)) for name, df in all_dfs],
                    columns=["File", "Records"],
                )
                st.dataframe(breakdown, use_container_width=True, hide_index=True)

        st.dataframe(combined_df, use_container_width=True)

        # Derive a sensible base filename
        base_name = (
            all_dfs[0][0].replace(".pdf", "")
            if len(all_dfs) == 1
            else "attendance_combined"
        )

        col1, col2 = st.columns(2)

        with col1:
            csv_bytes = combined_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="⬇️ Download CSV",
                data=csv_bytes,
                file_name=f"{base_name}.csv",
                mime="text/csv",
            )

        with col2:
            excel_buf = io.BytesIO()
            combined_df.to_excel(excel_buf, index=False, engine="openpyxl")
            st.download_button(
                label="⬇️ Download Excel",
                data=excel_buf.getvalue(),
                file_name=f"{base_name}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )