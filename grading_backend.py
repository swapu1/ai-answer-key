from pathlib import Path
import json, re, csv, math, shutil
from difflib import SequenceMatcher
from pdf2image import convert_from_path
import pytesseract

# ---------------- CONFIG ----------------
PDF_INPUT_FOLDER = Path(r"E:\code\student_pdfs")
STUDENTS_TXT_FOLDER = Path(r"E:\code\students_txt")
OUTPUT_FOLDER = Path(r"E:\code\grading_results")
RUBRIC_FILE = Path("rubric.json")

POPPLER_PATH = r"C:\Users\swapn\Downloads\Release-24.08.0-0\poppler-24.08.0\Library\bin"
TESSERACT_EXE = r"C:\Users\swapn\tesseract.exe"

DPI = 300
MARKS_ROUND = 2
SIMILARITY_THRESHOLD = 0.65
MAX_WINDOW_WORDS = 8
# ----------------------------------------

pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE


# ---------- TEXT HELPERS ----------
def normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^\w\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def phrase_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def best_similarity(keyword: str, answer_text: str) -> float:
    if keyword in answer_text:
        return 1.0

    best = 0.0
    words = answer_text.split()
    kw_words = keyword.split()
    window = max(1, min(len(kw_words), MAX_WINDOW_WORDS))

    for i in range(len(words) - window + 1):
        chunk = " ".join(words[i:i + window])
        score = phrase_similarity(keyword, chunk)
        best = max(best, score)

    return best


# ---------- OCR ----------
def ocr_pdf_to_text(pdf_path: Path) -> str:
    images = convert_from_path(
        str(pdf_path),
        dpi=DPI,
        poppler_path=POPPLER_PATH
    )
    pages = []
    for i, img in enumerate(images, start=1):
        text = pytesseract.image_to_string(img, lang="eng")
        pages.append(f"--- PAGE {i} ---\n{text}")
    return "\n".join(pages)


def batch_ocr_pdfs():
    STUDENTS_TXT_FOLDER.mkdir(parents=True, exist_ok=True)

    pdfs = list(PDF_INPUT_FOLDER.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found in", PDF_INPUT_FOLDER)
        return

    print("Starting OCR...")
    for pdf in pdfs:
        print(" OCR:", pdf.name)
        text = ocr_pdf_to_text(pdf)
        out = STUDENTS_TXT_FOLDER / (pdf.stem + ".txt")
        out.write_text(text, encoding="utf-8")
    print("OCR completed.\n")


# ---------- GRADING ----------
def load_rubric():
    return json.loads(RUBRIC_FILE.read_text(encoding="utf-8"))


def split_answers_guess(full_text: str, qcount: int):
    splits = re.split(
        r"(?m)^\s*q\s*([0-9]+)\s*[:\-\)]?",
        full_text,
        flags=re.IGNORECASE
    )

    if len(splits) > 1:
        parts = {}
        it = iter(splits)
        next(it)
        while True:
            try:
                qn = int(next(it))
                txt = next(it)
                parts[qn] = txt.strip()
            except StopIteration:
                break
        return [parts.get(i, "") for i in range(1, qcount + 1)]

    paras = [p.strip() for p in re.split(r"\n\s*\n", full_text) if p.strip()]
    if len(paras) >= qcount:
        return paras[:qcount]

    words = full_text.split()
    if not words:
        return [""] * qcount

    chunk = math.ceil(len(words) / qcount)
    answers = []
    for i in range(0, len(words), chunk):
        answers.append(" ".join(words[i:i + chunk]))

    while len(answers) < qcount:
        answers.append("")

    return answers[:qcount]


def score_answer(answer: str, question: dict):
    ans_norm = normalize(answer)
    wc = len(re.findall(r"\w+", answer))

    earned = 0.0
    found = []

    for kw in question["keywords"]:
        k = normalize(kw["text"])
        max_marks = float(kw["marks"])

        score = best_similarity(k, ans_norm)

        if score >= SIMILARITY_THRESHOLD:
            awarded = round(max_marks * score, MARKS_ROUND)
            earned += awarded
            found.append((kw["text"], awarded, True))
        else:
            found.append((kw["text"], 0, False))

    penalty = 0.0
    wl = question.get("word_limit", 0)
    penrate = question.get("penalty_per_word", 0)

    if wl and wc < wl:
        penalty = (wl - wc) * penrate

    earned = max(0.0, earned - penalty)
    earned = min(earned, question.get("max_marks", earned))

    return round(earned, MARKS_ROUND), round(penalty, MARKS_ROUND), wc, found


def grade_student(txt_path: Path, rubric):
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    answers = split_answers_guess(text, len(rubric))

    per_q = []
    total = 0.0

    for q, ans in zip(rubric, answers):
        earned, penalty, wc, found = score_answer(ans, q)
        per_q.append({
            "id": q["id"],
            "max": q["max_marks"],
            "earned": earned,
            "penalty": penalty,
            "word_count": wc,
            "found": found
        })
        total += earned

    return per_q, round(total, MARKS_ROUND)


# ---------- OUTPUT ----------
def write_student_csv(name, per_q, total):
    p = OUTPUT_FOLDER / f"{name}_marks.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Question", "Max", "Earned", "Penalty", "WordCount", "Keywords"])
        for q in per_q:
            detail = "; ".join(
                f"{t}:{m}:{'FOUND' if ok else 'MISS'}"
                for t, m, ok in q["found"]
            )
            w.writerow([q["id"], q["max"], q["earned"], q["penalty"], q["word_count"], detail])
        w.writerow([])
        w.writerow(["TOTAL", "", total])


