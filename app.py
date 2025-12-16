from flask import Flask, render_template, request
from pathlib import Path
import grading_backend
import json

app = Flask(__name__)

UPLOAD_FOLDER = Path("uploads")
OUTPUT_FOLDER = Path("outputs")
RUBRIC_FILE = Path("rubric.json")

UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")

    if not files or files[0].filename == "":
        return render_template(
            "index.html",
            message="No files selected!",
            success=False
        )

    for f in files:
        if f.filename.lower().endswith(".pdf"):
            f.save(UPLOAD_FOLDER / f.filename)

    grading_backend.run_grading(
        pdf_input_folder=str(UPLOAD_FOLDER),
        output_folder=str(OUTPUT_FOLDER)
    )

    try:
        results = grading_backend.get_results_for_ui(str(OUTPUT_FOLDER))
    except Exception:
        results = []

    return render_template(
        "index.html",
        message="✅ Grading completed!",
        success=True,
        results=results
    )


@app.route("/report/<student>")
def view_report(student):
    report = grading_backend.get_student_report(
        output_folder=str(OUTPUT_FOLDER),
        student_name=student
    )
    return render_template("report.html", student=student, report=report)


# ---------- TEACHER RUBRIC BUILDER ----------

@app.route("/rubric", methods=["GET", "POST"])
def rubric():
    message = None

    if request.method == "POST":
        qid = request.form.get("qid")
        max_marks = request.form.get("max_marks")
        word_limit = request.form.get("word_limit")
        penalty = request.form.get("penalty")
        keywords_raw = request.form.get("keywords")

        if not all([qid, max_marks, word_limit, penalty, keywords_raw]):
            message = "All fields are required."
            return render_template("rubric.html", message=message)

        keywords = []
        for line in keywords_raw.splitlines():
            if ":" in line:
                text, marks = line.split(":", 1)
                keywords.append({
                    "text": text.strip(),
                    "marks": float(marks.strip())
                })

        if RUBRIC_FILE.exists():
            rubric_data = json.loads(RUBRIC_FILE.read_text())
        else:
            rubric_data = []

        rubric_data.append({
            "id": qid.strip(),
            "max_marks": float(max_marks),
            "word_limit": int(word_limit),
            "penalty_per_word": float(penalty),
            "keywords": keywords
        })

        RUBRIC_FILE.write_text(json.dumps(rubric_data, indent=2))
        message = f"Saved {qid} successfully."

    return render_template("rubric.html", message=message)


if __name__ == "__main__":
    app.run(debug=True)












