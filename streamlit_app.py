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


def build_col_map_from_header(header_row):
    """Build a mapping from raw column index (0..N-1) to target column index (0..9)
    based on header text labels. Handles merged cells spanning multiple columns.
    """
    if not header_row:
        return None

    raw_to_target = {}
    curr_target = None

    for i, cell in enumerate(header_row):
        text = " ".join(cell.split()).upper() if cell else ""

        if "NO" in text:
            curr_target = 0
        elif "SHIFT" in text:
            curr_target = 1
        elif "DATETIME IN" in text or "DATE/TIME IN" in text or "TIME IN" in text:
            curr_target = 2
        elif "LOCATION IN" in text or "LOC IN" in text:
            curr_target = 3
        elif "DATETIME OUT" in text or "DATE/TIME OUT" in text or "TIME OUT" in text:
            curr_target = 4
        elif "LOCATION OUT" in text or "LOC OUT" in text:
            curr_target = 5
        elif "BREAK HOUR" in text or "BREAK HRS" in text:
            curr_target = 6
        elif "TOTAL BREAK" in text:
            curr_target = 7
        elif "ACTUAL" in text or "WORKING HOUR" in text:
            curr_target = 9
        elif "TOTAL HOUR" in text:
            curr_target = 8

        raw_to_target[i] = curr_target

    # Fill leading unmapped indices if header didn't start at index 0
    if raw_to_target and raw_to_target.get(0) is None:
        first_valid = next((v for v in raw_to_target.values() if v is not None), 0)
        for i in range(len(header_row)):
            if raw_to_target.get(i) is None:
                raw_to_target[i] = first_valid
            else:
                break

    return raw_to_target


def normalize_row_with_map(row, raw_to_target):
    """Normalize a raw table row to exactly 10 columns using the column map."""
    if row is None:
        return None

    res = [""] * 10
    for i, cell in enumerate(row):
        t_idx = raw_to_target.get(i)
        if t_idx is not None and 0 <= t_idx < 10:
            cleaned = " ".join(cell.split()) if cell else ""
            if cleaned:
                if res[t_idx]:
                    res[t_idx] += " " + cleaned
                else:
                    res[t_idx] = cleaned

    return res


def post_process_row(row):
    """Clean up whitespace and resolve semantic misalignments in a 10-column row."""
    # 0: NO, 1: SHIFT, 2: DATETIME IN, 3: LOCATION IN,
    # 4: DATETIME OUT, 5: LOCATION OUT, 6: BREAK HOUR,
    # 7: TOTAL BREAK, 8: TOTAL HOUR, 9: ACTUAL WORKING HOUR

    # 1. If DATETIME OUT is empty and LOCATION IN is empty, but LOCATION OUT has text:
    #    The location text belongs to LOCATION IN (since clock-in location is recorded first).
    if not row[4] and not row[3] and row[5]:
        row[3] = row[5]
        row[5] = ""

    # Normalize whitespace for all cells
    return [" ".join(val.split()) for val in row]


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
                if not table:
                    continue

                # Find header row in this table if present
                col_map = None
                for row in table:
                    if row:
                        first_cell = " ".join(row[0].split()).upper() if row[0] else ""
                        row_str = " ".join(" ".join(c.split()) for c in row if c).upper()
                        if first_cell == "NO" or "DATETIME IN" in row_str:
                            col_map = build_col_map_from_header(row)
                            break

                # Fallback if no header row found in table
                if not col_map:
                    n_cols = len(table[0]) if table[0] else 10
                    if n_cols == 10:
                        col_map = {i: i for i in range(10)}
                    elif n_cols == 14:
                        # Standard 14-col layout with merged sub-columns
                        col_map = {
                            0: 0, 1: 1, 2: 2, 3: 3, 4: 3,
                            5: 4, 6: 4, 7: 5, 8: 5, 9: 6,
                            10: 7, 11: 7, 12: 8, 13: 9
                        }
                    else:
                        col_map = {i: min(i, 9) for i in range(n_cols)}
                        warnings.append(
                            f"Page {page_num}: Encountered table with unexpected column count ({n_cols} columns)."
                        )

                for row in table:
                    cleaned = normalize_row_with_map(row, col_map)
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
            merged_rows.append(post_process_row(r))
        elif merged_rows and no_val == "":
            # Continuation row — merge with previous row (page-break overflow)
            for col_idx in range(len(r)):
                if r[col_idx]:
                    merged_rows[-1][col_idx] = (
                        merged_rows[-1][col_idx] + " " + r[col_idx]
                    ).strip()
            # Post-process after merging continuation row
            merged_rows[-1] = post_process_row(merged_rows[-1])

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