def write_student_report(name, per_q, total):
    p = OUTPUT_FOLDER / f"{name}_report.txt"
    with p.open("w", encoding="utf-8") as f:
        f.write(f"Student: {name}\n")
        f.write("-" * 50 + "\n")
        for q in per_q:
            f.write(f"\n{q['id']}\n")
            f.write(f"Marks: {q['earned']} / {q['max']}\n")
            f.write(f"Word Count: {q['word_count']} | Penalty: {q['penalty']}\n")
            for t, m, ok in q["found"]:
                f.write(f" {'✓' if ok else '✗'} {t} ({m})\n")
        f.write("\n" + "-" * 50 + "\n")
        f.write(f"TOTAL MARKS: {total}\n")


# ---------- MAIN ----------
def main():
    if OUTPUT_FOLDER.exists():
        shutil.rmtree(OUTPUT_FOLDER)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    batch_ocr_pdfs()

    rubric = load_rubric()
    combined = OUTPUT_FOLDER / "combined_results.csv"

    with combined.open("w", newline="", encoding="utf-8") as cf:
        cw = csv.writer(cf)
        cw.writerow(["student"] + [q["id"] for q in rubric] + ["TOTAL"])

        for txt in sorted(STUDENTS_TXT_FOLDER.glob("*.txt")):
            name = txt.stem
            print("Grading:", name)
            per_q, total = grade_student(txt, rubric)
            write_student_csv(name, per_q, total)
            write_student_report(name, per_q, total)
            cw.writerow([name] + [q["earned"] for q in per_q] + [total])

    print("\nGrading complete.")
    print("Results saved in:", OUTPUT_FOLDER)


def run_grading(pdf_input_folder, output_folder):
    global PDF_INPUT_FOLDER, OUTPUT_FOLDER
    PDF_INPUT_FOLDER = Path(pdf_input_folder)
    OUTPUT_FOLDER = Path(output_folder)
    main()

def get_student_report(output_folder, student_name):
    report_path = Path(output_folder) / f"{student_name}_report.txt"
    if not report_path.exists():
        return "Report not found."

    return report_path.read_text(encoding="utf-8", errors="replace")

def get_results_for_ui(output_folder):
    output_folder = Path(output_folder)
    combined_csv = output_folder / "combined_results.csv"

    if not combined_csv.exists():
        return []

    students = []
    with combined_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            students.append(row)

    return students

