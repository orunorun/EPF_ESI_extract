#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Streamlit app – PDF numeric‑data extractor

Two extraction modes
---------------------
* PF  – Page No, S.No, UAN
* ESI – Page No, S.No, IP Number

The extractor is tolerant to:
  - hyphens (‑) used as placeholders,
  - commas as thousand separators,
  - trailing “.00”, “.0”, etc.,
  - lines that contain only headings like “IP Contribution”.

Author : Your Name
Date   : 2026‑02‑18
"""

import io
import re
from typing import List, Tuple

import pandas as pd
import pdfplumber
import streamlit as st

# ----------------------------------------------------------------------
# Helper utilities
# ----------------------------------------------------------------------


def _normalise_token(tok: str) -> str:
    """
    Remove commas and, if the fractional part consists only of zeros,
    drop the decimal part altogether.
    Example:  "1.00" → "1",  "102,156,292,708.00" → "102156292708"
    """
    t = tok.replace(",", "")
    if "." in t:
        int_part, frac_part = t.split(".", 1)
        if set(frac_part) <= {"0"}:      # only zeros after the dot
            t = int_part
    return t


def _extract_rows_from_text(
    txt: str, page_idx: int, min_id_len: int
) -> List[Tuple[int, int, str]]:
    """
    Parses a block of text (one page) and returns rows:

        (page_no, sno, identifier)

    * `page_idx` – the real PDF page number (overwrites any printed page number).
    * `min_id_len` – minimal length of the identifier (9 for ESI, 10 for PF).  
    """
    rows: List[Tuple[int, int, str]] = []

    # Pattern that matches a sequence that *starts* with a digit and may contain commas/decimals.
    # It will NOT capture isolated hyphens or alphabetic words.
    token_pat = re.compile(r"\d[\d,]*\.?\d*")
    pure_digit_pat = re.compile(r"^\d+$")

    for raw_line in txt.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # 1️⃣  Grab every “numeric‑looking” token from the line
        raw_tokens = token_pat.findall(line)

        # 2️⃣  Clean them (remove commas, strip “.00”)
        cleaned = [_normalise_token(tok) for tok in raw_tokens]

        # 3️⃣  Keep only those that are pure digits after cleaning
        digit_tokens = [tok for tok in cleaned if pure_digit_pat.fullmatch(tok)]

        # We need at least: printed‑page‑no, S.No, identifier
        if len(digit_tokens) < 3:
            continue

        # 4️⃣  Extract the S.No (second token) – it is always a small integer
        sno = int(digit_tokens[1])

        # 5️⃣  Identifier = the right‑most token whose length ≥ min_id_len
        identifier = None
        for cand in reversed(digit_tokens):
            if len(cand) >= min_id_len:
                identifier = cand
                break

        if identifier is None:
            # No long enough token → this line is not an IP/UAN row
            continue

        rows.append((page_idx, sno, identifier))

    return rows


def _process_pdf(pdf_bytes: bytes, mode: str = "PF") -> pd.DataFrame:
    """
    Core extraction routine.

    Parameters
    ----------
    pdf_bytes : bytes
        The uploaded PDF file.
    mode : {"PF", "ESI"}
        Determines column names and minimal identifier length.

    Returns
    -------
    pd.DataFrame
        Columns = [Page No, S.No, UAN]  (PF)
               or [Page No, S.No, IP Number] (ESI)
        Sorted by Page No → S.No.
    """
    # ------------------------------------------------------------------
    # Settings for the two modes
    # ------------------------------------------------------------------
    if mode == "PF":
        col_names = ["Page No", "S.No", "UAN"]
        min_id_len = 10          # UAN = 12‑digit, we accept 10+ digits
    else:  # "ESI"
        col_names = ["Page No", "S.No", "IP Number"]
        min_id_len = 9           # IP = 10‑digit, accept 9+ digits

    all_rows: List[Tuple[int, int, str]] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total_pages = len(pdf.pages)

        # A tiny progress bar – it updates inside the `with` block
        progress_placeholder = st.empty()
        for page_no, page in enumerate(pdf.pages, start=1):
            # --------------------------------------------------------------
            # 1️⃣  Try to use tables that pdfplumber detects
            # --------------------------------------------------------------
            tables = page.extract_tables()
            if tables:
                for tbl in tables:
                    for row in tbl:
                        # Join non‑None cells to a single line string
                        line = " ".join(
                            str(cell).strip() for cell in row if cell is not None
                        )
                        if line:
                            rows = _extract_rows_from_text(line, page_no, min_id_len)
                            all_rows.extend(rows)

            # --------------------------------------------------------------
            # 2️⃣  Fallback to raw text extraction
            # --------------------------------------------------------------
            txt = page.extract_text()
            if txt:
                rows = _extract_rows_from_text(txt, page_no, min_id_len)
                all_rows.extend(rows)

            # Update progress bar
            progress_placeholder.progress(page_no / total_pages)

        # Remove progress bar after we are done
        progress_placeholder.empty()

    # ------------------------------------------------------------------
    # Build the DataFrame
    # ------------------------------------------------------------------
    df = pd.DataFrame(all_rows, columns=col_names)

    # Cast numeric columns to `int` – identifier stays as `str`
    df["Page No"] = df["Page No"].astype(int)
    df["S.No"] = df["S.No"].astype(int)

    # Sort for a clean view
    df.sort_values(by=["Page No", "S.No"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


# ----------------------------------------------------------------------
# Streamlit UI
# ----------------------------------------------------------------------
st.set_page_config(page_title="PDF Numeric Extractor", layout="wide")

st.title("🔎 PDF Numeric‑Data Extractor")
st.markdown(
    """
    **What it does** – Reads a PDF and extracts three values per line:

    * **PF mode** – Page No, S.No, UAN  
    * **ESI mode** – Page No, S.No, IP Number  

    The extractor tolerates hyphens (`-`), commas, trailing “.00”, and even header lines such as “IP Contribution”.  
    Everything happens **locally** – nothing is uploaded to a server.
    """
)

# ------------------------------------------------------------------
# Sidebar – file upload & mode selector
# ------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Settings")
    uploaded_file = st.file_uploader(
        "Upload a **PDF** file", type=["pdf"], accept_multiple_files=False
    )
    mode = st.selectbox(
        "Select extraction mode",
        options=["PF", "ESI"],
        format_func=lambda m: (
            "PF – Page No / S.No / UAN"
            if m == "PF"
            else "ESI – Page No / S.No / IP Number"
        ),
    )
    st.caption(
        "All processing is performed on your computer – the file never leaves the browser."
    )

# ------------------------------------------------------------------
# Main area – do the work when a file is present
# ------------------------------------------------------------------
if uploaded_file:
    # --------------------------------------------------------------
    # Show a quick summary of the uploaded file
    # --------------------------------------------------------------
    file_kb = uploaded_file.size / 1024
    st.success(f"✅ **{uploaded_file.name}** – {file_kb:.1f} KB uploaded")

    # --------------------------------------------------------------
    # Read the PDF bytes and run the extractor
    # --------------------------------------------------------------
    pdf_bytes = uploaded_file.read()

    with st.spinner("⏳ Extracting data from the PDF…"):
        try:
            df = _process_pdf(pdf_bytes, mode=mode)
        except Exception as exc:
            st.error(f"❌ Extraction failed – {exc}")
            st.stop()

    # --------------------------------------------------------------
    # No rows found?
    # --------------------------------------------------------------
    if df.empty:
        st.warning("🚩 No rows with a valid identifier were found in the document.")
        st.info(
            """
            **Why might this happen?**  
            * The PDF could be a scanned image (no selectable text).  
            * The identifier column may be shorter than the required length (9/10 digits).  
            * The file may not contain the expected three‑column layout.  

            For scanned PDFs you’ll need OCR (e.g. `pytesseract`). Let me know if you need that added.
            """
        )
    else:
        # --------------------------------------------------------------
        # Show the extracted table
        # --------------------------------------------------------------
        st.subheader("📊 Extracted table (first 20 rows)")
        st.dataframe(df.head(20), use_container_width=True)

        # --------------------------------------------------------------
        # Download buttons
        # --------------------------------------------------------------
        st.subheader("💾 Download results")
        csv_bytes = df.to_csv(index=False, encoding="utf-8").encode()
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Extracted")
        excel_bytes = excel_buffer.getvalue()

        c1, c2 = st.columns(2)
        c1.download_button(
            label="Download CSV",
            data=csv_bytes,
            file_name=f"{uploaded_file.name.rsplit('.', 1)[0]}_{mode}.csv",
            mime="text/csv",
        )
        c2.download_button(
            label="Download Excel",
            data=excel_bytes,
            file_name=f"{uploaded_file.name.rsplit('.', 1)[0]}_{mode}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # --------------------------------------------------------------
        # Optional quick stats / filtering
        # --------------------------------------------------------------
        with st.expander("📈 Quick stats & filters"):
            st.write("**Rows extracted** :", len(df))
            # Descriptive statistics for any numeric columns (none for PF/ESI, but kept for completeness)
            numeric_cols = df.select_dtypes(include=["int", "float"]).columns
            if len(numeric_cols):
                st.write("**Descriptive statistics**")
                st.dataframe(df[numeric_cols].describe().transpose())

            # Simple page filter (even though we already sorted)
            pages = sorted(df["Page No"].unique())
            page_filter = st.multiselect(
                "Show only selected pages",
                options=pages,
                default=pages,
            )
            if page_filter:
                filtered = df[df["Page No"].isin(page_filter)]
                st.write(f"**Rows after filter** : {len(filtered)}")
                st.dataframe(filtered.head(20), use_container_width=True)

else:
    st.info("👈 Please upload a PDF from the sidebar to start the extraction.")

# ----------------------------------------------------------------------
st.markdown(
    """
    ---
    **Built with** ❤️ using **Streamlit**, **pdfplumber**, and **pandas**.  
    Got a question or a bug? Open an issue on the GitHub repo or drop a comment below.
    """
)
