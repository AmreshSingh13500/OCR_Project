"""
[MODULE]   tests/fixtures/ground_truth.py
[TASK]     T5.1 — Test suite completion
[SUBTASKS] T5.1.1 fabricated document text/ground-truth ExtractedData for each fixture
[SUMMARY]  Single source of truth for the fabricated document content baked into the
           T5.1.1 fixtures, and the ExtractedData each content-bearing fixture should
           yield. LAB_REPORT_LINES / HANDWRITTEN_LINES are consumed by
           generate_fixtures.py to render native.pdf/scanned.pdf/printed_report.jpg and
           handwritten.jpg respectively, and by module tests that assert an OCR/vision
           result contains a known keyword. GROUND_TRUTH is consumed by the T5.1.4
           accuracy harness. password.pdf and blurry.jpg have no GROUND_TRUTH entry:
           password.pdf never reaches Step 5 (it's an error-path fixture), and
           blurry.jpg is intentionally unreadable — the harness checks it for
           "all fields null" directly rather than via field-level comparison. Every
           name/value here is fabricated for testing — never real patient data
           (CLAUDE.md, plan R7).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T5.1.1, T5.1.4
[HISTORY]  2026-07-17  T5.1.1  initial fabricated content + ground truth for 5
                                content-bearing fixtures
"""

# [T5.1.1] Native-PDF / scanned-PDF / printed-report content — same fabricated lab
# report reused across all three so one GROUND_TRUTH entry covers them (they only
# differ in *how* the same content reaches the pipeline: text layer, rasterized OCR,
# or a standalone printed image).
LAB_REPORT_LINES = [
    "LAB REPORT",
    "",
    "Patient Name: John Smith",
    "Doctor Name: Dr. Alice Johnson",
    "Diagnosis: Type 2 Diabetes Mellitus",
    "Procedure: Fasting Blood Glucose Test",
    "Cost: $120.00",
    "Medicines: Metformin 500mg, Glimepiride 2mg",
]

# [T5.1.1] Fabricated handwritten prescription note content (rendered in a cursive
# font by generate_fixtures.py) — deliberately terser/messier than the lab report to
# be representative of a real Branch-B (vision) document.
HANDWRITTEN_LINES = [
    "Rx",
    "",
    "Pt: Maria Garcia",
    "Dx: Acute Bronchitis",
    "Procedure: Chest Auscultation",
    "Cost: $45",
    "Meds: Amoxicillin 500mg,",
    "      Cough Syrup",
    "",
    "Dr. R. Mehta",
]

# [T5.1.1] Expected ExtractedData per fixture — every value is fabricated test data.
GROUND_TRUTH: dict[str, dict] = {
    "native.pdf": {
        "patient_name": "John Smith",
        "doctor_name": "Dr. Alice Johnson",
        "diagnosis": "Type 2 Diabetes Mellitus",
        "procedure": "Fasting Blood Glucose Test",
        "cost": "$120.00",
        "medicines": ["Metformin 500mg", "Glimepiride 2mg"],
    },
    "scanned.pdf": {
        "patient_name": "John Smith",
        "doctor_name": "Dr. Alice Johnson",
        "diagnosis": "Type 2 Diabetes Mellitus",
        "procedure": "Fasting Blood Glucose Test",
        "cost": "$120.00",
        "medicines": ["Metformin 500mg", "Glimepiride 2mg"],
    },
    "printed_report.jpg": {
        "patient_name": "John Smith",
        "doctor_name": "Dr. Alice Johnson",
        "diagnosis": "Type 2 Diabetes Mellitus",
        "procedure": "Fasting Blood Glucose Test",
        "cost": "$120.00",
        "medicines": ["Metformin 500mg", "Glimepiride 2mg"],
    },
    "handwritten.jpg": {
        "patient_name": "Maria Garcia",
        "doctor_name": "Dr. R. Mehta",
        "diagnosis": "Acute Bronchitis",
        "procedure": "Chest Auscultation",
        "cost": "$45",
        "medicines": ["Amoxicillin 500mg", "Cough Syrup"],
    },
    "medicine_box.jpg": {
        "patient_name": None,
        "doctor_name": None,
        "diagnosis": None,
        "procedure": None,
        "cost": None,
        "medicines": ["Paracetamol 500mg"],
    },
}
